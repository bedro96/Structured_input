# Structured Input → MCP → Azure AI Foundry Agent

A **uv**-based Python ≥ 3.13 project that demonstrates:

1. An **HTTP Streamable MCP server** (FastMCP) exposing tools for structured input processing.
2. An **Azure AI Foundry agent** (`azure-ai-projects ≥ 2.0.0`) that uses the MCP server as a tool backend.
3. A **console app** that walks through the full flow end-to-end.
4. A **FastAPI REST API** that a front-end application can call to interact with the agent.

All components emit **verbose structured logs** to the console via the standard `logging` module.

---

## Requirements

| Requirement | Value |
|---|---|
| Python | ≥ 3.13 |
| Package manager | [uv](https://docs.astral.sh/uv/) |
| Azure AI Projects SDK | ≥ 2.0.0 |
| MCP transport | HTTP Streamable (FastMCP) |

---

## Quick Start

### 1. Install uv

```bash
pip install uv
```

### 2. Clone & set up

```bash
git clone <repo-url>
cd Structured_input

# Install all dependencies into a managed virtual environment
uv sync
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your Azure AI Foundry credentials
```

Required variables:

| Variable | Description |
|---|---|
| `AZURE_AI_PROJECT_ENDPOINT` | Your Foundry project endpoint URL |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Deployment name of the AI model |

Optional variables (have defaults):

| Variable | Default | Description |
|---|---|---|
| `MCP_SERVER_HOST` | `localhost` | Host the MCP server listens on |
| `MCP_SERVER_PORT` | `8000` | Port the MCP server listens on |
| `API_HOST` | `localhost` | Host the API server listens on |
| `API_PORT` | `8080` | Port the API server listens on |
| `LOG_LEVEL` | `DEBUG` | Logging verbosity |

### 4. Run the MCP server (Terminal 1)

```bash
uv run mcp-server
```

The server starts at `http://localhost:8000/mcp` using the **Streamable HTTP** transport.

### 5. Run the console demo (Terminal 2)

```bash
uv run console-app
```

This will:
- Create an agent in your Foundry project backed by the local MCP server.
- Create a conversation thread.
- Send a **customer-inquiry** structured input payload and print the agent's response.
- Send a **data-analysis** structured input payload and print the agent's response.
- Delete the agent version.

### 6. Run the API server (optional, Terminal 2)

```bash
uv run api-server
```

The API is available at `http://localhost:8080`.  Interactive docs: `http://localhost:8080/docs`.

---

## API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Service health check |
| `POST` | `/api/agents` | Create an agent version |
| `DELETE` | `/api/agents` | Delete the active agent version |
| `POST` | `/api/conversations` | Create a new conversation |
| `POST` | `/api/conversations/{id}/messages` | Send structured input to the agent |

### Example: end-to-end with `curl`

```bash
# 1. Create agent
curl -s -X POST http://localhost:8080/api/agents | jq

# 2. Create conversation
curl -s -X POST http://localhost:8080/api/conversations | jq

# 3. Send structured input (replace <conversation_id> from step 2)
curl -s -X POST http://localhost:8080/api/conversations/<conversation_id>/messages \
  -H "Content-Type: application/json" \
  -d '{
    "structured_input": {
      "type": "customer_inquiry",
      "customer_id": "CUST-001",
      "inquiry_type": "billing",
      "message": "I was charged twice for my subscription.",
      "priority": "high",
      "metadata": {"account_tier": "premium"}
    }
  }' | jq
```

---

## Project Structure

```
.
├── .env.example              # Environment variable template
├── .python-version           # Pins Python 3.13 for uv
├── pyproject.toml            # Project metadata and dependencies
├── README.md
└── src/
    ├── mcp_server/
    │   └── server.py         # FastMCP HTTP Streamable MCP server
    ├── agent/
    │   └── client.py         # Azure AI Foundry agent client
    ├── api/
    │   └── app.py            # FastAPI REST API (front-end integration)
    └── console_app.py        # Console demo (end-to-end flow)
```

---

## Authentication

Authentication to Azure uses **Entra ID** via [`DefaultAzureCredential`](https://learn.microsoft.com/python/api/azure-identity/azure.identity.defaultazurecredential).

Run `az login` (Azure CLI) before executing the demos, or configure a service principal / managed identity in your deployment environment.

---

## MCP Tools Exposed

| Tool | Description |
|---|---|
| `process_customer_inquiry` | Routes a structured customer inquiry and returns a ticket |
| `run_data_analysis` | Runs a simulated data analysis and returns insights |
| `get_server_status` | Returns the MCP server status and list of available tools |
