# EBX SQL Gateway MCP Server

This MCP server exposes TIBCO EBX natively as tools via token-based authentication. It is built with [FastMCP](https://github.com/jlowin/fastmcp) and served over HTTP via uvicorn.

Unlike the Agent API server (`server.py`), this server talks directly to the EBX Dataservices REST API and an ESL script endpoint, giving you full control without a middleware layer.
Unlike the Agent API server (`server.py`), this server talks directly to the EBX Dataservices REST API and an ESL script endpoint, giving you full control without a middleware layer.

## Tools

The server provides five tools that must be called in order:

### 1. `login_to_ebx`
Authenticates with EBX and returns an `auth_token` string.

**Parameters:**
- `username` (required): EBX username
- `password` (required): EBX password

**Returns:** Token string (e.g. `"Token abc123…"`). Pass this to every subsequent tool call.

---

### 2. `search_ebx_repository`
Discovers available dataspaces and datasets.

**Parameters:**
- `auth_token` (required): Token from `login_to_ebx`
- `dataspace_name` (optional): If omitted, returns all open dataspaces. If provided, returns all datasets inside that dataspace.

**Returns:** Formatted list of dataspaces or datasets with labels and descriptions.

---

### 3. `list_tables_in_dataset`
Crawls a dataset's metamodel to find all queryable table paths.

**Parameters:**
- `auth_token` (required): Token from `login_to_ebx`
- `dataspace` (required): Dataspace name (from `search_ebx_repository`)
- `dataset` (required): Dataset name (from `search_ebx_repository`)

**Returns:** Markdown table of table paths and labels.

---

### 4. `inspect_table`
Returns the exact column names, types, and structure needed to write a SQL query.

**Parameters:**
- `auth_token` (required): Token from `login_to_ebx`
- `dataspace` (required): Dataspace name
- `dataset` (required): Dataset name
- `table_path` (required): Table path (e.g. `/root/Customer`) from `list_tables_in_dataset`

**Returns:** Markdown table of column names, types, labels, and whether the field is required.

> **Important:** Note the returned type for each field — non-string types must be wrapped in `CAST(… AS VARCHAR)` and foreign keys require `FK_AS_STRING(…)` in SQL.

---

### 5. `execute_ebx_sql`
Executes an Apache Calcite SQL query against EBX.

**Parameters:**
- `auth_token` (required): Token from `login_to_ebx`
- `sql` (required): SQL SELECT query
- `dataspace` (required): Dataspace name
- `dataset` (required): Dataset name
- `expected_columns` (required): List of column aliases that exactly match the `AS` aliases in the SQL

**Returns:** JSON query results.

#### SQL Rules (critical — the API gives no error details on bad SQL)

| Rule | Correct | Incorrect |
|---|---|---|
| Table path must be double-quoted with an alias | `FROM "/root/Customer" c` | `FROM /root/Customer` |
| Every field must be prefixed with the table alias | `c.Address.city` | `Address.city` |
| Non-string fields must be cast | `CAST(c.age AS VARCHAR) AS age` | `c.age AS age` |
| Foreign key fields must use native function | `FK_AS_STRING(c.household) AS household_id` | `CAST(c.household AS VARCHAR)` |
| Every selected column must have an explicit alias | `c.name AS name` | `c.name` |
| `expected_columns` must exactly match SQL aliases | `["name", "age"]` matching `AS name, AS age` | mismatched names |

**Example query:**
```sql
SELECT
    c.Identification.firstName AS first_name,
    CAST(c.Metrics.age AS VARCHAR) AS age,
    FK_AS_STRING(c.household) AS household_id
FROM "/root/Person" c
```

## EBX ESL Script Setup (required)

Before running the MCP server, you must import and publish the `AI_SQL_Gateway_ESL.xml` script into your EBX instance. This deploys the `SqlExecutor` REST endpoint that the MCP server calls.

### Step 1 — Open the Script IDE

Log in to EBX as an administrator and navigate to:

**Administration** → **Script IDE**

([Script IDE documentation](https://docs.tibco.com/pub/ebx/6.2.3/doc/html/en/script_ide/user_interface_reference.html))

### Step 2 — Import the script

1. In the Script IDE toolbar, click **Actions** → **Import**.
2. In the import dialog, select **Choose file** and pick `AI_SQL_Gateway_ESL.xml` from this repository.
3. Click **Import**. The script `rest/SqlExecutor` (labelled *AI SQL Gateway*) will appear in the script tree.

### Step 3 — Publish the script

1. Select the `rest/SqlExecutor` script in the tree.
2. Click **Actions** → **Publish** in the toolbar.
3. Confirm the dialog. EBX will compile and publish the script, making the REST endpoint live.

The endpoint will now be available at:

```
http://<your-ebx-host>/ebx-dataservices/script/SqlExecutor/execute
```

> **Note:** If you change the script path (`idePath` in the XML), update `EBX_ESL_REST_URL` in `server_ESL.py` accordingly.

---

## Setup

1. Create a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
# or
.venv\Scripts\activate     # Windows
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Ensure TIBCO EBX is running at `http://localhost:8081` and that the `SqlExecutor` ESL script is deployed at `/ebx-dataservices/script/SqlExecutor/execute`.

## Running the Server

```bash
python server_ESL.py
```

Starts the server on port **8001**. The MCP endpoint is:

- **MCP endpoint**: `http://localhost:8001/mcp`

## API Configuration

Modify these constants at the top of `server_ESL.py` to point at a different environment:

| Constant | Default |
|---|---|
| `EBX_HOST` | `http://localhost:8081` |
| `EBX_ESL_REST_URL` | `{EBX_HOST}/ebx-dataservices/script/SqlExecutor/execute` |
| `EBX_DATASERVICES_REST_URL` | `{EBX_HOST}/ebx-dataservices/rest/data/v1` |

## Integration

### GitHub Copilot (VS Code)

Add to `.vscode/mcp.json`:

```json
{
  "servers": {
    "ebx-sql-gateway": {
      "type": "http",
      "url": "http://localhost:8001/mcp"
    }
  }
}
```

### Claude Desktop

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "ebx-agent-tools": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "http://localhost:8001/mcp"
      ]
    }
  }
}
```

### OpenWebUI

OpenWebUI can use this MCP server as an external tool provider. These steps assume you already have a model configured (e.g. via Ollama). A moderately powerful model capable of agentic/function-calling behaviour is required — for example `gpt-oss:20b` or equivalent.

#### Step 1 — Register the MCP server as an External Tool

1. Open the **Admin Panel** → **Settings** → **External Tools**.
2. Click **+** to add a new entry.
3. Set the **URL** to point at the MCP server.  
   E.g. If OpenWebUI runs in Docker and the MCP server runs on the host, use:
   ```
   http://host.docker.internal:8001/mcp
   ```
4. Fill in **ID**, **Name**, and **Description** (free-form, used for display only).
5. In the **Function Name Filter List** field, type a single comma (`,`). This is a workaround for a current bug that prevents all tools from being exposed if the field is left empty.
6. Toggle **Enable** and click **Check Connection** to verify the server is reachable.

#### Step 2 — Create a model in the OpenWebUI workspace

1. Go to **Workspace** → **Models** and create a new model backed by your chosen base model.
2. **System prompt** — paste in a system prompt that instructs the model to use EBX tools correctly. The files `System_Prompt_ESL` and `System_Prompt_XPath` in this repository are ready-made starting points.
3. **Advanced params** → set **Function Calling** to **Native**.
4. **Tools** → tick the checkbox next to the MCP server entry you registered in Step 0.
5. Save the model. You can now chat with it and it will invoke the EBX MCP tools automatically.

---

## Recommended Workflow

Always call tools in this order:

1. `login_to_ebx` — authenticate and get the token
2. `search_ebx_repository` — find the right dataspace (omit `dataspace_name`)
3. `search_ebx_repository` — find the right dataset (pass `dataspace_name`)
4. `list_tables_in_dataset` — find the exact table path
5. `inspect_table` — confirm exact field names and types before writing SQL
6. `execute_ebx_sql` — run the query

## Testing with curl

```bash
# Initialize session
curl -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'

# List available tools
curl -X POST http://localhost:8001/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":2}'
```
