# Agent Workflow

The project follows the outline's core principle: multi-agent does not mean several chatbots talking freely. It means specialized units with constrained inputs, tools, and schemas.

## Workflow

```mermaid
sequenceDiagram
  participant U as User
  participant W as Web UI
  participant O as Orchestrator
  participant P as Profile Agent
  participant E as Evidence Agent
  participant R as Rule Engine
  participant M as Matching Agent
  participant V as Review Agent

  U->>W: Submit assessment form
  W->>O: POST /api/workflows/assessment
  O->>P: Normalize profile
  P-->>O: Profile snapshot
  O->>E: Check evidence readiness
  E-->>O: Uploads and human gate
  O->>R: Evaluate general rules
  R-->>O: Scores and checks
  O->>M: Rank eligible programs
  M->>R: Program hard-rule checks
  M-->>O: Reach/match/safer/not recommended
  O->>V: Review plan and writing draft
  V-->>O: Human gates
  O-->>W: Result + trace
```

## LLM Mode

Default:

```bash
HARBOR_AGENT_LLM_MODE=mock
```

Real smoke test with environment variables:

```bash
set OPENAI_API_KEY=sk-...
set HARBOR_AGENT_LLM_PROVIDER=openai
python scripts/run_real_agent_smoke.py
```

The web UI can also configure DeepSeek, OpenAI, or another OpenAI-compatible endpoint after startup. The LLM is only used for explanation and drafting. GPA, language requirements, prerequisites, and unpublished-field gates are deterministic.
