# EBX Agent API MCP Server

This MCP server exposes the EBX Agent API as tools that can be used with Claude Desktop or other MCP clients.

## Tools

The server provides three tools:

### 1. searchSchema
Search for schema elements in the EBX repository.

**Parameters:**
- `roots` (optional): Root path(s) to search within
- `query` (optional): Search query string

### 2. executeSql
Execute SQL queries against the EBX database.

**Parameters:**
- `sql` (required): SQL query to execute

### 3. getTableDefinition
Get field definitions and structure of a specific table.

**Parameters:**
- `dataspace` (optional): The dataspace name
- `dataset` (optional): The dataset name
- `path` (optional): The table path

## Setup

1. Create a virtual environment (recommended):
```bash
python3 -m venv .venv
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate  # On Windows
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Ensure the EBX Agent API is running at `http://localhost:8080/ebx-ps-fasttrack/rest/`

## Configuration

### Running as HTTP Server (Recommended for Testing)

Run the server with JSON-RPC over HTTP transport:
```bash
python server.py --http          # Runs on port 8000
python server.py --http 3000     # Runs on custom port
```

This starts an HTTP server with JSON-RPC endpoints:
- JSON-RPC endpoint: `POST http://localhost:8000/`
- Health check: `GET http://localhost:8000/health`

**Example requests:**
```bash
# List available tools
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# Call searchSchema tool
curl -X POST http://localhost:8000/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"searchSchema","arguments":{"query":"customer"}},"id":2}'

# Health check
curl http://localhost:8000/health
```

### Running as Stdio Server (For Claude Desktop)

Run without arguments for stdio mode:
```bash
python server.py
```

## Integration

### For Claude Desktop (Stdio Mode)

Add to your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ebx-agent": {
      "command": "python",
      "args": [
        "/Users/matboek/AI/github-copilot/server.py"
      ]
    }
  }
}
```

**Note**: Update the path in `args` to match your actual installation location.

### For MCP Clients via HTTP

Connect to the HTTP server using the JSON-RPC endpoint:
```
POST http://localhost:8000/
```

Send JSON-RPC 2.0 requests with MCP protocol methods:
- `initialize` - Initialize the server
- `tools/list` - List available tools
- `tools/call` - Execute a tool
- `ping` - Ping the server

### Testing Standalone

**HTTP Mode:**
```bash
python server.py --http
# Server starts on http://localhost:8000
# Test with MCP Inspector or curl
```

**Stdio Mode:**
```bash
python server.py
# Server communicates via stdin/stdout (MCP protocol)
```sed MCP clients.

### Testing Standalone

Run the server directly:
```bash
python server.py
```

The server will communicate over stdio using the MCP protocol.

## API Configuration

By default, the server connects to:
- Base URL: `http://localhost:8080/ebx-ps-fasttrack/rest`

To change this, modify the `BASE_URL` constant in `server.py`.

## Example Usage

Once configured in Claude Desktop, you can use natural language to interact with the EBX API:

- "Search for schemas containing 'customer'"
- "Execute this SQL query: SELECT * FROM users LIMIT 10"
- "Get the table definition for the products table in the main dataspace"
