"""
FastAPI REST API server for the Structured-Input → MCP → Agent demo.

This API can be called from a front-end application.  It exposes endpoints to:
  - Check health of the service.
  - Create an agent (POST /api/agents).
  - Delete an agent version (DELETE /api/agents/{agent_name}/{agent_version}).
  - Create a conversation (POST /api/conversations).
  - Send structured input to the agent (POST /api/conversations/{id}/messages).

Prerequisites:
  - The MCP HTTP Streamable server must be running:
      uv run mcp-server
  - A valid .env file with Azure credentials (copy from .env.example).

Run:
    uv run api-server
  or
    uv run python -m src.api.app
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# Verbose logging — always on, regardless of development stage
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    force=True,
)
logger = logging.getLogger(__name__)

API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("API_PORT", "8080"))


# ---------------------------------------------------------------------------
# Shared application state (simple in-memory – replace with a store in prod)
# ---------------------------------------------------------------------------

class AppState:
    agent_client: Any = None           # FoundryAgentClient instance
    active_agent: dict[str, str] | None = None    # {name, version, id}


state = AppState()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    logger.info("API server starting up | host=%s port=%d", API_HOST, API_PORT)
    logger.info("Log level: %s", LOG_LEVEL)
    yield
    logger.info("API server shutting down")
    if state.agent_client is not None:
        try:
            state.agent_client.__exit__(None, None, None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error during agent client cleanup: %s", exc)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Structured Input → MCP → Azure AI Foundry Agent API",
    description=(
        "REST API that proxies structured input payloads to an Azure AI Foundry "
        "agent backed by an HTTP Streamable MCP server."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class AgentCreateResponse(BaseModel):
    name: str
    version: str
    id: str


class ConversationCreateResponse(BaseModel):
    conversation_id: str


class MessageRequest(BaseModel):
    json_input: dict[str, Any] = Field(
        ...,
        user_prompt="This is user input that the agent should respond to.",
        variables=[
            {
                "recipient": "Email recipient",
                "subject": "Email subject",
                "incidentId": "incident ID to notify by email.",
            }
        ],
    )
    conversation_id: str | None = Field(
        default=None,
        description="Previous conversation ID for multi-turn conversations",
    )


class MessageResponse(BaseModel):
    output: str
    conversation_id: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_client():
    """Return (or lazily create) the shared FoundryAgentClient."""
    if state.agent_client is None:
        from src.agent.client import FoundryAgentClient  # noqa: PLC0415
        logger.info("Initialising FoundryAgentClient")
        state.agent_client = FoundryAgentClient()
    return state.agent_client


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Return service health status."""
    logger.debug("Health check requested")
    return {"status": "ok", "service": "structured-input-api"}

@app.post(
    "/api/messages",
    response_model=MessageResponse,
    tags=["conversations"],
)
def process_message(body: MessageRequest) -> MessageResponse:
    """
    Receives a structured-json payload and sends it to the agent.
    If conversation_id is provided, the message is sent as part of that conversation (enabling multi-turn interactions).
    The payload is expected to contain a user prompt and any variables needed for MCP tool execution.
    The API forwards the structured input to the Azure AI Foundry agent, which may call MCP tools. 
    The agent's text response is returned in the API response, along with the conversation ID for continued interactions.

    """
    conversation_id = body.conversation_id
    logger.debug(
        "POST /api/messages received payload: json_input=%s | conversation_id=%s",
        body.json_input,
        conversation_id,
    )

    # Check if there is active agent client and if yes, use that client to send the message. 
    # If not, it means the agent has not been created yet, create a new agent client and agent version before sending the message.
    if state.agent_client is None or state.active_agent is None:
        logger.info("No active agent client found. Initialising new client and agent version.")
        client = _get_client()
        meta = client.create_agent()
        state.active_agent = meta
        logger.info("Agent ready | %s", meta)

    if conversation_id is None:
        logger.info("No conversation_id provided. Starting a new conversation.")
        new_conversation_id = state.agent_client.create_conversation()
        logger.info("New conversation started | id=%s", new_conversation_id)
        conversation_id = new_conversation_id
    try:
        output = state.agent_client.send_json_input(
            conversation_id=conversation_id,
            json_input=body.json_input,
        )
        return MessageResponse(output=output, conversation_id=conversation_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to send message: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Launching API server | host=%s port=%d", API_HOST, API_PORT)
    uvicorn.run(
        "src.api.app:app",
        host=API_HOST,
        port=API_PORT,
        reload=False,
        log_level=LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
