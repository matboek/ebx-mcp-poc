#!/usr/bin/env python3
import logging
from urllib import response
import httpx
from fastmcp import FastMCP
from fastapi import FastAPI
import uvicorn

logging.basicConfig(level=logging.DEBUG)

# Base URL for the EBX Agent API
BASE_URL = "http://localhost:8080/ebx-ps-fasttrack/rest"

# Basic authentication credentials
AUTH = ("admin", "admin")

# Create FastMCP server instance
mcp = FastMCP("EBX Agent MCP Server")

@mcp.tool()
async def search_schema(query: str) -> str:
    """Search the EBX schema to discover where data is stored in the repository.
    
    Searches through all dataspaces, datasets, and schema nodes to find tables matching your query.
    Returns information about table locations that you can use with other tools.
    
    Search behavior:
    - Searches across ALL valid dataspaces in the repository (excludes technical dataspaces starting with 'ebx-')
    - Matches against table labels, descriptions, and technical names (case-insensitive)
    - If a dataset name matches the query, returns ALL tables from that dataset
    - Otherwise, returns only tables whose names/labels match the query
    - Skips technical datasets (those starting with 'ebx-')
    
    Each result includes:
    - dataspace: The dataspace name where the table is located
    - dataset: The dataset name containing the table
    - path: The schema path to the table (e.g., '/root/Customer')
    - label: User-friendly display name of the table
    - description: Documentation about the table's purpose
    
    Use the returned dataspace, dataset, and path with getTableDefinition to see field details.
    
    Args:
        query: Search term to match against table names, labels, and descriptions (case-insensitive)
    
    Returns:
        JSON array of matching table locations with dataspace, dataset, path, label, and description
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/agent/v1/search",
            params={"query": query},
            auth=AUTH
        )
        response.raise_for_status()
        return response.text

@mcp.tool()
async def execute_sql(sql: str, dataspace: str, dataset: str) -> str:
    """Execute a SQL query against the EBX data repository.
    
    EBX supports standard SQL queries with some extensions. Use this tool to retrieve and analyze data.
    
    Supported SQL syntax:
    - SELECT, FROM, WHERE, GROUP BY, HAVING clauses
    - DISTINCT, ORDER BY, LIMIT and OFFSET
    - UNION [ALL] to combine queries
    - WITH clause (including RECURSIVE)
    - Subqueries and derived tables
    
    JOIN types:
    - INNER JOIN (recommended for best performance)
    - LEFT JOIN (supported)
    - RIGHT JOIN, FULL JOIN (supported but avoid if possible - less optimized)
    
    Data types (XML Schema to SQL mapping):
    - xs:string → VARCHAR, xs:boolean → BOOLEAN
    - xs:int → INT, xs:decimal → DECIMAL
    - xs:date → DATE, xs:time → TIME, xs:dateTime → TIMESTAMP
    - Complex types: Use dot notation (e.g., address.street, customer.name)
    - Foreign keys: Access via dot notation (e.g., employee.fkDept.id)
    - Lists/Arrays: Use UNNEST to query multi-valued fields
    
    Special columns (must be explicitly selected):
    - \"$pk\": String representation of primary key
    - \"$adaptation\": Record adaptation object
    - t.\"ebx-metadata\".\"system\".\"creator\": Record creator
    - t.\"ebx-metadata\".\"system\".\"creation_time\": Creation timestamp
    
    Table and field naming:
    - When referencing a table in a SQL statement, always use the full absolute path (e.g. "/root/Employee").  
      The path must be quoted and must start with /root/
    - ALWAYS use field names from get_table_definition. Do NOT guess field names.
    - Fields that belong to a complex type (a nested group) are accessed with dot‑notation: table."ComplexField"."SubField".  
      Do not use a single string like table."ComplexField.SubField".  
      Use the get_table_definition tool to discover the exact field path.
    - When you reference a sub-field of a complex type in a query, you must ALWAYS use the table name or alias as a prefix, 
      even if the field name is unique across the entire table.
      For example, if you have a table "Employee" with a complex field "Address" that has a sub-field "Street", you MUST 
      reference it as Employee."Address"."Street" in your SQL query, even if no other field is named "Street" in the entire table.
    - Absolute paths need quotes: SELECT * FROM \"/root/myTable\"
    - Reserved words need quotes: SELECT t.\"user\", t.\"order\" FROM myTable t
    - Groups with same table names: Use full path like \"my_group/my_table\"
    
    Performance tips:
    - Always use LIMIT to avoid large result sets
      Ensure you describe any LIMIT size in your response to the user so they understand how many records will be returned
    - Use ORDER BY with LIMIT instead of MIN/MAX aggregates for better performance
    - GROUP BY and most aggregates (except COUNT) are not optimized
    - Avoid RIGHT and FULL joins when possible
    - Use WHERE clauses to filter early

    Syntax notes:
    - Do not use semicolons at the end of queries

    Foreign key Dereferencing:
    - When dereferencing foreign keys, you need to find the fields of the primary key of the target table using getTableDefinition.
    - In your SQL WHERE or JOIN condition, you need to specify the table name that is referenced, then the field of the foreign key 
      Primary key using dot notation.
    - For a target table with a composite primary key, you need to specify all the fields of the primary key in your SQL condition.
    - For example, if you have an employee table with a foreign key to a department table named fkDept, and the department table has 
      a primary key 'id', you would write: SELECT * FROM employee JOIN department ON employee.fkDept.id = department.id
    - Another example if you wish to filter on a value of a foreign key: SELECT * FROM employee WHERE employee.fkDept.id = '123'

    Foreign key joins:
    - Simple FK: SELECT * FROM employee JOIN department ON employee.fkDept.id = department.id
    - Composite PK: SELECT * FROM tableA JOIN tableB ON tableA.fkB.id1 = tableB.id1 AND tableA.fkB.id2 = tableB.id2
    - Using $pk: SELECT * FROM tableA JOIN tableB ON FK_AS_STRING(tableA.fkB) = tableB.\"$pk\"
    
    Args:
        sql: SQL SELECT query to execute (read-only). The table names should be just the name, not the full path. 
             Use get_table_definition to find correct field names with dot notation for nested fields within complex types.
        dataspace: The dataspace name where the query will be executed (from search_schema results)
        dataset: The dataset name where the query will be executed (from search_schema results)
    
    Returns:
        JSON with query results including rows and column metadata
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/agent/v1/sql",
            json={
                "sql": sql,
                "dataspace": dataspace,
                "dataset": dataset
            },
            auth=AUTH
        )

        # Check if the Java API returned an error (400 or 500)
        if response.is_error:
            try:
                # Try to return the detailed JSON error from your Java API
                error_data = response.json()
                return f"EBX SQL Error: {error_data.get('details', 'Unknown error')}"
            except Exception:
                # Fallback if the response isn't valid JSON
                return f"HTTP Error {response.status_code}: {response.text}" 
            
        return response.text

@mcp.tool()
async def find_similar_records(dataspace: str, dataset: str, table_path: str, record_pk: str, k: int = 5) -> str:
    """Performs a Top-K Vector Similarity Search by comparing a target record's stored vector embedding against all other records in the same EBX table. Returns the most semantically similar records ranked by cosine similarity score.

    IMPORTANT: Only use this tool if you have confirmed that the target table contains a field named "vector_blob". Use the get_table_fields tool first to inspect the table schema before calling this tool. If "vector_blob" is not present in the field list, do NOT call this tool.

    When to use:
    - The user asks to find records that are "similar to", "like", "related to", or "semantically close to" a specific record
    - The user wants to perform a semantic or similarity search within a table
    - The target table has been confirmed to have a "vector_blob" field containing pre-computed vector embeddings

    When NOT to use:
    - The table does not have a "vector_blob" field
    - The user is asking for exact matches or filter-based lookups (use the SQL tool instead)
    - The user is searching across multiple tables

    Args:
        dataspace: The name of the EBX dataspace containing the table (e.g. "Reference")
        dataset: The name of the EBX dataset containing the table (e.g. "MIMA")
        table_path: The absolute schema path to the table (e.g. "/root/Company")
        record_pk: The primary key of the target record to compare against all others (e.g. "1")
        k: The number of top similar records to return (default: 5)

    Returns:
        A JSON array of up to k objects, sorted by descending similarity score. Each object contains:
        - "pk": the primary key of the similar record (string)
        - "score": the cosine similarity expressed as a percentage from 0.0 to 100.0, rounded to 2 decimal places (number)

        Example response:
        [
          { "pk": "7", "score": 94.12 },
          { "pk": "3", "score": 88.45 },
          { "pk": "12", "score": 76.30 }
        ]
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/agent/v1/vector-similarity",
            json={
                "dataspace": dataspace,
                "dataset": dataset,
                "tablePath": table_path,
                "recordPk": record_pk,
                "k": k
            },
            auth=AUTH
        )

        if response.is_error:
            try:
                error_data = response.json()
                return f"EBX Vector Similarity Error: {error_data.get('details', 'Unknown error')}"
            except Exception:
                return f"HTTP Error {response.status_code}: {response.text}"

        return response.text

@mcp.tool()
async def get_table_definition(dataspace: str, dataset: str, path: str) -> str:
    """Get detailed field information for a specific table in EBX.
    
    Retrieves all fields (columns) in a table, including nested fields from complex types.
    Use the dataspace, dataset, and path values returned by search_schema.
    
    Field information includes:
    - name: Full field path using dot notation (e.g., 'address.street', 'customer.name')
      Use these exact field names in SQL SELECT statements
    - label: User-friendly display name in English
    - type: XSD data type (xs:string, xs:int, xs:date, xs:boolean, etc.)
    - fk_target: Foreign key reference if this field links to another table
      Format: "DataspaceName/DatasetName/TablePath" or just "/TablePath" for same dataset
    
    Complex types and groups:
    - Nested fields use dot notation: parent.child
    - Recursively extracts all terminal (leaf) fields
    - Groups are not returned, only actual data fields
    
    Use this tool to:
    - See what columns are available before writing SQL queries
    - Get correct field names with dot notation for nested structures
    - Discover foreign key relationships between tables
    - Understand data types for proper SQL comparisons
    
    Args:
        dataspace: Dataspace name (from search_schema results)
        dataset: Dataset name (from search_schema results)
        path: Table path like '/root/Customer' (from search_schema results)
    
    Returns:
        JSON array of field definitions with name, label, type, and fk_target (null if not a FK)
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/agent/v1/fields",
            params={
                "dataspace": dataspace,
                "dataset": dataset,
                "path": path
            },
            auth=AUTH
        )

        # Check if the Java API returned an error (400 or 500)
        if response.is_error:
            try:
                # Try to return the detailed JSON error from your Java API
                error_data = response.json()
                return f"EBX SQL Error: {error_data.get('details', 'Unknown error')}"
            except Exception:
                # Fallback if the response isn't valid JSON
                return f"HTTP Error {response.status_code}: {response.text}" 
            
        return response.text

mcp_app = mcp.http_app(path="/mcp", stateless_http=True)
app = FastAPI(lifespan=mcp_app.lifespan)  # Use MCP lifespan for startup/shutdown events
app.mount("/", mcp_app)  

if __name__ == "__main__":
#    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
    uvicorn.run(app, host="0.0.0.0", port=8000)