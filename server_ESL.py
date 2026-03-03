from fastmcp import FastMCP
import httpx
import json

# 1. Initialize the FastMCP server
mcp = FastMCP("EBX_SQL_Gateway")

# 2. Configuration (Replace with your actual EBX details)
EBX_REST_URL = "http://YOUR_EBX_HOST:PORT/ebx-dataservices/rest/YOUR_MODULE/YOUR_SERVICE_PATH/executeSql"
EBX_USER = "your_username"
EBX_PASS = "your_password"

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

# 4. Run the server
if __name__ == "__main__":
    mcp.run()
