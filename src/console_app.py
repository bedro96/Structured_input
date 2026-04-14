"""
구조화된 입력 → MCP → 에이전트 전체 흐름을 시연하는 콘솔 애플리케이션.

이 스크립트는 종단 간(end-to-end) 사용 예시를 보여줍니다:
  1. 로컬 MCP 서버를 백엔드로 사용하는 Azure AI Foundry 에이전트를 생성합니다.
  2. 대화(스레드)를 생성합니다.
  3. 두 가지 예시 구조화 입력 페이로드를 전송하고 에이전트 응답을 출력합니다.
  4. 에이전트 버전을 삭제하여 리소스를 정리합니다.

사전 요구 사항:
  - MCP HTTP Streamable 서버가 실행 중이어야 합니다:
      uv run mcp-server
  - Azure 자격 증명이 포함된 유효한 .env 파일이 필요합니다 (.env.example 참고).

실행 방법:
    uv run console-app
  또는
    uv run python -m src.console_app
"""

from __future__ import annotations

import sys
import httpx
from dotenv import load_dotenv

load_dotenv(override=True)


def main() -> int:
    """콘솔 데모를 실행하고 종료 코드를 반환합니다."""
    print("\n" + "=" * 60)
    print("\nJSON input → AI Foundry Agent → MCP Demo")
    print("\nThis demo sends structured JSON input to an Azure AI Foundry agent that uses variables for MCP server input when making call." )
    print("=" * 60)
    print("\nStarting demo...")

    # ----------------------------------------------------------
    # 인시던트 알림 이메일 전송을 위한 구조화된 입력 페이로드 정의
    system_alert_message = {
        "json_input": {
            "user_prompt": "Notify the on-call engineer about incident INC7788 via email.",
            "recipient": "kunhoko@kakao.com",
            "subject": "Incident[ID: INC7788] Notification",
            "incidentId": "INC7788"
        },
    }
    print(f"\nSystem_alert_message is system_alert_message={system_alert_message}")

    # 로컬 API 서버에 구조화된 메시지를 POST 요청으로 전송 (타임아웃: 60초)
    response = httpx.post("http://localhost:8080/api/messages", json=system_alert_message, timeout=60.0)
    print(f"\nResponse status: {response.status_code}")
    if response.is_success:  # HTTP 2xx 응답인 경우에만 본문 출력
        print(f"\nResponse from API: {response.json()}")

if __name__ == "__main__":
    sys.exit(main())
