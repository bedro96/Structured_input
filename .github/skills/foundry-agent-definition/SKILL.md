---
name: foundry-agent-definition
description: Azure AI Foundry 에이전트를 PromptAgentDefinition으로 정의하고, MCP 툴과 structured_inputs를 선언하여 새로운 에이전트(또는 새 버전)를 프로젝트에 등록하는 방법을 설명합니다. 새 에이전트를 만들거나, 시스템 인스트럭션·MCP 연결·구조화된 입력 스키마를 추가/변경해야 할 때 이 스킬을 사용하세요.
---

# Skill: Azure AI Foundry 에이전트 정의 (Definition)

이 스킬은 본 리포지토리에서 **Microsoft Azure AI Foundry 에이전트를 클래스 기반으로 정의하는 방식**을 설명합니다. 참조 구현은 `src/agent/client.py`의 `FoundryAgentClient.create_agent()` 입니다.

## 언제 이 스킬을 사용하나요?

- 새로운 Foundry 에이전트를 코드로 등록해야 할 때
- 기존 에이전트의 시스템 인스트럭션, MCP 툴, `structured_inputs` 스키마를 바꿔 **새 버전**을 발행해야 할 때
- 다른 도메인(예: 다른 MCP 서버, 다른 입력 스키마)을 위한 비슷한 에이전트 클래스를 새로 작성해야 할 때

`foundry-agent-usage` 스킬과 짝을 이룹니다(정의된 에이전트를 호출하는 방법).

## 핵심 개념

| 개념 | 설명 |
|---|---|
| `AIProjectClient` | Azure AI Foundry 프로젝트에 연결되는 최상위 SDK 클라이언트. `azure.ai.projects`에서 임포트. |
| `PromptAgentDefinition` | 에이전트의 모델·시스템 인스트럭션·툴·구조화된 입력을 한 번에 정의하는 데이터클래스. |
| `MCPTool` | 외부 MCP(Model Context Protocol) 서버를 에이전트의 툴로 등록. `server_label`/`server_url`/`require_approval` 필요. |
| `StructuredInputDefinition` | 시스템 인스트럭션의 `{{변수}}` 자리에 런타임에 채워질 변수의 타입과 필수 여부를 선언. |
| 에이전트 버전 | 동일 `agent_name` 아래 `create_version()`을 호출할 때마다 새 **불변(immutable) 버전**이 만들어집니다. |
| 인증 | 본 리포지토리는 `AzureCliCredential`을 사용합니다. 사용자는 사전에 `az login`이 필요합니다. |

## 클래스 기반 정의 패턴

본 리포지토리에서는 에이전트 정의 로직을 클래스 메서드 안에 캡슐화합니다(`FoundryAgentClient.create_agent`). 이 패턴을 따르세요.

1. **환경 변수 로드** — `_require_env()` 헬퍼처럼 누락 시 명시적 오류를 발생시킵니다. 필수 항목:
   - `AZURE_AI_PROJECT_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT_NAME`, `AZURE_AI_AGENT_NAME`
   - `MCP_SERVER_LABEL`, `MCP_SERVER_URL`, `MCP_REQUIRE_APPROVAL`, `MCP_SERVER_CONNECTION_NAME`
2. **클라이언트 초기화** — 생성자(`__init__`)에서 `AIProjectClient(endpoint, credential)`를 한 번만 만들고 인스턴스에 보관합니다. OpenAI 호환 클라이언트는 `project_client.get_openai_client()`로 얻습니다.
3. **MCP 툴 구성** — `MCPTool(server_label=..., server_url=..., require_approval=...)`을 만듭니다. `require_approval="never"`이면 툴 호출이 자동 승인됩니다.
4. **PromptAgentDefinition 작성** — `model`, `instructions`(템플릿 변수 `{{...}}` 포함), `structured_inputs`(dict[str, StructuredInputDefinition]), `tools=[mcp_tool]`을 채웁니다.
5. **존재 여부 확인 후 버전 발행** — `agents.get(agent_name=...)`을 try/except로 감싸서:
   - 존재하지 않으면 → `agents.create_version(agent_name, definition)`로 첫 버전을 만듭니다.
   - 존재하면 → 동일 호출로 **새 버전**을 추가합니다.
6. **결과 보관** — 반환된 `agent.name`/`agent.version`/`agent.id`를 인스턴스 속성에 저장하고, 호출자에게 dict로 돌려줍니다.

## 시스템 인스트럭션 작성 규칙

- 변수 자리는 반드시 **이중 중괄호** `{{변수명}}`으로 표기합니다. 예: `{{recipient}}`.
- 변수명은 `structured_inputs` 딕셔너리의 키와 **정확히 일치**해야 합니다.
- 우선순위가 다른 입력 채널(사용자 프롬프트 vs structured input)이 있다면 인스트럭션에서 명시적으로 우선순위를 진술하세요. 본 리포지토리 예시는 다음 문장을 사용합니다.
  > "It is imperative to use following variables for calling MCP tools. These variables have highest priority over any other means…"

## `structured_inputs` 선언 규칙

각 변수는 `StructuredInputDefinition`으로 선언합니다:

- `description`: 사람이 읽는 한국어/영어 설명.
- `required`: 보통 `True`. 누락 시 런타임 오류 발생.
- `schema`: JSON Schema 조각. 단순 문자열은 `{"type": "string"}`. 더 복잡한 객체도 가능합니다.

키 이름은 인스트럭션의 `{{...}}` 자리표시자와 **반드시 일치**시키세요.

## 버전 관리 시 주의사항

- `create_version()`은 호출할 때마다 새 버전을 만듭니다. 본 리포지토리의 `create_agent()`는 **항상 새 버전을 추가**한 뒤 그 버전을 활성화합니다. 이는 의도된 동작입니다.
- 같은 정의로 매번 호출하면 빈 버전이 누적될 수 있습니다. 정의가 실제로 변경되지 않았다면 버전 발행을 건너뛰는 보호 로직을 두는 것을 고려하세요(현재 코드에는 없음).
- `delete_agent()`는 **현재 세션이 만든 버전만** 삭제합니다(에이전트 자체는 남음).

## 리소스 정리

`AIProjectClient`, OpenAI 클라이언트, `AzureCliCredential`은 모두 컨텍스트 매니저입니다. 본 리포지토리는 `__enter__`/`__exit__`을 구현해 셋 모두를 안전하게 닫습니다. 클래스를 새로 만들 때도 같은 패턴을 사용하세요.

## 참조 파일

- 기준 구현: [`src/agent/client.py`](../../../src/agent/client.py) — `FoundryAgentClient.__init__`, `create_agent`, `delete_agent`
- 환경 변수 템플릿: [`.env.example`](../../../.env.example)
- README의 "핵심 강조 3 — 에이전트 정의의 `structured_inputs` 선언" 섹션
- Microsoft 공식 문서:
  - 에이전트 빠른 시작: <https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/quickstart>
  - MCP 툴 통합: <https://learn.microsoft.com/ko-kr/azure/ai-foundry/agents/tools/model-context-protocol>

## 새 에이전트 클래스를 만들 때 체크리스트

- [ ] 필수 환경 변수에 대한 `_require_env()` 호출이 모두 있는가?
- [ ] `AIProjectClient` / `openai_client` / `credential`이 인스턴스에 저장되어 있는가?
- [ ] `MCPTool`의 `require_approval` 정책이 의도와 일치하는가? (`never` = 자동 승인)
- [ ] 인스트럭션의 모든 `{{변수}}`가 `structured_inputs` 키와 1:1로 매칭되는가?
- [ ] 각 `StructuredInputDefinition`의 `schema`가 올바른 JSON Schema인가?
- [ ] `agents.get()` 분기와 `agents.create_version()` 분기가 모두 처리되는가?
- [ ] `__enter__`/`__exit__`로 자원 정리가 되는가?
