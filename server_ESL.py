from fastmcp import FastMCP
import httpx
import json

# 1. Initialize the FastMCP server
mcp = FastMCP("EBX_SQL_Gateway")

# 2. Configuration (Replace with your actual EBX details)
EBX_HOST = "http://localhost:8081"
EBX_ESL_REST_URL = EBX_HOST + "/ebx-dataservices/script/SqlExecutor/execute"
EBX_DATASERVICES_REST_URL = EBX_HOST + "/ebx-dataservices/rest/data/v1"
EBX_USER = "admin"
EBX_PASS = "admin"

# 3. Define the Tool using the @mcp.tool() decorator
@mcp.tool()
async def execute_ebx_sql(sql: str, dataspace: str, dataset: str, expected_columns: list[str]) -> str:
    """
    Executes an Apache Calcite SQL query against the TIBCO EBX Master Data Management system.
    
    CRITICAL RULES FOR EBX SQL:
    1. You must format your SELECT statement to return strings for every column. Wrap standard 
       non-string fields (integers, dates, booleans) in CAST(field AS VARCHAR).
    2. FOREIGN KEYS: TIBCO EBX treats foreign keys as complex objects. NEVER use CAST() on a 
       foreign key. You MUST use the native EBX function FK_AS_STRING(foreign_key_column) 
       to extract its value. Do not attempt to traverse the foreign key (e.g., fk.id).
    3. Always provide an explicit alias using AS (e.g., FK_AS_STRING(household) AS household).
    4. You MUST pass those exact aliases in the `expected_columns` array.
    """
    
    payload = {
        "sql": sql,
        "dataspace": dataspace,
        "dataset": dataset,
        "expected_columns": expected_columns
    }
    
    try:
        # Send the request to your newly created EBX ESL endpoint
        async with httpx.AsyncClient() as client:
            response = await client.post(
                EBX_ESL_REST_URL, 
                json=payload,
                auth=(EBX_USER, EBX_PASS), # Use Basic Auth or adjust for token auth
                timeout=30.0
            )
            
            # If EBX throws a syntax error (HTTP 500), return the error text to the LLM 
            # so it can read it, self-correct its SQL, and try again.
            if not response.is_success:
                return f"SQL Execution Failed (HTTP {response.status_code}): {response.text}\nReview your syntax and try again."
            
            # Return the successful rows back to the AI
            return json.dumps(response.json(), indent=2)
            
    except Exception as e:
        return f"Network or connection error communicating with EBX: {str(e)}"

@mcp.tool()
async def introspect_ebx_schema(dataspace: str, dataset: str, table_path: str = None) -> str:
    """
    Introspects the TIBCO EBX data model to retrieve the schema (tables, columns, and types).
    ALWAYS run this before executing SQL to understand the exact column names and foreign keys.
    
    Args:
        dataspace: The exact EBX dataspace name (e.g., 'BtoCCustomers').
        dataset: The exact EBX dataset name (e.g., 'BtoCCustomers').
        table_path: (Optional) A specific table path to inspect (e.g., '/root/Person'). If omitted, returns all tables.
    """
    # EBX built-in REST URLs require dataspaces to be prefixed with 'B' (Branch)
    branch_name = f"B{dataspace}"
    
    # Normalize table_path: strip leading slash, then ensure it starts with 'root/'
    # Accepts: 'Person', '/Person', 'root/Person', '/root/Person', '/root/Person/subnode'
    if table_path:
        path_suffix = table_path.lstrip("/")
        if not path_suffix.startswith("root/"):
            path_suffix = f"root/{path_suffix}"
    else:
        path_suffix = ""
    openapi_url = f"{EBX_HOST}/ebx-dataservices/rest/api/v1/data/v1/{branch_name}/{dataset}"
    if path_suffix:
        openapi_url = f"{openapi_url}/{path_suffix}"
    
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(
                openapi_url,
                auth=(EBX_USER, EBX_PASS),
                timeout=30.0
            )
            
            if not response.is_success:
                location = response.headers.get("location", "")
                hint = f" → redirected to: {location}" if location else ""
                return f"Schema introspection failed (HTTP {response.status_code}){hint}: {response.text}"
                
            openapi_spec = response.json()
            
            # Extract schema definitions from the OpenAPI spec
            schemas = openapi_spec.get("components", {}).get("schemas", {})
            
            # Known EBX REST infrastructure schemas — never actual table data
            EBX_META_SCHEMAS = {"Message", "Count", "Pagination", "ErrorItem", "Link", "Sort", "Order"}

            def collect_properties(schema_details):
                """Collect all properties from a schema, merging allOf sub-schemas."""
                props = dict(schema_details.get("properties", {}))
                for sub in schema_details.get("allOf", []):
                    if "$ref" in sub:
                        ref_name = sub["$ref"].split("/")[-1]
                        props.update(schemas.get(ref_name, {}).get("properties", {}))
                    else:
                        props.update(sub.get("properties", {}))
                return props

            output = []
            for schema_name, schema_details in schemas.items():
                # Skip EBX REST infrastructure wrappers and operation envelope schemas
                if schema_name in EBX_META_SCHEMAS:
                    continue
                if "Request" in schema_name or "Response" in schema_name:
                    continue
                    
                properties = collect_properties(schema_details)
                if not properties:
                    continue
                    
                output.append(f"### Table: {schema_name}")
                for col_name, col_info in properties.items():
                    col_type = col_info.get("type", "complex")
                    
                    # Detect EBX Foreign Keys by looking for OpenAPI $ref or tableRef metadata
                    if "$ref" in col_info or col_type == "complex":
                        col_type = "Foreign Key (MUST use FK_AS_STRING in SQL)"
                    elif col_type == "array":
                        col_type = "List/Array"
                        
                    output.append(f"- **{col_name}** ({col_type})")
                output.append("")
                
            if not output:
                return f"No schema definitions found in dataset '{dataset}'" + (f" at path '{table_path}'." if table_path else ".")
                
            return "\n".join(output)
            
    except Exception as e:
        return f"Network error during introspection: {str(e)}"

import httpx

@mcp.tool()
async def search_ebx_repository(dataspace_name: str = None) -> str:
    """
    Searches the EBX repository to discover available data.
    - If dataspace_name is omitted, traverses the entire tree and returns all OPEN, non-technical Dataspaces.
    - If dataspace_name is provided, returns a list of all Datasets inside that specific Dataspace.
    ALWAYS use this to find the correct names and descriptions before introspecting tables.
    """
    try:
        async with httpx.AsyncClient() as client:
            output = []
            
            # --- FIX 1: Bulletproof URL Parsing ---
            # Splits at '/rest' and reconstructs to guarantee 'http://.../ebx-dataservices/rest'
            base_url = EBX_DATASERVICES_REST_URL.split('/rest')[0] + '/rest'
            
            # --- PATH 1: FIND ALL DATASPACES (Recursive Tree Traversal) ---
            if not dataspace_name:
                output.append("### Available Dataspaces (Open & Business Only)")
                
                # Start at the root endpoint to dynamically get Reference and any other top-level dataspaces
                queue = [f"{base_url}/data/v1?pageSize=100"]
                
                while queue:
                    current_url = queue.pop(0)
                    
                    while current_url:
                        response = await client.get(current_url, auth=(EBX_USER, EBX_PASS), timeout=30.0)
                        
                        # Never swallow errors silently
                        if not response.is_success:
                            return f"Repository search failed on {current_url} (HTTP {response.status_code}): {response.text}"
                            
                        data = response.json()
                        items = data.get("rows", [])
                        
                        for item in items:
                            key = item.get("key", "Unknown")
                            
                            # Only process active Branches ('B'), ignore Versions ('V')
                            if not key.startswith('B'):
                                continue
                                
                            actual_name = key[1:]
                            
                            # --- Strict Filtering ---
                            if actual_name.lower().startswith("ebx-") or item.get("isTechnical") is True:
                                continue
                            if item.get("status") == "closed" or item.get("closed") is True:
                                continue
                            
                            # FIX 2: Dataspace JSON has label/description at the root (based on your payload)
                            label = item.get("label") or "No label"
                            description = item.get("description") or "No description"
                            
                            output.append(f"- **{actual_name}** | Label: {label} | Description: {description}")
                            
                            # Dynamically queue the children endpoint if this dataspace has children
                            if item.get("hasChildren") is True:
                                children_url = item.get("children")
                                if children_url:
                                    queue.append(f"{children_url}?pageSize=100")
                                
                        pagination = data.get("pagination", {})
                        current_url = pagination.get("nextPage") if pagination.get("hasNext") else None

            # --- PATH 2: FIND DATASETS IN A SPECIFIC DATASPACE ---
            else:
                output.append(f"### Available Datasets in '{dataspace_name}'")
                branch_name = f"B{dataspace_name}" if not dataspace_name.startswith("B") else dataspace_name
                current_url = f"{base_url}/data/v1/{branch_name}?pageSize=100"
                
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
                        
                    pagination = data.get("pagination", {})
                    current_url = pagination.get("nextPage") if pagination.get("hasNext") else None

            if len(output) == 1: 
                return "No open, non-technical results found."
                
            return "\n".join(output)
            
    except Exception as e:
        return f"Network error during repository search: {str(e)}"

import httpx

@mcp.tool()
async def inspect_table(dataspace: str, dataset: str, table_path: str) -> str:
    """
    Get the exact table definition and columns required to write a SQL query.
    Requires the dataspace, dataset, and table_path found via the search tool.
    """
    try:
        async with httpx.AsyncClient() as client:
            # Isolate the base REST URL
            base_url = EBX_ESL_REST_URL.split('/ebx-dataservices')[0] + '/ebx-dataservices/rest'
            
            # Ensure branch prefix is present
            branch_name = f"B{dataspace}" if not dataspace.startswith("B") else dataspace
            
            # Format table path (remove leading slash if present to avoid double slashes in URL)
            clean_path = table_path[1:] if table_path.startswith('/') else table_path
            
            # Build the URL: Request exactly 1 row, but ask for the full metamodel
            current_url = f"{base_url}/data/v1/{branch_name}/{dataset}/{clean_path}?includeMetamodel=true"
            
            response = await client.get(current_url, auth=(EBX_USER, EBX_PASS), timeout=30.0)
            
            if not response.is_success:
                return f"Failed to introspect table (HTTP {response.status_code}): {response.text}"
                
            data = response.json()
            
            # Extract the schema definitions from the 'meta' block
            meta_fields = data.get("meta", {}).get("fields", [])
            
            if not meta_fields:
                return f"Table found, but no metadata fields were returned. Ensure the table path '{table_path}' is correct."

            # Format the output specifically for the AI's context window
            output = [f"### Schema Definition for `{table_path}`"]
            output.append("| Column Name | Type | Label | Required |")
            output.append("| :--- | :--- | :--- | :--- |")
            
            for field in meta_fields:
                name = field.get("name", "Unknown")
                field_type = field.get("type", "string")
                label = field.get("label", "No label")
                
                # Check cardinality to tell the AI if the field is mandatory
                min_occurs = field.get("minOccurs", 0)
                is_required = "Yes" if min_occurs > 0 else "No"
                
                output.append(f"| `{name}` | {field_type} | {label} | {is_required} |")

            return "\n".join(output)

    except Exception as e:
        return f"Network error during table introspection: {str(e)}"

@mcp.tool()
async def list_tables_in_dataset(dataspace: str, dataset: str) -> str:
    """
    Crawls an EBX dataset schema to find all valid tables.
    Use this when you have the dataspace and dataset, but need the exact table_path 
    for the inspect_table tool.
    """
    try:
        async with httpx.AsyncClient() as client:
            base_url = EBX_ESL_REST_URL.split('/ebx-dataservices')[0] + '/ebx-dataservices/rest'
            branch_name = f"B{dataspace}" if not dataspace.startswith("B") else dataspace
            
            output = [f"### Tables found in Dataset `{dataset}`"]
            output.append("| Table Path | Label |")
            output.append("| :--- | :--- |")
            
            # Queue for Breadth-First Search. We start at the dataset root (empty path).
            queue = [""] 
            tables_found = 0
            
            while queue:
                current_path = queue.pop(0)
                
                # Fetch the current node's metamodel
                # Note: We use pageSize=1 because we only care about the schema (meta block), not the data rows
                node_url = f"{base_url}/data/v1/{branch_name}/{dataset}{current_path}?includeMetamodel=true"
                
                response = await client.get(node_url, auth=(EBX_USER, EBX_PASS), timeout=30.0)
                
                if not response.is_success:
                    continue # Skip nodes the API user doesn't have permission to read
                    
                data = response.json()
                
                # The 'meta' block contains the schema definition for the immediate children
                meta_fields = data.get("meta", {}).get("fields", [])
                
                for field in meta_fields:
                    field_name = field.get("name")
                    child_path = f"{current_path}/{field_name}"
                    
                    # In EBX, a Table is defined as an element with maxOccurs > 1
                    max_occurs = field.get("maxOccurs", 1)
                    is_table = max_occurs == "unbounded" or (isinstance(max_occurs, int) and max_occurs > 1)
                    
                    if is_table:
                        label = field.get("label", "No label")
                        output.append(f"| `{child_path}` | {label} |")
                        tables_found += 1
                    else:
                        # If it's not a table, it could be a group.
                        # Simple fields have a 'type' (e.g., 'string', 'int'). 
                        # Groups usually omit the 'type' property.
                        if "type" not in field:
                            # Queue this group to inspect its children in the next loop
                            queue.append(child_path)

            if tables_found == 0:
                return f"No tables were found in '{dataset}'. The dataset may be empty, or you lack permissions."
                
            return "\n".join(output)

    except Exception as e:
        return f"Network error during dataset crawling: {str(e)}"
        
# 4. Run the server
if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8001)
