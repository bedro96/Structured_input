"""
Azure AI Foundry 에이전트 클라이언트.

다음 작업 방법을 보여줍니다:
  1. Microsoft Foundry 프로젝트에 연결된 AIProjectClient 생성.
  2. 로컬 HTTP Streamable MCP 서버를 가리키는 MCP 툴이 포함된 에이전트 버전 생성.
  3. OpenAI 대화(thread) 생성.
  4. 에이전트에 구조화된 입력을 전송하고 응답 수신.

필요한 환경 변수 (.env.example 참조):
  - AZURE_AI_PROJECT_ENDPOINT
  - AZURE_AI_MODEL_DEPLOYMENT_NAME
  - MCP_SERVER_HOST  (기본값: localhost)
  - MCP_SERVER_PORT  (기본값: 8000)

참고 문서:
  - Azure AI Foundry 에이전트 개요:
    https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/overview
  - AIProjectClient Python SDK:
    https://learn.microsoft.com/ko-kr/python/api/azure-ai-projects/azure.ai.projects.aiprojectclient
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
# 설정 헬퍼
# ---------------------------------------------------------------------------

def _require_env(name: str) -> str:
    """환경 변수를 반환하거나, 설정되지 않은 경우 명확한 오류를 발생시킵니다."""
    value = os.environ.get(name)
    if not value:
        raise EnvironmentError(
            f"Required environment variable '{name}' is not set. "
            "Copy .env.example to .env and fill in your values."
        )
    return value


# ---------------------------------------------------------------------------
# 에이전트 클라이언트
# ---------------------------------------------------------------------------

class FoundryAgentClient:
    """
    HTTP Streamable MCP 서버를 기반으로 하는 에이전트를 생성하고
    구조화된 입력을 전송하는 AIProjectClient 고수준 래퍼 클래스.

    참고 문서:
      - Azure AI Foundry 에이전트 빠른 시작:
        https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/quickstart
      - MCP 툴 통합:
        https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/tools/model-context-protocol
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
        self._credential = AzureCliCredential()  # Azure CLI 자격 증명으로 인증 (az login 선행 필요)
        self._project_client = AIProjectClient(
            endpoint=self._endpoint,
            credential=self._credential,
        )  # Foundry 프로젝트에 연결된 클라이언트 초기화
        self._openai_client = self._project_client.get_openai_client()  # Responses/Conversations API 호출에 사용할 OpenAI 호환 클라이언트 획득
        self._agent_version: str | None = None  # create_agent() 호출 후 설정되는 현재 세션의 에이전트 버전

        logger.debug("AIProjectClient and OpenAI client initialised")

    # ------------------------------------------------------------------
    # 에이전트 생명주기
    # ------------------------------------------------------------------

    def create_agent(self) -> dict[str, str]:
        """
        *self._agent_name* 과 동일한 이름의 에이전트가 이미 존재하는지 먼저 확인합니다.
        존재하는 경우 기존 에이전트를 재사용하고, 존재하지 않으면 새 에이전트를 생성합니다.
        두 경우 모두 새 버전을 추가합니다.

        반환값:
            에이전트 메타데이터(name, version, id)를 담은 딕셔너리.

        참고 문서:
          - 에이전트 버전 관리:
            https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/
        """
        # --- MCP 툴 및 에이전트 정의 구성 --------------------------
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

        # --- 에이전트 존재 여부 확인 ------------------------------
        try:
            existing = self._project_client.agents.get(agent_name=self._agent_name)
            logger.info("Agent '%s' already exists (id=%s) — reusing", existing.name, existing.id)
        except Exception:
            # 에이전트가 없는 경우 — 새 에이전트를 생성 (첫 번째 버전)
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

        # --- 에이전트가 이미 존재하는 경우 — 새 버전 추가 ---------------------------
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
        """현재 세션에서 생성된 에이전트 버전을 삭제합니다."""
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
    # 대화 및 구조화된 입력
    # ------------------------------------------------------------------

    def create_conversation(self) -> str:
        """새 대화를 생성하고 해당 id를 반환합니다."""
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
        *json_input*을 프롬프트 문자열로 직렬화하여 Responses API를 통해 에이전트에 전송하고,
        MCP 승인 요청을 자동으로 처리합니다.

        Args:
            conversation_id: 사용자가 제공한 대화 id.
                None인 경우 새 conversation_id를 생성해야 합니다.
            json_input: JSON으로 직렬화되어 프롬프트에 삽입될 임의의 딕셔너리.

        반환값:
            에이전트의 최종 텍스트 출력.

        참고 문서:
          - Responses API:
            https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/
          - MCP 툴 승인 흐름:
            https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/tools/model-context-protocol
        """
        if self._agent_name is None:
            raise RuntimeError("Call create_agent() before sending input.")


        logger.info(
            "Sending structured input to agent | conversation_id=%s agent_name=%s",
            conversation_id,
            self._agent_name,
        )
        logger.debug("Structured input payload: %s", json.dumps(json_input, indent=2))

        # Foundry 에이전트 참조 및 구조화된 입력을 extra_body에 포함하여 Responses API에 전달
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

        # 에이전트가 발생시키는 MCP 툴 승인 요청을 자동 처리
        approval_list: ResponseInputParam = []  # 자동 승인 응답을 누적할 목록
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
    # 컨텍스트 매니저 지원
    # ------------------------------------------------------------------

    def __enter__(self) -> "FoundryAgentClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self._openai_client.__exit__(*_)
        self._project_client.__exit__(*_)
        self._credential.__exit__(*_)
