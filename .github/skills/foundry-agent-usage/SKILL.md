---
name: foundry-agent-usage
description: 이미 정의된 Azure AI Foundry 에이전트에 OpenAI 호환 Responses/Conversations API와 extra_body의 structured_inputs를 통해 구조화된 입력을 전달하고, MCP 승인 흐름을 처리하여 응답 텍스트를 얻는 방법을 설명합니다. 에이전트에 메시지를 보내고 응답을 받는 코드를 작성하거나, 다중 턴 대화를 구현할 때 이 스킬을 사용하세요.
---

# Skill: Azure AI Foundry 에이전트 호출 및 구조화된 입력 전달 (Usage)

이 스킬은 본 리포지토리에서 **클래스화된 Foundry 에이전트를 실제로 호출하는 방식**을 설명합니다. 참조 구현은 `src/agent/client.py`의 `create_conversation()` 및 `send_json_input()` 메서드, 그리고 `src/api/app.py`의 `/api/messages` 엔드포인트입니다.

## 언제 이 스킬을 사용하나요?

- 정의된 Foundry 에이전트에 사용자 입력을 전달하고 응답을 받아야 할 때
- 새로운 API 엔드포인트, CLI 명령, 백엔드 작업 등에서 에이전트를 호출하는 코드를 추가할 때
- 다중 턴(multi-turn) 대화를 구현해야 할 때
- MCP 툴 승인 요청(`mcp_approval_request`)을 처리해야 할 때

`foundry-agent-definition` 스킬과 짝을 이룹니다(에이전트를 만드는 방법).

## 호출 흐름 한눈에 보기

```
client.create_conversation()        # ① 새 대화 ID 생성 (또는 기존 conversation_id 재사용)
        │
        ▼
client.send_json_input(              # ② structured input을 에이전트로 전송
    conversation_id=...,             #    Responses API + extra_body.structured_inputs
    json_input={ user_prompt, recipient, subject, incidentId },
)
        │
        ▼
[approval loop]                      # ③ mcp_approval_request가 있으면 자동 승인 후 재호출
        │
        ▼
return response.output_text          # ④ 최종 텍스트 응답
```

## 구조화된 입력 전송 패턴

본 리포지토리는 OpenAI 호환 Responses API의 `extra_body`를 활용해 Foundry 고유 필드인 `agent_reference`와 `structured_inputs`를 전달합니다. 다음 형태를 따르세요.

```python
create_kwargs = {
    "conversation": conversation_id,            # 대화 스레드 ID
    "input": json_input.get("user_prompt", ""), # 사용자 자연어 프롬프트
    "extra_body": {
        "agent_reference": {                     # 호출할 Foundry 에이전트 식별
            "name": self._agent_name,
            "type": "agent_reference",
        },
        "structured_inputs": {                   # PromptAgentDefinition.structured_inputs와 동일 키
            "recipient": json_input.get("recipient"),
            "subject":   json_input.get("subject"),
            "incidentId": json_input.get("incidentId"),
        },
    },
}
response = self._openai_client.responses.create(**create_kwargs)
```

핵심 규칙:

- `extra_body.structured_inputs`의 **키 집합은 에이전트 정의의 `structured_inputs` 키 집합과 정확히 일치**해야 하며, 인스트럭션의 `{{변수}}`도 같은 키를 참조해야 합니다.
- `input`(사용자 프롬프트)과 `structured_inputs`(템플릿 변수)는 **다른 채널**입니다. 같은 정보를 두 곳에 중복 전달하지 마세요.
- `agent_reference.type`은 항상 문자열 리터럴 `"agent_reference"` 입니다.

## MCP 승인 흐름 처리

`require_approval`이 `"never"`가 아닌 경우(또는 일부 도구가 승인을 요구할 때) 첫 번째 응답의 `response.output`에 `mcp_approval_request` 항목이 들어옵니다. 본 리포지토리의 표준 처리 패턴은 다음과 같습니다.

1. `response.output`을 순회하며 `item.type == "mcp_approval_request"` 인 항목을 모읍니다.
2. 각 항목에 대해 `McpApprovalResponse(type="mcp_approval_response", approve=True, approval_request_id=item.id)`를 생성해 리스트에 추가합니다.
3. `approval_list`가 비어있지 않으면 `responses.create(input=approval_list, previous_response_id=response.id, extra_body={"agent_reference": {...}})`로 **재호출**하여 최종 응답을 받습니다.
4. 최종 `response.output_text`를 반환합니다.

승인 정책을 바꾸고 싶다면 모든 요청을 승인하는 대신 화이트리스트(`server_label` 또는 도구명 기반)를 적용하는 것을 고려하세요.

## 대화(Conversation) 관리

- **새 대화**: `self._openai_client.conversations.create()` → `conversation.id` 사용.
- **다중 턴**: 같은 `conversation_id`를 후속 `send_json_input()` 호출에 다시 전달하면 같은 스레드에서 컨텍스트가 유지됩니다. 본 리포지토리의 API 서버(`src/api/app.py`)는 클라이언트가 `conversation_id`를 보내지 않으면 새 대화를 만들고, 보내면 이어서 사용합니다.
- 대화 ID는 외부(사용자 세션, DB 등)에 보관해야 다중 턴이 가능합니다. 본 리포지토리의 메모리 상태(`AppState`)는 데모 용도이며 프로덕션에서는 영속 저장소로 교체하세요.

## 호출 전 사전 조건

`send_json_input()`은 `self._agent_name is None`이면 즉시 실패합니다. 따라서 호출 순서는 항상:

1. `FoundryAgentClient()` 인스턴스 생성
2. `create_agent()` 호출(존재 확인 + 새 버전 발행)
3. `create_conversation()` 또는 기존 `conversation_id` 확보
4. `send_json_input(conversation_id, json_input)` 호출

API 서버는 첫 요청 시 ①②③를 지연 초기화(lazy init)로 한 번만 수행합니다(`_get_client()` 참고).

## 입력 페이로드 형태 (현재 데모 기준)

```json
{
  "user_prompt": "Notify the on-call engineer about incident INC7788 via email.",
  "recipient": "kunhoko@kakao.com",
  "subject": "Incident[ID: INC7788] Notification",
  "incidentId": "INC7788"
}
```

- `user_prompt` 만 LLM 입력으로 들어갑니다.
- 나머지 키는 `structured_inputs`로 분리되어 시스템 인스트럭션의 `{{변수}}`를 채웁니다.
- 키 이름은 에이전트 정의와 1:1 매칭이어야 합니다(`foundry-agent-definition` 참고).

## 새로운 입력 변수를 추가할 때

1. `foundry-agent-definition` 스킬을 따라 `PromptAgentDefinition.structured_inputs`에 새 `StructuredInputDefinition`을 추가하고, 인스트럭션에 `{{새변수}}`를 사용합니다.
2. `send_json_input()`의 `extra_body.structured_inputs` 딕셔너리에 동일 키를 추가합니다.
3. 호출자(API 모델, 콘솔 앱, 테스트)도 새 키를 받도록 업데이트합니다.
4. **반드시 새 에이전트 버전을 발행**해야 변경된 `structured_inputs` 스키마가 적용됩니다.

## 디버깅 팁

- `LOG_LEVEL=DEBUG`로 실행하면 직렬화된 페이로드 전체와 응답 ID가 로그에 남습니다.
- LLM이 `{{변수}}`를 그대로 출력한다면 → 키 이름 불일치 또는 에이전트 버전이 갱신되지 않은 경우입니다.
- MCP 도구가 호출되지 않는다면 → `require_approval` 설정이 `"never"`가 아닐 때 승인 루프를 빠뜨렸을 가능성이 큽니다.
- 401/403 오류 → `az login --use-device-code` 미실행, 또는 잘못된 테넌트 컨텍스트.

## 참조 파일

- 기준 구현: [`src/agent/client.py`](../../../src/agent/client.py) — `create_conversation`, `send_json_input`
- API 통합 예시: [`src/api/app.py`](../../../src/api/app.py) — `process_message` (`/api/messages`)
- 클라이언트 데모: [`src/console_app.py`](../../../src/console_app.py)
- README의 "핵심 강조 1 — 클라이언트의 구조화된 입력 전달", "핵심 강조 2 — 시스템 인스트럭션의 템플릿 변수" 섹션
- Microsoft 공식 문서:
  - Foundry 에이전트 개요: <https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/overview>
  - 스레드(대화) 관리: <https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/how-to/threads>
  - MCP 툴 승인 흐름: <https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/tools/model-context-protocol>

## 호출 코드를 작성할 때 체크리스트

- [ ] `create_agent()`가 호출 전에 한 번 실행되었는가?
- [ ] `extra_body.structured_inputs`의 키가 에이전트 정의와 100% 일치하는가?
- [ ] `agent_reference.name`이 현재 활성 에이전트 이름인가?
- [ ] `mcp_approval_request` 항목을 검사하고 필요한 경우 승인 후 재호출하는가?
- [ ] 다중 턴이 필요한 경로에서 `conversation_id`가 유지·재사용되는가?
- [ ] 예외/타임아웃 시 에이전트 응답 텍스트 대신 사용자에게 의미 있는 오류가 반환되는가?
