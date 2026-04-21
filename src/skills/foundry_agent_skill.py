"""
Azure AI Foundry 에이전트를 재사용 가능한 SKILL로 래핑한 모듈.

이 모듈은 FoundryAgentClient 클래스를 기반으로 Foundry 에이전트를
AI 파이프라인(Semantic Kernel, AutoGen, LangChain 등)에서 호출 가능한
표준 스킬(Skill) 인터페이스로 노출합니다.

SKILL 구성 요소:
  - SkillInput   : 스킬 입력 스키마 (Pydantic 모델)
  - SkillOutput  : 스킬 출력 스키마 (Pydantic 모델)
  - skill_function : 함수 수준 메타데이터를 부착하는 데코레이터
  - FoundryAgentSkill : 스킬 클래스 — 에이전트 생명주기와 대화를 관리하고
                        구조화된 입력을 에이전트에 전달하는 단일 진입점 제공

사용 예시:
    from src.skills import FoundryAgentSkill, SkillInput

    skill = FoundryAgentSkill()
    payload = SkillInput(
        user_prompt="Notify the on-call engineer about INC0042 via email.",
        recipient="oncall@example.com",
        subject="Incident[ID: INC0042] Notification",
        incident_id="INC0042",
    )
    result = skill.run(payload)
    print(result.output)
"""

from __future__ import annotations

import functools
import logging
from typing import Any, Callable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 입출력 스키마 — Pydantic 모델
# ---------------------------------------------------------------------------

class SkillInput(BaseModel):
    """Foundry 에이전트 스킬에 전달할 구조화된 입력 스키마."""

    user_prompt: str = Field(
        ...,
        description="에이전트에 전달할 자연어 사용자 프롬프트.",
        examples=["Notify the on-call engineer about INC0042 via email."],
    )
    recipient: str = Field(
        ...,
        description="이메일 수신자 주소. MCP 서버의 send_email 툴에 전달됩니다.",
        examples=["oncall@example.com"],
    )
    subject: str = Field(
        ...,
        description="이메일 제목. MCP 서버의 send_email 툴에 전달됩니다.",
        examples=["Incident[ID: INC0042] Notification"],
    )
    incident_id: str = Field(
        ...,
        alias="incidentId",
        description="분석 대상 인시던트 ID. 이메일 본문 작성에 사용됩니다.",
        examples=["INC0042"],
    )
    conversation_id: str | None = Field(
        default=None,
        description="다중 턴(multi-turn) 대화를 이어가기 위한 기존 대화 ID. "
                    "None이면 새 대화를 자동 생성합니다.",
    )

    model_config = {"populate_by_name": True}

    def to_agent_payload(self) -> dict[str, Any]:
        """FoundryAgentClient.send_json_input()에 전달할 딕셔너리로 변환합니다."""
        return {
            "user_prompt": self.user_prompt,
            "recipient": self.recipient,
            "subject": self.subject,
            "incidentId": self.incident_id,
        }


class SkillOutput(BaseModel):
    """Foundry 에이전트 스킬이 반환하는 출력 스키마."""

    output: str = Field(..., description="에이전트의 최종 텍스트 응답.")
    conversation_id: str = Field(
        ..., description="현재 대화 ID. 다음 턴의 SkillInput.conversation_id로 전달하세요."
    )
    skill_name: str = Field(default="FoundryAgentSkill", description="스킬 이름.")


# ---------------------------------------------------------------------------
# skill_function 데코레이터 — 함수 수준 메타데이터 부착
# ---------------------------------------------------------------------------

def skill_function(
    name: str | None = None,
    description: str = "",
    input_description: str = "",
    output_description: str = "",
) -> Callable:
    """
    스킬 함수에 메타데이터(이름·설명·입출력 설명)를 부착하는 데코레이터.

    AI 오케스트레이터(Semantic Kernel, AutoGen 등)가 이 메타데이터를
    도구(Tool) 등록 시 활용할 수 있습니다.

    Args:
        name: 스킬 내 함수 고유 이름. 기본값은 함수 이름.
        description: 함수가 수행하는 작업 설명.
        input_description: 입력 파라미터 설명.
        output_description: 반환값 설명.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        wrapper.__skill_metadata__ = {  # type: ignore[attr-defined]
            "name": name or func.__name__,
            "description": description,
            "input_description": input_description,
            "output_description": output_description,
        }
        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# FoundryAgentSkill 클래스
# ---------------------------------------------------------------------------

class FoundryAgentSkill:
    """
    Azure AI Foundry 에이전트를 재사용 가능한 SKILL로 노출하는 클래스.

    이 스킬은 내부적으로 FoundryAgentClient를 활용하여:
      1. 에이전트 생명주기(생성/재사용)를 관리합니다.
      2. 대화(conversation) 생성을 처리합니다.
      3. 구조화된 입력(SkillInput)을 에이전트에 전달하고 출력(SkillOutput)을 반환합니다.

    이 클래스는 컨텍스트 매니저로도 사용할 수 있어 리소스 자동 정리가 가능합니다.

    Examples:
        단일 호출::

            skill = FoundryAgentSkill()
            result = skill.run(SkillInput(
                user_prompt="...", recipient="...", subject="...", incident_id="..."
            ))
            print(result.output)

        컨텍스트 매니저::

            with FoundryAgentSkill() as skill:
                result = skill.run(payload)

        다중 턴 대화::

            skill = FoundryAgentSkill()
            r1 = skill.run(payload1)
            r2 = skill.run(payload2.model_copy(update={"conversation_id": r1.conversation_id}))
    """

    SKILL_NAME = "FoundryAgentSkill"
    SKILL_VERSION = "1.0.0"
    SKILL_DESCRIPTION = (
        "Azure AI Foundry 에이전트를 통해 구조화된 입력(수신자·제목·인시던트 ID)을 "
        "받아 MCP 서버를 호출하여 인시던트 알림 이메일을 전송하는 스킬."
    )

    def __init__(self) -> None:
        # FoundryAgentClient는 지연 초기화(lazy init)하여 환경 변수 설정 시점을 유연하게 합니다.
        self._client: Any | None = None
        self._agent_initialized: bool = False
        logger.debug("FoundryAgentSkill instance created (client not yet initialised)")

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _ensure_client(self) -> Any:
        """FoundryAgentClient가 초기화되지 않은 경우 지연 생성합니다."""
        if self._client is None:
            from src.agent.client import FoundryAgentClient  # noqa: PLC0415
            logger.info("Initialising FoundryAgentClient inside FoundryAgentSkill")
            self._client = FoundryAgentClient()
        return self._client

    def _ensure_agent(self) -> None:
        """에이전트 버전이 생성되지 않은 경우 생성합니다."""
        if not self._agent_initialized:
            client = self._ensure_client()
            meta = client.create_agent()
            self._agent_initialized = True
            logger.info("Agent ready | %s", meta)

    # ------------------------------------------------------------------
    # 공개 스킬 함수
    # ------------------------------------------------------------------

    @skill_function(
        name="run",
        description=(
            "구조화된 입력(SkillInput)을 Foundry 에이전트에 전달하고 "
            "에이전트의 텍스트 응답(SkillOutput)을 반환합니다."
        ),
        input_description="SkillInput — user_prompt, recipient, subject, incident_id 포함.",
        output_description="SkillOutput — 에이전트 응답 텍스트와 conversation_id 포함.",
    )
    def run(self, skill_input: SkillInput) -> SkillOutput:
        """
        Foundry 에이전트 스킬의 단일 진입점.

        내부적으로 다음 순서로 동작합니다:
          1. FoundryAgentClient 지연 초기화.
          2. 에이전트 버전 존재 여부 확인 및 생성.
          3. conversation_id가 없으면 새 대화 생성.
          4. 구조화된 입력을 에이전트에 전송하고 응답 수신.

        Args:
            skill_input: 에이전트에 전달할 구조화된 입력.

        Returns:
            에이전트의 텍스트 응답과 대화 ID를 담은 SkillOutput.

        Raises:
            EnvironmentError: 필수 환경 변수가 설정되지 않은 경우.
            RuntimeError: 에이전트 생성 또는 메시지 전송에 실패한 경우.
        """
        self._ensure_agent()
        client = self._ensure_client()

        # conversation_id 결정 — 제공된 경우 재사용, 아니면 새로 생성
        conversation_id = skill_input.conversation_id
        if conversation_id is None:
            conversation_id = client.create_conversation()
            logger.info("New conversation created | id=%s", conversation_id)

        logger.info(
            "Running FoundryAgentSkill | conversation_id=%s incident_id=%s",
            conversation_id,
            skill_input.incident_id,
        )

        output_text = client.send_json_input(
            conversation_id=conversation_id,
            json_input=skill_input.to_agent_payload(),
        )

        return SkillOutput(
            output=output_text,
            conversation_id=conversation_id,
            skill_name=self.SKILL_NAME,
        )

    @skill_function(
        name="get_skill_metadata",
        description="이 스킬의 이름·버전·설명·입력 스키마를 딕셔너리로 반환합니다.",
        output_description="스킬 메타데이터 딕셔너리.",
    )
    def get_skill_metadata(self) -> dict[str, Any]:
        """
        이 스킬의 메타데이터를 반환합니다.

        AI 오케스트레이터가 스킬을 자동으로 등록하거나 설명할 때 활용할 수 있습니다.

        Returns:
            name, version, description, input_schema, output_schema를 포함하는 딕셔너리.
        """
        return {
            "name": self.SKILL_NAME,
            "version": self.SKILL_VERSION,
            "description": self.SKILL_DESCRIPTION,
            "input_schema": SkillInput.model_json_schema(),
            "output_schema": SkillOutput.model_json_schema(),
        }

    # ------------------------------------------------------------------
    # 컨텍스트 매니저 지원
    # ------------------------------------------------------------------

    def __enter__(self) -> "FoundryAgentSkill":
        return self

    def __exit__(self, *args: Any) -> None:
        if self._client is not None:
            try:
                self._client.__exit__(*args)
                logger.debug("FoundryAgentClient resources released")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error releasing FoundryAgentClient: %s", exc)
        self._client = None
        self._agent_initialized = False


# ---------------------------------------------------------------------------
# 스킬 독립 실행 데모 진입점
# ---------------------------------------------------------------------------

def _demo_main() -> None:  # pragma: no cover
    """
    ``uv run skills-demo`` 로 실행하는 간단한 스킬 사용 데모.

    MCP 서버와 .env 파일이 준비된 환경에서 FoundryAgentSkill을 직접 테스트합니다.
    """
    import json
    import logging as _logging
    from dotenv import load_dotenv

    load_dotenv(override=True)
    _logging.basicConfig(level="INFO", format="%(asctime)s [%(levelname)-8s] %(message)s")

    payload = SkillInput(
        user_prompt="Notify the on-call engineer about incident INC0042 via email.",
        recipient="oncall@example.com",
        subject="Incident[ID: INC0042] Notification",
        incident_id="INC0042",
    )

    print("\n" + "=" * 60)
    print("FoundryAgentSkill — 독립 실행 데모")
    print("=" * 60)

    with FoundryAgentSkill() as skill:
        print("\n[Skill Metadata]")
        print(json.dumps(skill.get_skill_metadata(), indent=2, ensure_ascii=False, default=str))

        print(f"\n[Input]\n{payload.model_dump_json(indent=2, by_alias=True)}")

        result = skill.run(payload)

        print(f"\n[Output]\n{result.model_dump_json(indent=2)}")

