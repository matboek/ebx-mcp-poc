from fastmcp import FastMCP
import httpx
import json

# 1. Initialize the FastMCP server
mcp = FastMCP("EBX_SQL_Gateway")

# 2. Configuration (Replace with your actual EBX details or use os.environ)
EBX_HOST = "http://localhost:8081"
EBX_ESL_REST_URL = EBX_HOST + "/ebx-dataservices/script/SqlExecutor/execute"
EBX_DATASERVICES_REST_URL = EBX_HOST + "/ebx-dataservices/rest/data/v1"
EBX_USER = "admin"
EBX_PASS = "admin"

@mcp.tool()
async def search_ebx_repository(dataspace_name: str = None) -> str:
    """
    Searches the EBX repository to discover available dataspaces and datasets.
    - If dataspace_name is omitted, recursively traverses and returns all OPEN Dataspaces.
    - If dataspace_name is provided, recursively traverses and returns all Datasets inside it.
    NEVER guess dataspace or dataset names. Always use this tool first to find them.
    """
    try:
        async with httpx.AsyncClient() as client:
            output = []
            base_url = EBX_DATASERVICES_REST_URL.split('/rest')[0] + '/rest'
            
            # --- PATH 1: FIND ALL DATASPACES (Recursive Tree Traversal) ---
            if not dataspace_name:
                output.append("### Available Dataspaces (Open & Business Only)")
                
                # Start at the root dataspaces endpoint
                queue = [f"{base_url}/data/v1?pageSize=100"]
                
                while queue:
                    current_url = queue.pop(0)
                    
                    while current_url:
                        response = await client.get(current_url, auth=(EBX_USER, EBX_PASS), timeout=30.0)
                        
                        if not response.is_success:
                            return f"Repository search failed on {current_url} (HTTP {response.status_code}): {response.text}"
                            
                        data = response.json()
                        items = data.get("rows", [])
                        
                        for item in items:
                            key = item.get("key", "Unknown")
                            
                            # Only process active Branches ('B')
                            if not key.startswith('B'):
                                continue
                                
                            actual_name = key[1:]
                            
                            # Strict filtering for system and closed dataspaces
                            if actual_name.lower().startswith("ebx-") or item.get("isTechnical") is True:
                                continue
                            if item.get("status") == "closed" or item.get("closed") is True:
                                continue
                            
                            label = item.get("label") or "No label"
                            description = item.get("description") or "No description"
                            
                            output.append(f"- **{actual_name}** | Label: {label} | Description: {description}")
                            
                            # RECURSION: If this dataspace has children, queue them up
                            if item.get("hasChildren") is True:
                                children_url = item.get("children")
                                if children_url:
                                    sep = "&" if "?" in children_url else "?"
                                    queue.append(f"{children_url}{sep}pageSize=100")
                                
                        pagination = data.get("pagination", {})
                        current_url = pagination.get("nextPage") if pagination.get("hasNext") else None

            # --- PATH 2: FIND DATASETS IN A SPECIFIC DATASPACE (Recursive Tree Traversal) ---
            else:
                output.append(f"### Available Datasets in '{dataspace_name}'")
                branch_name = f"B{dataspace_name}"
                
                # Start at the root datasets endpoint for this branch
                queue = [f"{base_url}/data/v1/{branch_name}?pageSize=100"]
                
                while queue:
                    current_url = queue.pop(0)
                    
                    while current_url:
                        response = await client.get(current_url, auth=(EBX_USER, EBX_PASS), timeout=30.0)
                        if not response.is_success:
                            return f"Failed to list datasets in {dataspace_name} (HTTP {response.status_code}): {response.text}"
                            
                        data = response.json()
                        items = data.get("rows", [])
                        
                        for item in items:
                            key = item.get("key", "Unknown")
                            
                            # Dataset JSON puts label/description inside the documentation array
                            docs = item.get("documentation")
                            doc = docs[0] if docs and len(docs) > 0 else {}
                            
                            label = doc.get("label") or "No label"
                            description = doc.get("description") or "No description"
                            
                            output.append(f"- **{key}** | Label: {label} | Description: {description}")
                            
                            # RECURSION: If this dataset has inherited children, queue them up
                            if item.get("hasChildren") is True:
                                children_url = item.get("children")
                                if children_url:
                                    sep = "&" if "?" in children_url else "?"
                                    queue.append(f"{children_url}{sep}pageSize=100")
                                    
                        pagination = data.get("pagination", {})
                        current_url = pagination.get("nextPage") if pagination.get("hasNext") else None

            if len(output) == 1: 
                return "No open, non-technical results found."
                
            return "\n".join(output)
            
    except Exception as e:
        return f"Network error during repository search: {str(e)}"

@mcp.tool()
async def list_tables_in_dataset(dataspace: str, dataset: str) -> str:
    """
    Crawls an EBX dataset schema to find all valid tables.
    Use this ONLY after finding the dataspace and dataset using search_ebx_repository.
    This returns the exact `table_path` you need for the inspect_table tool.
    """
    try:
        async with httpx.AsyncClient() as client:
            base_url = EBX_ESL_REST_URL.split('/ebx-dataservices')[0] + '/ebx-dataservices/rest'
            branch_name = f"B{dataspace}"
            
            root_url = f"{base_url}/data/v1/{branch_name}/{dataset}?includeMetamodel=true"
            
            response = await client.get(root_url, auth=(EBX_USER, EBX_PASS), timeout=30.0)
            
            if not response.is_success:
                return f"Failed to retrieve dataset metamodel (HTTP {response.status_code}): {response.text}"
                
            data = response.json()
            meta_fields = data.get("meta", {}).get("fields", [])
            
            if not meta_fields:
                return f"No metamodel fields returned for dataset '{dataset}'. It may be empty."
                
            tables_found = []
            
            def extract_tables(fields_array, parent_path=""):
                for field in fields_array:
                    path = field.get("pathInDataset")
                    if not path:
                        path = f"{parent_path}/{field.get('name')}"
                                            
                    if field.get("type") == "table":
                        label = field.get("label", "No label")
                        tables_found.append(f"| `{path}` | {label} |")
                    elif field.get("type") == "group" and "fields" in field:
                        extract_tables(field.get("fields"), path)

            extract_tables(meta_fields)
            
            if not tables_found:
                return f"No tables were found in '{dataset}'."
                
            output = [f"### Tables found in Dataset `{dataset}`"]
            output.append("| Table Path | Label |")
            output.append("| :--- | :--- |")
            output.extend(tables_found)
            
            return "\n".join(output)

    except Exception as e:
        return f"Network error during dataset crawling: {str(e)}"

@mcp.tool()
async def inspect_table(dataspace: str, dataset: str, table_path: str) -> str:
    """
    Get the exact table definition, column names, and data types required to write a SQL query.
    Requires the dataspace, dataset, and table_path found via the previous tools.
    
    PAY CLOSE ATTENTION TO THE RETURNED TYPES: 
    If a field is not a 'string', you must remember to CAST it to VARCHAR in your SQL query.
    If a field is a Foreign Key, you must use FK_AS_STRING().
    """
    try:
        async with httpx.AsyncClient() as client:
            base_url = EBX_ESL_REST_URL.split('/ebx-dataservices')[0] + '/ebx-dataservices/rest'
            branch_name = f"B{dataspace}"
            clean_path = table_path[1:] if table_path.startswith('/') else table_path
            
            current_url = f"{base_url}/data/v1/{branch_name}/{dataset}/{clean_path}?includeMetamodel=true"
            
            response = await client.get(current_url, auth=(EBX_USER, EBX_PASS), timeout=30.0)
            
            if not response.is_success:
                return f"Failed to introspect table (HTTP {response.status_code}): {response.text}"
                
            data = response.json()
            meta_fields = data.get("meta", {}).get("fields", [])
            
            if not meta_fields:
                return f"Table found, but no metadata fields were returned. Ensure path '{table_path}' is correct."

            output = [f"### Schema Definition for `{table_path}`"]
            output.append("| Column Name (Use exactly as written) | Type | Label | Required |")
            output.append("| :--- | :--- | :--- | :--- |")
            
            def flatten_schema(fields_array, prefix=""):
                for field in fields_array:
                    name = field.get("name", "Unknown")
                    full_name = f"{prefix}{name}"
                    
                    field_type = field.get("type", "string")
                    label = field.get("label", "No label")
                    min_occurs = field.get("minOccurs", 0)
                    max_occurs = field.get("maxOccurs", 1)
                    is_required = "Yes" if min_occurs > 0 else "No"
                    
                    # --- Foreign Key Detection ---
                    table_ref = field.get("tableRef")
                    if table_ref:
                        target_path = table_ref.get("tablePath", "Unknown Table")
                        field_type = f"Foreign Key -> `{target_path}`"
                        
                    # --- Association Detection ---
                    elif field.get("association") or field.get("isAssociation") or field_type == "association":
                        field_type = "Association (Virtual Link - DO NOT query directly)"
                        
                    # --- List/Array Detection ---
                    is_list = max_occurs == "unbounded" or (isinstance(max_occurs, int) and max_occurs > 1)
                    if is_list and field_type != "group":
                        if "Foreign Key" in field_type:
                            field_type += " (List/Array)"
                        else:
                            field_type = f"{field_type} (List/Array)"

                    # Recurse if group, else print leaf node
                    if field_type == "group" and "fields" in field:
                        flatten_schema(field.get("fields"), f"{full_name}.")
                    else:
                        output.append(f"| `{full_name}` | {field_type} | {label} | {is_required} |")

            flatten_schema(meta_fields)

            return "\n".join(output)

    except Exception as e:
        return f"Network error during table introspection: {str(e)}"

@mcp.tool()
async def execute_ebx_sql(sql: str, dataspace: str, dataset: str, expected_columns: list[str]) -> str:
    """
    Executes an Apache Calcite SQL query against the TIBCO EBX system.
    
    CRITICAL WARNING: The EBX API masks syntax errors. If your SQL is invalid, you will receive 
    a generic HTTP 500 error with NO debugging details. You MUST follow these rules exactly:
    
    1. TABLE ALIAS: Enclose the exact table path in double quotes and ALWAYS declare a table alias. 
       Example: FROM "/root/Customer" c
    2. NESTED GROUPS (DOT NOTATION): EBX schemas use nested groups. You must use dot notation for 
       nested fields, and you MUST prefix EVERY field with the table alias. 
       Correct: c.Address.city  |  Incorrect: Address.city OR city
    3. DATA TYPES: You must return strings for every column. Wrap standard non-string fields 
       (integers, dates, booleans) in CAST(c.field AS VARCHAR).
    4. FOREIGN KEYS: EBX treats foreign keys as complex objects. NEVER use CAST() on a foreign key. 
       You MUST use the native function: FK_AS_STRING(c.foreign_key_column).
    5. COLUMN ALIASES: Every selected column MUST have an explicit AS alias. The `expected_columns` 
       array MUST exactly match these SQL AS aliases.
    
    EXAMPLE PERFECT QUERY:
    SELECT 
        c.Identification.firstName AS first_name, 
        CAST(c.Metrics.age AS VARCHAR) AS age, 
        FK_AS_STRING(c.household) AS household_id 
    FROM "/root/Person" c
    """
    payload = {
        "sql": sql,
        "dataspace": dataspace,
        "dataset": dataset,
        "expected_columns": expected_columns
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                EBX_ESL_REST_URL, 
                json=payload,
                auth=(EBX_USER, EBX_PASS),
                timeout=30.0
            )
            
            if not response.is_success:
                return f"SQL Execution Failed (HTTP {response.status_code}). Due to API security, no syntax details are available. Review your SQL against the strict tool rules (Table Aliases, Dot Notation, CAST, FK_AS_STRING) and try again."
            
            return json.dumps(response.json(), indent=2)
            
    except Exception as e:
        return f"Network or connection error communicating with EBX: {str(e)}"

# 4. Run the server
if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8001)
