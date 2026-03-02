# EBX Agent MCP Server — Copilot Instructions

## Setup & running

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS/Linux — or .venv\Scripts\activate on Windows
pip install -r requirements.txt
python server.py                 # starts FastAPI+uvicorn on http://localhost:8000
```

MCP endpoint: `http://localhost:8000/mcp`

## Smoke-testing the server

No test suite is configured. Use curl or the archived script `archive/test_server.py` (stdio transport) for ad-hoc checks:

```bash
# List tools
curl -s -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'

# Initialize session
curl -s -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'
```

## Architecture

Single-file server (`server.py`). The stack is: **FastMCP** (tool definitions) → **FastAPI** (HTTP host) → **uvicorn** (ASGI runner).

```
MCP client (VS Code / Claude Desktop)
    ↓  JSON-RPC over HTTP
FastAPI app  (app = FastAPI(lifespan=mcp_app.lifespan))
    ↓  mounted at /mcp
FastMCP  (mcp = FastMCP("EBX Agent MCP Server"))
    ↓  @mcp.tool() decorated async functions
httpx.AsyncClient  →  EBX Agent REST API (BASE_URL, port 8080)
```

Four tools exposed via `@mcp.tool()`:
| Tool | REST endpoint | Purpose |
|---|---|---|
| `search_schema` | `GET /agent/v1/search` | Discover tables across dataspaces |
| `get_table_definition` | `GET /agent/v1/fields` | Get field names/types/FK targets for a table |
| `execute_sql` | `POST /agent/v1/sql` | Run Apache Calcite SQL against EBX |
| `find_similar_records` | `POST /agent/v1/vector-similarity` | Top-K cosine similarity search |

`ebx-agent-api.json` is the OpenAPI spec for the underlying EBX Agent REST API — useful when adding new tools or debugging raw HTTP calls.

`archive/server.py.backup` is an older stdio-transport implementation (pre-FastMCP); ignore it for new work.

## Configuration

`BASE_URL` and `AUTH` (basic auth tuple) are constants at the top of `server.py`. Change them for different environments; do not hard-code credentials into tool logic.

## Key conventions

### Recommended tool-call workflow
Always call tools in this order when answering EBX data questions:
1. `search_schema` — find the right dataspace/dataset/path
2. `get_table_definition` — confirm exact field names before writing SQL
3. `execute_sql` — run the query

### SQL quoting (critical)
EBX uses Apache Calcite SQL. **Every** table path and field name must be double-quoted to preserve case:
- ✅ `SELECT c."Identification"."Name" FROM "/root/Companies" c`
- ❌ `SELECT c.Identification.Name FROM /root/Companies c`

Table paths must be absolute (`/root/...`) and quoted. No trailing semicolons.

### Cross-dataset joins
Tables in a different dataset must be injected via `additional_datasets` — you cannot reference them directly:
```python
execute_sql(
    sql='SELECT c."Name", r."CountryName" FROM "/root/Companies" c JOIN ref."/root/Countries" r ON c."CountryID" = r."ID"',
    dataspace="Main", dataset="CompaniesData",
    additional_datasets=[{"alias": "ref", "dataspace": "Reference", "dataset": "Geography"}]
)
```

### Foreign key dereferencing
Look up the FK target's primary key fields with `get_table_definition` (`fk_target` attribute), then use dot notation:
```sql
SELECT * FROM "/root/Employee" e JOIN "/root/Department" d ON e."fkDept"."id" = d."id"
-- composite PK:
JOIN "/root/TableB" b ON a."fkB"."id1" = b."id1" AND a."fkB"."id2" = b."id2"
```

### Vector similarity
`find_similar_records` requires the table to have a `vector_blob` field. Verify with `get_table_definition` first; do not call the tool if that field is absent.

### Performance
- Always include `LIMIT`; tell the user how many rows were capped.
- Use `ORDER BY … LIMIT` instead of `MIN`/`MAX` aggregates.
- Avoid `RIGHT JOIN` / `FULL JOIN`; prefer `INNER JOIN` or `LEFT JOIN`.
- `GROUP BY` and most aggregates (except `COUNT`) are not optimized in EBX.

### Error handling
Tools return a plain string on error. Check for the prefix `"EBX SQL Error:"` or `"HTTP Error"` and surface the `details` field from the JSON body to the user.

## EBX API reference

**TIBCO EBX® Version 6.2.3** — use this as the authoritative Java API reference:
`https://docs.tibco.com/pub/ebx/6.2.3/doc/html/en/Java_API/index.html`

## MCP client config snippets

**VS Code** (`.vscode/mcp.json`):
```json
{ "servers": { "ebx-agent": { "type": "http", "url": "http://localhost:8000/mcp" } } }
```

**Claude Desktop** (`~/Library/Application Support/Claude/claude_desktop_config.json`):
```json
{ "mcpServers": { "ebx-agent": { "type": "http", "url": "http://localhost:8000/mcp" } } }
```
