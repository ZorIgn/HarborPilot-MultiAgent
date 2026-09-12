# Agent Workflow

HarborPilot uses a Supervisor-mediated runtime. “Multi-agent” means that
specialized roles have separate tool allowlists and typed outputs; it does not
mean that several models freely hand work to one another.

## Actual execution topology

```mermaid
sequenceDiagram
  participant U as User
  participant S as SupervisorAgent
  participant A as Specialist Agent
  participant T as Tool Registry
  participant H as Human Gate

  U->>S: Start or resume workflow
  S->>A: Supervisor route / dispatch
  A->>T: Allowed deterministic tool proposal
  T-->>A: Validated result
  A-->>S: Typed result + HANDOFF to Supervisor
  S->>S: Evaluate route signals and formal gates
  S->>A: Next bounded specialist turn
  A->>H: Only for an explicit human-gated operation
  H-->>S: Typed approval or resolution
  S-->>U: Complete, WAITING_USER, WAITING_HUMAN, FAILED_RETRYABLE, or FAILED
```

The execution graph contains only these two transition classes:

```text
SupervisorAgent -> AssessmentAgent | ResearchAgent | MatchingAgent
SupervisorAgent -> VerificationAgent | PlanningAgent | WritingAgent | CriticAgent
SpecialistAgent -> SupervisorAgent
```

Most live states intentionally expose one legal Supervisor route: a missing
profile field, unresolved official source, or formal gate is a dependency, not
a prompt for the model to invent parallel work. The route set becomes plural
only where work is genuinely independent and non-escalating—for example,
bounded source-plan preparation and student story-card preparation while
verification is pending, or fact-bound writing and timeline construction after
verification. This is policy-safe dynamic routing, not unrestricted agent
autonomy.

There are no `CriticAgent -> MatchingAgent`, `CriticAgent -> VerificationAgent`,
`CriticAgent -> WritingAgent`, `MatchingAgent -> ResearchAgent`, or
`VerificationAgent -> VerificationAgent` execution edges. Those outcomes are
signals written by a specialist and consumed on the next Supervisor turn. For
example, `CriticAgent` may report `REVERIFY`; the Supervisor then decides
whether the current policy state permits a new `VerificationAgent` turn. This
keeps the real path explicit as:

```text
Specialist -> Supervisor -> Specialist
```

`can_handoff(source, target)` is an executor-boundary check, not a route-opening
compatibility fallback. A specialist may return only to `SupervisorAgent`; only
`SupervisorAgent` may select a specialist target. Unknown sources and direct
specialist-to-specialist targets are rejected; a legacy/plug-in unknown source
may only use the safe fallback of returning to `SupervisorAgent`.

## Default mode and real data modes

The default runtime is deterministic/mock and offline:

```bash
HARBOR_AGENT_LLM_MODE=mock
```

The HTTP runtime injects a live tool-calling provider only when the server has
an active administrator-owned OpenAI-compatible configuration. Otherwise it
uses the deterministic runtime. The default source acquisition mode is also
`mock`; it does not contact the public web. Setting `dry_run=false` alone is
not permission to make network requests.

The `refresh_official_sources` flag on a runtime workflow is an explicit
source-tool request, not a verification or publication result. It is enabled
only when the caller also names known programme IDs, sets
`source_connection_mode=real|hybrid`, and the API injects a server-validated
operator authorization. In `mock` mode, with no scope, or without that
authorization, it cannot contact the public web. It keeps the same
Verification-only tool boundary and human publication gate; operator-run live
acquisition should use the controlled endpoint and `connection_mode` contract
below.

For an explicitly controlled acquisition run, an operator can use
`DataAcquisitionRequest.connection_mode` as follows:

| Mode | Network behavior | Formal-use behavior |
| --- | --- | --- |
| `mock` (default) | No live request; produces a dry-run plan | No new verified fact is created |
| `real` | Fetches allowlisted official sources after admin/scope checks | Snapshot → extraction → candidate → human review → publish; fetch success alone is never verification |
| `hybrid` | Uses retained snapshots plus an explicit real refresh | Same review and publish gates; failed real refresh cannot silently become a mock fact |

The live path is auditable through source snapshots, page hashes, extraction
candidates, exact source binding, review records, and published field facts.
The current formal coverage is reported by `GET /api/admin/decision-coverage`;
catalog size is not evidence coverage.

The controlled entry point is `POST /api/workflows/data-acquisition`. A live
run must set both `dry_run=false` and `connection_mode=real|hybrid`, pass the
admin/operator check, and name known programme IDs. Supervisor owns routing;
Verification is the only Specialist allowed to enter this path. Research cannot
turn a bounded source plan into a network request by itself.

## Agent responsibilities and boundaries

| Role | Allowed responsibility | Explicit boundary |
| --- | --- | --- |
| `SupervisorAgent` | Split tasks, select one currently legal specialist route, handle pauses and terminal status | Does not execute tools or bypass admissions/formal gates |
| `AssessmentAgent` | Normalize profile and identify missing inputs | Does not invent student facts or eligibility |
| `ResearchAgent` | Recall and narrow the deterministic catalog; build a bounded official-source research plan | Does not perform unrestricted web research, fetch pages, extract fields, bind sources, review candidates, or publish facts |
| `MatchingAgent` | Evaluate admissions, finances, preference, applicant fit, and portfolio composition | Does not turn unverified catalog values into hard qualification or budget facts |
| `VerificationAgent` | Inspect evidence readiness and, when explicitly enabled, drive the controlled source pipeline | It is the only runtime specialist allowed to enter snapshot/extract/bind/review tools; candidates remain non-formal until human publication |
| `PlanningAgent` | Build preparation and evidence-gated official timelines | Does not make an unverified deadline formal |
| `WritingAgent` | Retrieve grounded student/program facts, build story cards, and draft | Grounding validation must pass before `writing_ready` can be true |
| `CriticAgent` | Run recommendation, source, writing, and formal gates | `BLOCKED` remains blocked after a failed reverify; it cannot convert missing sources into a field-level `PASS` or Critic `FORMAL_PASS` |

## Model proposal contract

When model-driven mode is enabled, the model is proposal-only. It does not gain
authority to mutate runtime state or control the execution graph:

- Specialist models see only the exact policy-approved tool calls for the
  current state. They may select a non-empty ordered prefix, but cannot change
  tool names, arguments, or order.
- Specialist models cannot set `next_agent` to a peer, replace a user/human
  question, or write a shared `state_patch`. Their deterministic policy owns
  the return to `SupervisorAgent`.
- The Supervisor model sees only currently available route targets. The
  runtime owns route state patches and rejects invented targets, self-routes,
  tool calls, and unvalidated patches.
- The executor revalidates the final `AgentDecision`, tool allowlist, handoff
  graph, terminal ownership, and state-field ACLs before performing any action.

This separation allows an LLM to help select or explain an action without
granting it tool-argument, routing, or state-mutation authority.

## Source verification path

`ResearchAgent` first calls catalog recall and then
`build_source_research_plan`. The plan is bounded by program, URL, field, and
registry limits; it permits only HTTPS official institution domains and does
not fetch or publish data.

Only the Verification route can enter the runtime source workflow:

```text
discover official source
  -> snapshot official source
  -> extract typed candidates
  -> exact source binding (human approval)
  -> save review candidate (human approval)
  -> reviewer publication
  -> published DecisionFact / ResolvedProgramView
```

The source text is untrusted and extraction output is only a candidate. A
successful fetch, parser result, or persisted review candidate is not a formal
fact. Publication must include the current cycle, source scope, source URL,
snapshot URL, page hash, evidence snippet, reviewer identity, review decision,
and a matched program binding. Missing any required provenance leaves the field
`UNKNOWN` for formal decisions.

The same canonical fact model is consumed by matching, planning, writing and
the final Critic gate; no downstream component may promote catalogue seed
values into formal facts.

## Decision and writing gates

Catalog `Program` records are useful for recall and display. Hard qualification,
hard budget caps, official timelines, and formal recommendations read the
canonical `DecisionFact` projection through `ResolvedProgramView`. At the
field level the result is `PASS`, `FAIL`, or `UNKNOWN`:

- `PASS`/`FAIL` requires a current, reviewed, formally usable fact;
- absent, stale, previous-cycle, conflicted, community-only, or incomplete
  provenance produces `UNKNOWN` and cannot create a hard rejection or formal
  recommendation;
- conflicting current facts remain unresolved until an exact human decision.

`portfolio_required` is a hard admissions fact, not a writing preference. It
is formal only when a reviewed official record gives an explicit boolean. A
missing/ambiguous portfolio statement is `UNKNOWN`, so it cannot create a hard
pass or reject. The same fail-closed rule applies to GPA scale: a source value
such as `3.6/4.0` is preserved as candidate text until a reviewer publishes an
explicit 100-point value; the runtime does not silently convert it.

The Critic has separate readiness states:

```text
FORMAL_PASS          all required formal gates pass
PRELIMINARY_COMPLETE background, exploration recommendation, or preparation
                       plan with explicit blockers and formal_use_ready=false
BLOCKED              one or more gates remain unsupported or conflicted
```

After a source reverify is exhausted, missing grounding can never be written as
`PASS` or `FORMAL_PASS`. `PROGRAM_RECOMMENDATION` and
`APPLICATION_PLANNING` may safely end as `PRELIMINARY_COMPLETE` only with
explicit source blockers; this produces a non-formal exploration/preparation
artifact. Writing and full-application delivery remain `BLOCKED`. For writing
workflows, ClaimGraph validation must explicitly pass before the runtime can
set `writing_ready=true`.

`WAITING_HUMAN` is reserved for a typed, executable tool approval or evidence
conflict resolution. A `BLOCKED` delivery without either action becomes
`FAILED_RETRYABLE`, preserving the Critic blockers without presenting an
unactionable human-review checkpoint. After controlled acquisition and
independent publication add the missing DecisionFacts, the workflow may be
resumed with the same ID.

## LLM mode

Default:

```bash
HARBOR_AGENT_LLM_MODE=mock
```

An operator can configure an OpenAI-compatible provider for a controlled model
run. This changes model proposal generation only; it does not change the
deterministic eligibility, evidence, formal-gate, handoff, or state ACLs. A
live model run should be evaluated separately from deterministic/mock tests.

## Runtime contract and trace

`GET /api/agent-system` exposes the instantiated agent contracts and checks.
`GET /api/agent/workflows/{id}/trace` records Supervisor routes, specialist
turns, tool calls/results, checkpoints, human gates, and terminal status. A
`HANDOFF` from a specialist is always a return to `SupervisorAgent`; the next
specialist is represented by the following `SUPERVISOR_ROUTE` event.

The runtime is bounded by workflow steps, agent turns, tool rounds, total tool
calls, and Supervisor replans. Limits and checkpoints are persisted so a
`WAITING_USER` or `WAITING_HUMAN` workflow can resume without skipping the
same policy gates.

## Optional Langfuse observability

The runtime can mirror sanitized structural observations to Langfuse through
the optional Python SDK (`langfuse==4.15.2`). Langfuse Cloud and a self-hosted
instance use the same client; only credentials and the HTTP(S) base URL differ.
Configure the external Langfuse instance with the official [Langfuse SDK
documentation](https://langfuse.com/docs/observability/sdk/overview) and
[self-hosting documentation](https://langfuse.com/self-hosting).

Install the SDK only when the server or eval CLI will export observations:

```bash
python -m pip install -e '.[observability]'
```

The settings are server-side environment variables. The defaults keep export
off and target Langfuse Cloud:

| Variable | Default | Meaning |
| --- | --- | --- |
| `HARBOR_AGENT_LANGFUSE_ENABLED` | `false` | Enable the optional sink and SDK initialization |
| `LANGFUSE_PUBLIC_KEY` | unset | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | unset | Langfuse secret key |
| `LANGFUSE_BASE_URL` | `https://cloud.langfuse.com` | Langfuse Cloud or self-hosted HTTP(S) endpoint |
| `LANGFUSE_TRACING_ENVIRONMENT` | `development` | Langfuse environment label |
| `LANGFUSE_RELEASE` | unset | Optional release label |
| `LANGFUSE_SAMPLE_RATE` | `1` | Deterministic trace-level sampling rate from `0` to `1` |

For a local self-hosted service use `http://localhost:3000` from a local API
process. When the API runs in Docker Desktop and Langfuse runs on the host,
use `http://host.docker.internal:3000`; a public deployment should use HTTPS.
Create or copy the public and secret keys from the Langfuse project settings in
Langfuse Cloud or in the self-hosted UI.
The Compose file passes these values only to the API container. Set
`HARBOR_AGENT_LANGFUSE_ENABLED=true` in the project `.env`, then run
`docker compose up --build`; Compose passes the flag as
`INSTALL_OBSERVABILITY` for the optional SDK build and as the API runtime
setting. Langfuse keys are runtime environment values and are not copied into
the image or exposed to the web application.

### Lifecycle and identity

FastAPI initializes the optional sink during application startup and calls its
shutdown/flush path during application shutdown. The eval CLI initializes the
same sink before running cases and flushes it in its `finally` path. Each
normal workflow start and resume creates a new `execution_id` and `trace_id`;
the stable `workflow_id` is used as the Langfuse session ID. The exported
hierarchy is:

```text
workflow.run
└── agent
    ├── model.proposal (generation)
    ├── tool
    └── policy.check (guardrail)
```

Each Supervisor or Specialist turn has its own agent span. A model retry has
its own generation, and a tool retry has its own tool span. Entering
`WAITING_USER` or `WAITING_HUMAN` closes the current execution; human waiting
time is excluded from execution latency. A resume starts another execution
in the same session and records the typed human decision when applicable.

The integration covers Runtime API workflow start/resume executions and the
eval CLI. Generation observations carry the configured provider and model when
an actual runtime proposal request is made. Replay providers are labelled
`model_replay`, external providers `live_model`; a deterministic turn has no
generation. Other standalone LLM endpoints are outside this runtime trace.

The local SQLite runtime trace remains the audit record. Langfuse supplies an
asynchronous, best-effort display; approvals, human review, checkpoints, and
routing remain local runtime concerns. Telemetry delivery is best effort and
not durably queued, so a process crash or exporter/remote failure can lose
remote spans while local audit facts remain available.
Missing credentials, unavailable SDK imports, or a failed exporter initialization
disable remote export and emit a diagnostic. SDK export failures are isolated
from workflow state transitions; local persistence errors remain runtime errors.

### Export boundary

Remote export begins when `HARBOR_AGENT_LANGFUSE_ENABLED=true`. Once enabled,
the sink's default payload contains IDs, event types, agent/tool names, status,
timing, model/provider labels, hashes, counts, and other allowlisted metadata.
It exports structure summaries rather than student profiles, full text, raw
prompts, raw tool arguments, or free-form human-review text. Local trace events
may retain the audit fields needed by the runtime; the remote payload is
filtered separately before it is sent.

Runtime diagnostics are JSON records written to stderr and carry the
`workflow_id`, `execution_id`, `trace_id`, and event identifiers where
available. The deployment environment handles log rotation.

### Eval capture and metrics

`--capture-synthetic-content` is a separate opt-in for repository synthetic
fixtures only. When enabled, model and tool content from those fixtures is
sanitized for observations, including the local eval trace. Credential fields,
email addresses and phone numbers are masked and long strings truncated.
Remote export still requires the Langfuse enable switch. `--live-model`
is the independent switch that calls the configured external provider. When
Langfuse is enabled, each sampled execution trace produced by an eval case is
associated with a `case_passed` BOOLEAN score. A resume case may produce
multiple execution traces, and unsampled traces have no score. A passed case is
an eval assertion and does not mean that the workflow reached `COMPLETED`.
`case_pass_rate` counts each case once. `workflow_completion_rate` uses only
`operation=workflow` cases and their final lifecycle status; injected safety
probes are excluded. Langfuse trace scores are not a case-deduplicated aggregate.

Eval aggregates report p50/p95 latency separately for workflow executions,
LLM calls, and tool attempts that entered the handler; human-gate pauses are
excluded from tool latency. Token and cost fields preserve known values
when available and expose completeness flags instead of inferring missing
usage. `known_cost_usd` sums costs calculable from known token usage and the
repository's configured per-model token prices; `calculated_cost_usd` is
populated only when every recorded LLM response has a known cost. A missing
price or token count remains unknown. Langfuse may display
its own price-table estimate, which is a UI estimate rather than a bill.
