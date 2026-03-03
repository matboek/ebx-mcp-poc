from fastmcp import FastMCP
import httpx
import json

# 1. Initialize the FastMCP server
mcp = FastMCP("EBX_SQL_Gateway")

# 2. Configuration (Replace with your actual EBX details)
EBX_HOST = "http://localhost:8081"
EBX_REST_URL = EBX_HOST + "/ebx-dataservices/script/SqlExecutor/execute"
EBX_USER = "admin"
EBX_PASS = "admin"

# 3. Define the Tool using the @mcp.tool() decorator
@mcp.tool()
async def execute_ebx_sql(sql: str, dataspace: str, dataset: str, expected_columns: list[str]) -> str:
    """
    Executes a SQL query against the TIBCO EBX Master Data Management system.
    
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
                EBX_REST_URL, 
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
        table_path: (Optional) A specific table to inspect (e.g., 'Person'). If omitted, returns all tables.
    """
    # EBX built-in REST URLs require dataspaces to be prefixed with 'B' (Branch)
    branch_name = f"B{dataspace}"
    
    # Construct the built-in EBX OpenAPI endpoint
    # Format: /rest/{category}/{categoryVersion}/{specificPath}
    openapi_url = f"{EBX_HOST}/ebx-dataservices/rest/open-api/v1/data/{branch_name}/{dataset}"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                openapi_url,
                auth=(EBX_USER, EBX_PASS),
                timeout=30.0
            )
            
            if not response.is_success:
                return f"Schema introspection failed (HTTP {response.status_code}): {response.text}"
                
            openapi_spec = response.json()
            
            # Extract just the schema definitions from the massive OpenAPI spec
            schemas = openapi_spec.get("components", {}).get("schemas", {})
            
            output = []
            for schema_name, schema_details in schemas.items():
                # Filter out REST-specific metadata wrappers (like sort arrays or pagination)
                if "Request" in schema_name or "Response" in schema_name:
                    continue
                    
                # If the AI asked for a specific table, filter for it
                if table_path and table_path.lower() not in schema_name.lower():
                    continue
                    
                properties = schema_details.get("properties", {})
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
                return f"No tables found matching '{table_path}' in dataset '{dataset}'."
                
            return "\n".join(output)
            
    except Exception as e:
        return f"Network error during introspection: {str(e)}"

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
            
            # --- PATH 1: FIND ALL DATASPACES (Recursive Tree Traversal) ---
            if not dataspace_name:
                output.append("### Available Dataspaces (Open & Business Only)")
                
                # Initialize queue with the root repository dataspace
                queue = ["BReference"]
                
                while queue:
                    current_ds = queue.pop(0)
                    current_url = f"{EBX_REST_URL.replace('/script/SqlExecutor/execute', '')}/data/v1/{current_ds}:children?pageSize=100"
                    
                    while current_url:
                        response = await client.get(current_url, auth=(EBX_USER, EBX_PASS), timeout=30.0)
                        
                        if not response.is_success:
                            break 
                            
                        data = response.json()
                        items = data.get("rows", [])
                        
                        for item in items:
                            key = item.get("key", "Unknown")
                            actual_name = key[1:] if key.startswith(('B', 'V')) else key
                            
                            # --- Strict Filtering ---
                            if actual_name.lower().startswith("ebx-") or item.get("isTechnical") is True:
                                continue
                            if item.get("status") == "closed" or item.get("closed") is True:
                                continue
                            
                            doc = item.get("documentation", [{}])[0]
                            label = doc.get("label", "No label")
                            description = doc.get("description", "No description")
                            
                            output.append(f"- **{actual_name}** | Label: {label} | Description: {description}")
                            
                            # Only queue active Branches ('B') for further traversal, ignore Versions ('V')
                            if key.startswith('B'):
                                queue.append(key)
                                
                        pagination = data.get("pagination", {})
                        current_url = pagination.get("nextPage") if pagination.get("hasNext") else None

            # --- PATH 2: FIND DATASETS IN A SPECIFIC DATASPACE ---
            else:
                output.append(f"### Available Datasets in '{dataspace_name}'")
                branch_name = f"B{dataspace_name}" if not dataspace_name.startswith("B") else dataspace_name
                current_url = f"{EBX_REST_URL.replace('/script/SqlExecutor/execute', '')}/data/v1/{branch_name}?pageSize=100"
                
                while current_url:
                    response = await client.get(current_url, auth=(EBX_USER, EBX_PASS), timeout=30.0)
                    if not response.is_success:
                        return f"Repository search failed (HTTP {response.status_code}): {response.text}"
                        
                    data = response.json()
                    items = data.get("rows", [])
                    
                    for item in items:
                        key = item.get("key", "Unknown")
                        doc = item.get("documentation", [{}])[0]
                        label = doc.get("label", "No label")
                        description = doc.get("description", "No description")
                        
                        output.append(f"- **{key}** | Label: {label} | Description: {description}")
                        
                    pagination = data.get("pagination", {})
                    current_url = pagination.get("nextPage") if pagination.get("hasNext") else None

            if len(output) == 1: 
                return "No open, non-technical results found."
                
            return "\n".join(output)
            
    except Exception as e:
        return f"Network error during repository search: {str(e)}"

# 4. Run the server
if __name__ == "__main__":
    mcp.run()
