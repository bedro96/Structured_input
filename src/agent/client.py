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
from azure.ai.projects.models import MCPTool, PromptAgentDefinition, StructuredInputDefinition
from azure.identity import AzureCliCredential
from dotenv import load_dotenv
from openai.types.responses.response_input_param import (
    McpApprovalResponse,
    ResponseInputParam,
)

load_dotenv(override=True)

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


# ---------------------------------------------------------------------------
# Agent client
# ---------------------------------------------------------------------------

class FoundryAgentClient:
    """
    High-level wrapper around AIProjectClient that creates an agent backed by
    an HTTP Streamable MCP server and sends structured input to it.
    """

    def __init__(self) -> None:
        endpoint = _require_env("AZURE_AI_PROJECT_ENDPOINT")
        model = _require_env("AZURE_AI_MODEL_DEPLOYMENT_NAME")
        agent_name = _require_env("AZURE_AI_AGENT_NAME")
        mcp_label = _require_env("MCP_SERVER_LABEL")
        mcp_url = _require_env("MCP_SERVER_URL")
        mcp_require_approval = _require_env("MCP_REQUIRE_APPROVAL")
        mcp_connection_name = _require_env("MCP_SERVER_CONNECTION_NAME")
        logger.info("Connecting to Foundry project: %s", endpoint)
        logger.info("Model deployment: %s", model)
        logger.info("MCP server URL: %s", mcp_url)

        self._endpoint = endpoint
        self._model = model
        self._agent_name = agent_name
        self._mcp_url = mcp_url
        self._mcp_require_approval = mcp_require_approval
        self._mcp_connection_name = mcp_connection_name
        self._mcp_label = mcp_label
        self._credential = AzureCliCredential()
        self._project_client = AIProjectClient(
            endpoint=self._endpoint,
            credential=self._credential,
        )
        self._openai_client = self._project_client.get_openai_client()
        self._agent_version: str | None = None

        logger.debug("AIProjectClient and OpenAI client initialised")

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def create_agent(self) -> dict[str, str]:
        """
        First checks whether an agent with *self._agent_name* already exists.
        If it does, the existing agent is reused; otherwise a brand-new agent
        is created.  In both cases a new version is then added.

        Returns a dict with agent metadata (name, version, id).
        """
        # --- Build MCP tool & agent definition --------------------------
        mcp_tool = MCPTool(
            server_label=self._mcp_label,
            server_url=self._mcp_url,
            require_approval=self._mcp_require_approval,
        )
        logger.debug("MCPTool configured: server_label=%s server_url=%s", mcp_tool.server_label, mcp_tool.server_url)

        definition = PromptAgentDefinition(
            model=self._model,
            instructions=(
                "Process the following structured json input."
                "It is imperative to use following variables for calling MCP tools. These variables have highest priority over any other means and must be used for calling MCP tools: \n\n"
                "{{recipient}} is email recipient for MCP server\n"
                "{{subject}} is email subject for MCP server\n"
                "{{incidentId}} is incident ID that is intended to use to compose email body.\n"
                "email body should start with 'Incident ID: {{incidentId}} details:' and then list all details of the incident.\n\n"
                "If user gave details from user prompt, uses that information. If no information could be found, then "
                "rest of the body should be mocked up assuming this is a real incident report from factory assembly line with details and next action items.\n\n"
            ),
            structured_inputs={
                "recipient": StructuredInputDefinition(
                    description="The recipient's email address", required=True, schema={"type": "string"},
                ),
                "subject": StructuredInputDefinition(
                    description="The email subject", required=True, schema={"type": "string"},
                ),
                "incidentId": StructuredInputDefinition(
                    description="The ID of the incident to analyze", required=True, schema={"type": "string"},
                ),
            },
            tools=[mcp_tool],
        )

        # --- Check if agent already exists ------------------------------
        try:
            existing = self._project_client.agents.get(agent_name=self._agent_name)
            logger.info("Agent '%s' already exists (id=%s) — reusing", existing.name, existing.id)
        except Exception:
            # Agent does not exist — create a brand-new agent (first version)
            logger.info("Agent '%s' not found — creating new agent", self._agent_name)
            agent = self._project_client.agents.create_version(
                agent_name=self._agent_name,
                definition=definition,
            )
            self._agent_name = agent.name
            self._agent_version = agent.version
            logger.info(
                "New agent created | name=%s version=%s id=%s",
                agent.name, agent.version, agent.id,
            )

        # --- Agent exists — add a new version ---------------------------
        logger.info("Adding new version for existing agent '%s'", self._agent_name)
        agent = self._project_client.agents.create_version(
            agent_name=self._agent_name,
            definition=definition,
        )
        self._agent_name = agent.name
        self._agent_version = agent.version
        logger.info(
            "Agent version added | name=%s version=%s id=%s",
            agent.name, agent.version, agent.id,
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

    def send_json_input(
        self,
        conversation_id: str,
        json_input: dict[str, Any],
    ) -> str:
        """
        Serialise *json_input* to a prompt string and send it to the agent
        via the Responses API, then handle any MCP approval requests automatically.

        Args:
            conversation_id: The conversation id given by user and if it is null, 
            it means it needs to generate a new conversation_id.
            json_input: Arbitrary dict that will be serialised to JSON and
                injected into the prompt.

        Returns:
            The agent's final text output.
        """
        if self._agent_name is None:
            raise RuntimeError("Call create_agent() before sending input.")


        logger.info(
            "Sending structured input to agent | conversation_id=%s agent_name=%s",
            conversation_id,
            self._agent_name,
        )
        logger.debug("Structured input payload: %s", json.dumps(json_input, indent=2))

        create_kwargs: dict[str, Any] = {
            "conversation": conversation_id,
            "input": json_input.get("user_prompt", ""),
            "extra_body": {
                "agent_reference": {
                    "name": self._agent_name,
                    "type": "agent_reference",
                },
                "structured_inputs": {"recipient": json_input.get("recipient"),
                                      "subject": json_input.get("subject"),
                                      "incidentId": json_input.get("incidentId")},
            },
        }

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
