"""
Azure AI Foundry Agent Client.

Demonstrates how to:
  1. Create an AIProjectClient connected to a Microsoft Foundry project.
  2. Create an agent version with an MCP tool pointing to the local
     HTTP Streamable MCP server.
  3. Create an OpenAI conversation (thread).
  4. Send structured input to the agent and receive the response.

Environment variables required (see .env.example):
  - AZURE_AI_PROJECT_ENDPOINT
  - AZURE_AI_MODEL_DEPLOYMENT_NAME
  - MCP_SERVER_HOST  (defaults to localhost)
  - MCP_SERVER_PORT  (defaults to 8000)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv
from openai.types.responses.response_input_param import (
    McpApprovalResponse,
    ResponseInputParam,
)

load_dotenv()

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

def _require_env(name: str) -> str:
    """Return an environment variable or raise a clear error."""
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            "Copy .env.example to .env and fill in your values."
        )
    return value


def _mcp_server_url() -> str:
    host = os.environ.get("MCP_SERVER_HOST", "localhost")
    port = os.environ.get("MCP_SERVER_PORT", "8000")
    return f"http://{host}:{port}/mcp"


# ---------------------------------------------------------------------------
# Agent client
# ---------------------------------------------------------------------------

AGENT_NAME = "structured-input-agent"


class FoundryAgentClient:
    """
    High-level wrapper around AIProjectClient that creates an agent backed by
    an HTTP Streamable MCP server and sends structured input to it.
    """

    def __init__(self) -> None:
        endpoint = _require_env("AZURE_AI_PROJECT_ENDPOINT")
        model = _require_env("AZURE_AI_MODEL_DEPLOYMENT_NAME")
        mcp_url = _mcp_server_url()

        logger.info("Connecting to Foundry project: %s", endpoint)
        logger.info("Model deployment: %s", model)
        logger.info("MCP server URL: %s", mcp_url)

        self._endpoint = endpoint
        self._model = model
        self._mcp_url = mcp_url
        self._credential = DefaultAzureCredential()
        self._project_client = AIProjectClient(
            endpoint=self._endpoint,
            credential=self._credential,
        )
        self._openai_client = self._project_client.get_openai_client()
        self._agent_name: str | None = None
        self._agent_version: str | None = None

        logger.debug("AIProjectClient and OpenAI client initialised")

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def create_agent(self) -> dict[str, str]:
        """
        Create (or update) an agent version with the MCP tool attached.

        Returns a dict with agent metadata (name, version, id).
        """
        logger.info("Creating agent '%s' with MCP tool at %s", AGENT_NAME, self._mcp_url)

        mcp_tool = MCPTool(
            server_label="structured-input-mcp",
            server_url=self._mcp_url,
            # Do not require human approval so the agent can call tools freely.
            require_approval="never",
        )
        logger.debug("MCPTool configured: server_label=%s server_url=%s", mcp_tool.server_label, mcp_tool.server_url)

        agent = self._project_client.agents.create_version(
            agent_name=AGENT_NAME,
            definition=PromptAgentDefinition(
                model=self._model,
                instructions=(
                    "You are a helpful assistant that processes structured customer "
                    "inquiries and data analysis requests. Use the available MCP tools "
                    "to route customer inquiries and run data analyses. Always respond "
                    "in a clear, concise manner."
                ),
                tools=[mcp_tool],
            ),
        )

        self._agent_name = agent.name
        self._agent_version = agent.version

        logger.info(
            "Agent created | name=%s version=%s id=%s",
            agent.name,
            agent.version,
            agent.id,
        )
        return {"name": agent.name, "version": str(agent.version), "id": agent.id}

    def delete_agent(self) -> None:
        """Delete the agent version created in this session."""
        if self._agent_name and self._agent_version:
            logger.info(
                "Deleting agent version | name=%s version=%s",
                self._agent_name,
                self._agent_version,
            )
            self._project_client.agents.delete_version(
                agent_name=self._agent_name,
                agent_version=self._agent_version,
            )
            logger.info("Agent version deleted")
        else:
            logger.warning("No agent to delete (create_agent was not called)")

    # ------------------------------------------------------------------
    # Conversation & structured input
    # ------------------------------------------------------------------

    def create_conversation(self) -> str:
        """Create a new conversation and return its id."""
        logger.info("Creating conversation thread")
        conversation = self._openai_client.conversations.create()
        logger.info("Conversation created | id=%s", conversation.id)
        return conversation.id

    def send_structured_input(
        self,
        conversation_id: str,
        structured_input: dict[str, Any],
        *,
        previous_response_id: str | None = None,
    ) -> str:
        """
        Serialise *structured_input* to a prompt string and send it to the agent
        via the Responses API, then handle any MCP approval requests automatically.

        Args:
            conversation_id: The conversation id returned by ``create_conversation``.
            structured_input: Arbitrary dict that will be serialised to JSON and
                injected into the prompt.
            previous_response_id: Chain to a previous response for multi-turn
                conversations.

        Returns:
            The agent's final text output.
        """
        if self._agent_name is None:
            raise RuntimeError("Call create_agent() before sending input.")

        prompt = (
            "Process the following structured input and use your tools as needed:\n\n"
            f"```json\n{json.dumps(structured_input, indent=2)}\n```"
        )

        logger.info(
            "Sending structured input to agent | conversation_id=%s agent_name=%s",
            conversation_id,
            self._agent_name,
        )
        logger.debug("Structured input payload: %s", json.dumps(structured_input, indent=2))

        create_kwargs: dict[str, Any] = {
            "conversation": conversation_id,
            "input": prompt,
            "extra_body": {
                "agent_reference": {
                    "name": self._agent_name,
                    "type": "agent_reference",
                }
            },
        }
        if previous_response_id:
            create_kwargs["previous_response_id"] = previous_response_id

        response = self._openai_client.responses.create(**create_kwargs)
        logger.debug("Initial response received | id=%s", response.id)

        # Handle any MCP tool-approval requests the agent raises
        approval_list: ResponseInputParam = []
        for item in response.output:
            if item.type == "mcp_approval_request":
                logger.info(
                    "MCP approval request received | server=%s id=%s — auto-approving",
                    item.server_label,
                    item.id,
                )
                approval_list.append(
                    McpApprovalResponse(
                        type="mcp_approval_response",
                        approve=True,
                        approval_request_id=item.id,
                    )
                )

        if approval_list:
            logger.info("Sending %d approval(s) and awaiting final response", len(approval_list))
            response = self._openai_client.responses.create(
                input=approval_list,
                previous_response_id=response.id,
                extra_body={
                    "agent_reference": {
                        "name": self._agent_name,
                        "type": "agent_reference",
                    }
                },
            )
            logger.debug("Final response received after approvals | id=%s", response.id)

        output_text: str = response.output_text
        logger.info("Agent response received (length=%d chars)", len(output_text))
        logger.debug("Agent output: %s", output_text)
        return output_text

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> "FoundryAgentClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self._openai_client.__exit__(*_)
        self._project_client.__exit__(*_)
        self._credential.__exit__(*_)
