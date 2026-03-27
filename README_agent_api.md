# EBX Agent API MCP Server

This MCP server exposes the EBX Agent API as tools that can be used with GitHub Copilot, Claude Desktop, or any other MCP-compatible client. It is built with [FastMCP](https://github.com/jlowin/fastmcp) and served over HTTP via FastAPI + uvicorn.

## Tools

The server provides three tools:

### 1. `search_schema`
Search the EBX schema to discover where data is stored in the repository.

**Parameters:**
- `query` (required): Search term to match against table names, labels, and descriptions (case-insensitive)

**Returns:** JSON array of matching table locations, each with `dataspace`, `dataset`, `path`, `label`, and `description`.

### 2. `execute_sql`
Execute a SQL SELECT query against the EBX data repository.

**Parameters:**
- `sql` (required): SQL SELECT query to execute
- `dataspace` (required): Dataspace name (from `search_schema` results)
- `dataset` (required): Dataset name (from `search_schema` results)

**Returns:** JSON with query results including rows and column metadata.

### 3. `get_table_definition`
Get detailed field information for a specific table in EBX.

**Parameters:**
- `dataspace` (required): Dataspace name (from `search_schema` results)
- `dataset` (required): Dataset name (from `search_schema` results)
- `path` (required): Table path like `/root/Customer` (from `search_schema` results)

**Returns:** JSON array of field definitions with `name`, `label`, `type`, and `fk_target`.

## Setup

1. Create a virtual environment (recommended):
\`\`\`bash
python3 -m venv .venv
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate     # On Windows
\`\`\`

2. Install dependencies:
\`\`\`bash
pip install -r requirements.txt
\`\`\`

3. Ensure the EBX Agent API is running at `http://localhost:8080/ebx-ps-fasttrack/rest`

## Running the Server

\`\`\`bash
python server.py
\`\`\`

This starts a FastAPI + uvicorn HTTP server on port 8000. The MCP endpoint is mounted at `/mcp`:

- **MCP endpoint**: `http://localhost:8000/mcp`

## API Configuration

By default the server connects to:
- **Base URL**: `http://localhost:8080/ebx-ps-fasttrack/rest`
- **Auth**: Basic auth with `admin` / `admin`

To change these, modify the `BASE_URL` and `AUTH` constants at the top of `server.py`.

## Integration

### GitHub Copilot (VS Code)

Add the server to your VS Code MCP configuration (`.vscode/mcp.json` or user settings):

\`\`\`json
{
  "servers": {
    "ebx-agent": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
\`\`\`

### Claude Desktop

Add to your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

\`\`\`json
{
  "mcpServers": {
    "ebx-agent": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
\`\`\`

### Testing with MCP Inspector or curl

\`\`\`bash
# Initialize session
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'

# List available tools
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":2}'

# Call search_schema
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"search_schema","arguments":{"query":"customer"}},"id":3}'
\`\`\`

## Example Usage

Once connected, an AI assistant can use natural language to interact with EBX:

- "Search for tables related to 'customer'"
- "Get the field definitions for the Employee table in the HR dataspace"
- "Execute this SQL: SELECT * FROM \"/root/Customer\" LIMIT 10"