# `.github/skills/` — Copilot Skills

이 폴더는 **GitHub Copilot Skills** 컨벤션에 따라 토픽별 사용법 문서를 모아둔 공간입니다.  
각 서브폴더는 하나의 스킬(Skill)을 나타내며, 그 안의 `SKILL.md`가 스킬의 진입점입니다.

```
.github/skills/
├── README.md                              ← 본 파일 (스킬 폴더 소개)
├── foundry-agent-definition/
│   └── SKILL.md                           ← Foundry 에이전트를 정의하는 방법
└── foundry-agent-usage/
    └── SKILL.md                           ← Foundry 에이전트를 호출/사용하는 방법
```

## 스킬 형식

각 `SKILL.md`는 다음 형식을 따릅니다.

1. **YAML frontmatter** — 스킬 이름과 한 줄 설명
   ```yaml
   ---
   name: skill-name
   description: 한 줄로 요약된 스킬 설명. 언제 이 스킬을 사용해야 하는지 명확히 기술.
   ---
   ```
2. **본문 (Markdown)** — 스킬을 적용할 때 따라야 할 단계, 코드 패턴, 주의사항, 참조 파일 경로 등.

## 스킬 목록

| 폴더 | 토픽 | 사용 시점 |
|---|---|---|
| `foundry-agent-definition/` | Azure AI Foundry 에이전트를 **정의**(생성·버전 관리)하는 방법 | 새 에이전트를 만들거나 시스템 인스트럭션·툴·`structured_inputs`를 변경할 때 |
| `foundry-agent-usage/` | 정의된 에이전트를 **호출**하고 구조화된 입력을 전달하는 방법 | 에이전트에 메시지를 보내고 응답을 받는 코드를 작성할 때 |
