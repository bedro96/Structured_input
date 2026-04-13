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

load_dotenv()

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
    structured_input: dict[str, Any] = Field(
        ...,
        description="Arbitrary structured input payload to send to the agent",
        examples=[
            {
                "type": "customer_inquiry",
                "customer_id": "CUST-001",
                "inquiry_type": "billing",
                "message": "I was charged twice for my subscription.",
                "priority": "high",
                "metadata": {"account_tier": "premium"},
            }
        ],
    )
    previous_response_id: str | None = Field(
        default=None,
        description="Chain this message to a previous response for multi-turn conversations",
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
    "/api/agents",
    status_code=status.HTTP_201_CREATED,
    response_model=AgentCreateResponse,
    tags=["agents"],
)
def create_agent() -> AgentCreateResponse:
    """
    Create an Azure AI Foundry agent version backed by the MCP server.

    Only one agent version is tracked at a time. Call DELETE /api/agents to
    clean up before creating a new one.
    """
    logger.info("POST /api/agents — creating agent")
    try:
        client = _get_client()
        meta = client.create_agent()
        state.active_agent = meta
        logger.info("Agent created | %s", meta)
        return AgentCreateResponse(**meta)
    except EnvironmentError as exc:
        logger.error("Configuration error: %s", exc)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to create agent: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@app.delete(
    "/api/agents",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["agents"],
)
def delete_agent() -> None:
    """Delete the currently active agent version."""
    logger.info("DELETE /api/agents — deleting agent")
    if state.agent_client is None or state.active_agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active agent. Create one first with POST /api/agents.",
        )
    try:
        state.agent_client.delete_agent()
        state.active_agent = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to delete agent: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@app.post(
    "/api/conversations",
    status_code=status.HTTP_201_CREATED,
    response_model=ConversationCreateResponse,
    tags=["conversations"],
)
def create_conversation() -> ConversationCreateResponse:
    """Create a new conversation thread."""
    logger.info("POST /api/conversations — creating conversation")
    if state.agent_client is None or state.active_agent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active agent. Create one first with POST /api/agents.",
        )
    try:
        conv_id = state.agent_client.create_conversation()
        logger.info("Conversation created | id=%s", conv_id)
        return ConversationCreateResponse(conversation_id=conv_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to create conversation: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@app.post(
    "/api/conversations/{conversation_id}/messages",
    response_model=MessageResponse,
    tags=["conversations"],
)
def send_message(conversation_id: str, body: MessageRequest) -> MessageResponse:
    """
    Send a structured-input payload to the agent within an existing conversation.

    The payload is serialised to a JSON prompt, forwarded to the Azure AI Foundry
    agent (which may call MCP tools on the local server), and the text response
    is returned.
    """
    logger.info(
        "POST /api/conversations/%s/messages — sending structured input",
        conversation_id,
    )
    logger.debug("Payload: %s", body.structured_input)

    if state.agent_client is None or state.active_agent is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active agent. Create one first with POST /api/agents.",
        )

    try:
        output = state.agent_client.send_structured_input(
            conversation_id=conversation_id,
            structured_input=body.structured_input,
            previous_response_id=body.previous_response_id,
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
