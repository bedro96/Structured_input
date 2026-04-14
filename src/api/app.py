"""
Structured-Input → MCP → Agent 데모를 위한 FastAPI REST API 서버.

프론트엔드 애플리케이션에서 호출할 수 있으며, 다음 엔드포인트를 제공합니다:
  - 서비스 상태 확인 (GET /health)
  - 에이전트 생성 (POST /api/agents)
  - 에이전트 버전 삭제 (DELETE /api/agents/{agent_name}/{agent_version})
  - 대화 생성 (POST /api/conversations)
  - 에이전트에 구조화된 입력 전송 (POST /api/conversations/{id}/messages)

사전 요구 사항:
  - MCP HTTP Streamable 서버가 실행 중이어야 합니다:
      uv run mcp-server
  - Azure 자격 증명이 포함된 유효한 .env 파일 (.env.example 참고).

실행:
    uv run api-server
  또는
    uv run python -m src.api.app

참고 문서:
  - Azure AI Foundry 에이전트: https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/
  - MCP(모델 컨텍스트 프로토콜): https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/how-to/tools/model-context-protocol
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

load_dotenv(override=True)  # .env 파일의 값으로 기존 환경 변수를 덮어씁니다

# ---------------------------------------------------------------------------
# 상세 로깅 — 개발 단계와 무관하게 항상 활성화
# ---------------------------------------------------------------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()  # 환경 변수 미설정 시 DEBUG로 기본 설정
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    force=True,  # 기존 루트 로거 핸들러를 강제로 재설정
)
logger = logging.getLogger(__name__)

API_HOST = os.environ.get("API_HOST", "0.0.0.0")  # 기본적으로 모든 네트워크 인터페이스에서 수신
API_PORT = int(os.environ.get("API_PORT", "8080"))  # 기본 포트 8080


# ---------------------------------------------------------------------------
# 공유 애플리케이션 상태 (단순 인메모리 — 프로덕션에서는 외부 저장소로 교체 권장)
# ---------------------------------------------------------------------------

class AppState:
    agent_client: Any = None           # FoundryAgentClient 인스턴스 (지연 초기화)
    active_agent: dict[str, str] | None = None    # 현재 활성 에이전트 정보 {name, version, id}


state = AppState()


# ---------------------------------------------------------------------------
# 수명 주기 (Lifespan)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    logger.info("API server starting up | host=%s port=%d", API_HOST, API_PORT)
    logger.info("Log level: %s", LOG_LEVEL)
    yield
    logger.info("API server shutting down")
    if state.agent_client is not None:
        try:
            state.agent_client.__exit__(None, None, None)  # 컨텍스트 매니저 프로토콜로 클라이언트 리소스 정리
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error during agent client cleanup: %s", exc)


# ---------------------------------------------------------------------------
# 앱 (App)
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
    allow_origins=["*"],   # 프로덕션에서는 허용할 출처를 명시적으로 제한해야 합니다
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 요청 / 응답 모델
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
        description="에이전트가 응답해야 할 사용자 입력입니다. 변수: recipient(이메일 수신자), subject(이메일 제목), incidentId(이메일로 알림을 보낼 인시던트 ID)",
    )
    conversation_id: str | None = Field(
        default=None,
        description="다중 턴 대화를 위한 이전 대화 ID",
    )


class MessageResponse(BaseModel):
    output: str
    conversation_id: str


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------

def _get_client():
    """공유 FoundryAgentClient 인스턴스를 반환하며, 없으면 지연 생성(lazy initialization)합니다."""
    if state.agent_client is None:
        from src.agent.client import FoundryAgentClient  # noqa: PLC0415  # 순환 임포트 방지를 위해 함수 내에서 지연 임포트
        logger.info("Initialising FoundryAgentClient")
        state.agent_client = FoundryAgentClient()
    return state.agent_client


# ---------------------------------------------------------------------------
# 라우트 (Routes)
# ---------------------------------------------------------------------------

@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """서비스 헬스 상태를 반환합니다."""
    logger.debug("Health check requested")
    return {"status": "ok", "service": "structured-input-api"}

@app.post(
    "/api/messages",
    response_model=MessageResponse,
    tags=["conversations"],
)
def process_message(body: MessageRequest) -> MessageResponse:
    """
    구조화된 JSON 페이로드를 수신하여 에이전트로 전송합니다.

    conversation_id가 제공된 경우, 해당 대화의 일부로 메시지를 전송하여 다중 턴(multi-turn) 상호작용을 지원합니다.
    페이로드에는 사용자 프롬프트와 MCP 도구 실행에 필요한 변수가 포함되어야 합니다.
    API는 구조화된 입력을 Azure AI Foundry 에이전트로 전달하며, 에이전트는 MCP 도구를 호출할 수 있습니다.
    에이전트의 텍스트 응답은 API 응답에 포함되어 반환되며, 이후 상호작용을 위한 conversation_id도 함께 반환됩니다.

    참고 문서:
      - Azure AI Foundry 에이전트 스레드 및 메시지: https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/how-to/threads
    """
    conversation_id = body.conversation_id  # 요청에서 conversation_id 추출
    logger.debug(
        "POST /api/messages received payload: json_input=%s | conversation_id=%s",
        body.json_input,
        conversation_id,
    )

    # 활성 에이전트 클라이언트가 없으면 새로 초기화하고 에이전트 버전을 생성합니다.
    if state.agent_client is None or state.active_agent is None:
        logger.info("No active agent client found. Initialising new client and agent version.")
        client = _get_client()  # 클라이언트 지연 초기화
        meta = client.create_agent()  # 새 에이전트 버전 생성 및 메타데이터 획득
        state.active_agent = meta  # 애플리케이션 상태에 에이전트 정보 저장
        logger.info("Agent ready | %s", meta)

    if conversation_id is None:
        logger.info("No conversation_id provided. Starting a new conversation.")
        new_conversation_id = state.agent_client.create_conversation()  # 새 대화 스레드 생성
        logger.info("New conversation started | id=%s", new_conversation_id)
        conversation_id = new_conversation_id  # 이후 메시지 전송에 사용할 대화 ID 설정
    try:
        output = state.agent_client.send_json_input(  # 에이전트에 구조화된 입력 전송 및 응답 수신
            conversation_id=conversation_id,
            json_input=body.json_input,
        )
        return MessageResponse(output=output, conversation_id=conversation_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to send message: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# 진입점 (Entry point)
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Launching API server | host=%s port=%d", API_HOST, API_PORT)
    uvicorn.run(
        "src.api.app:app",  # 모듈 경로로 앱 지정 (핫 리로드 지원을 위한 문자열 형태)
        host=API_HOST,
        port=API_PORT,
        reload=False,  # 프로덕션에서는 핫 리로드 비활성화
        log_level=LOG_LEVEL.lower(),  # uvicorn은 소문자 로그 레벨을 요구
    )


if __name__ == "__main__":
    main()
