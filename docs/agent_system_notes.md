# HarborPilot Agent System Notes

## Why this design

HarborPilot should not expose a decorative agent chain to students. The useful product shape is an operations-managed workflow: each agent step has status, owner, retry policy, handoff policy, source evidence, and a deterministic gate before student-facing output is trusted.

Public admissions-assistant and admissions-RAG examples point to the same pattern: parse or retrieve source material first, then let LLMs summarize or draft within source boundaries. EZCollegeApp is a practical example of keeping credentials in environment configuration and turning application data into structured workflow inputs rather than asking end users to manage raw model calls. Admissions RAG research such as MARAUS also emphasizes multi-agent retrieval grounding to reduce hallucination in university admissions QA.

## Current implementation

- `agent_runtime.sqlite` stores `agent_runs`, `agent_steps`, and `agent_jobs`.
- Admin APIs can list runs, inspect steps, enqueue jobs, retry a step, hand off a step, and resolve a human handoff.
- `TraceRecorder` persists every workflow span, then marks the run complete when the workflow ends.
- `ProgramDataAcquisitionAgent` can run a live snapshot pipeline. It saves official HTML/PDF snapshots, page hashes, parser outputs, field evidence candidates, and review-required records.
- `source_snapshot.py` supports ordinary HTTP snapshots and an optional Playwright rendered-page adapter via `HARBORPILOT_USE_PLAYWRIGHT=1`. PDF text extraction uses `pypdf` or `PyPDF2` when installed.
- Matching strategy is stored in `data/matching_strategy.json` and can be proposed by `MatchingStrategyAgent` instead of hard-coding quota and school-tier behavior.

## LLM boundaries

- EvaluationAgent: LLM can polish explanation text only. Hard thresholds stay deterministic.
- SchoolMatchingAgent: LLM can refine consultant notes and risk wording only. Ranking bands remain rule-scored and source-gated.
- DataRefreshAgent / DataAcquisitionAgent: LLM can summarize or classify extracted source content, but cannot publish official fields without source URL, excerpt, timestamp, and human review status.
- WritingAgent: LLM is the core drafting agent, but every programme-specific claim must bind to official evidence.

## Remaining production gaps

- Replace local BackgroundTasks worker with a durable worker process when deployment needs concurrency and scheduled refresh.
- Add browser install/bootstrap for Playwright in Docker if rendered admissions portals become common.
- Add richer source diff UI: old snapshot vs new snapshot, extracted candidate vs currently published field.
- Add checkpoint replay if retry must resume exactly from one step rather than requeueing the owner workflow.


## Reference notes from GitHub and admissions RAG

- EZCollegeApp separates API-key configuration into environment setup, parses student documents into a backend database first, and then uses structured data to fill or assist application forms. HarborPilot follows the same boundary: students do not connect raw API keys; Admin or environment configuration owns model access.
- EZCollegeApp also keeps application data as structured workflow inputs before generation. HarborPilot mirrors this by storing profiles, selected programmes, questionnaire answers, field evidence, and queue state locally instead of leaving everything in browser state.
- MARAUS and MA-RAG support the direction of specialized agents with retrieval/source grounding rather than one monolithic LLM call. HarborPilot therefore treats crawler, field extraction, matching, timeline, writing, and review as separately inspectable nodes.
- The product implication is operational: every agent output needs status, owner, retry/handoff policy, source record, and human release gate. Student-facing pages should show recommendations and sources, not internal parser uncertainty.

References checked: https://github.com/ezcollegeapp-public/ezcollegeapp-public, arXiv 2507.11272, arXiv 2505.20096.


## Information barrier reduction notes

Recent checks against Global-CS and openCS-style guides show a useful product pattern: community projects are strong at broad programme discovery, peer-oriented caveats, and explaining how to compare programmes, but they explicitly remain decision-support references rather than official requirement sources. HarborPilot should therefore use community/open guides for recall, taxonomy, and qualitative comparison only.

For student-facing assurance, every selected programme should show:

- institution, school, programme name, region, and official programme/application links before timeline tasks;
- a field-level source map for programme page, application portal, deadline, language, materials, and tuition;
- whether each field is current-cycle verified, previous-cycle official reference, missing, conflicted, or community-only;
- the concrete value still available for planning, even when the status is previous-cycle reference;
- a warning only where the field is being used for preparation rhythm rather than final submission.

Implementation implication: lowering information barriers is not just showing more links. The platform needs a source ledger: official snapshot, extracted value, source URL, excerpt, capture time, hash, parser, confidence, and reviewer decision. Open guides can seed candidate URLs and comparison dimensions; official pages and portals decide publishable fields.

References checked: https://github.com/Global-CS-application/global-cs-application.github.io, https://github.com/opencsapp/opencsapp.github.io, https://github.com/ezcollegeapp-public/ezcollegeapp-public.
