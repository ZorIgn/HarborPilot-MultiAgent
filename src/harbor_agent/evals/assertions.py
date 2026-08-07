from __future__ import annotations

from harbor_agent.runtime.state import AgentState


def evaluate_expectations(state: AgentState, expectations: dict) -> list[str]:
    """Return human-readable deterministic eval assertion failures."""

    failures: list[str] = []
    if expected := expectations.get("final_status"):
        if state.status.value != expected:
            failures.append(f"expected status={expected}; actual={state.status.value}")
    visited = set(state.visited_agents)
    for agent in expectations.get("must_visit_agents", []):
        if agent not in visited:
            failures.append(f"expected agent not visited: {agent}")
    for agent in expectations.get("must_not_visit_agents", []):
        if agent in visited:
            failures.append(f"forbidden agent visited: {agent}")
    if expectations.get("expect_human_review") is True and state.status.value != "WAITING_HUMAN":
        failures.append("expected human review")
    if expectations.get("expect_user_question") is True and state.status.value != "WAITING_USER":
        failures.append("expected user question")
    if "formal_use_ready" in expectations and expectations.get("formal_use_ready") is not None:
        expected_formal = bool(expectations["formal_use_ready"])
        actual_formal = bool((state.final_result or {}).get("formal_use_ready"))
        if actual_formal != expected_formal:
            failures.append(f"expected formal_use_ready={expected_formal}; actual={actual_formal}")
    if expected_admissions := expectations.get("admissions_status"):
        observed = {
            str(item.get("admissions_status"))
            for item in state.program_matches.values()
            if isinstance(item, dict) and item.get("admissions_status") is not None
        }
        if not observed:
            checks = (
                state.working_memory.get("tool_results", {})
                .get("evaluate_admissions_eligibility", {})
                .get("checks", [])
            )
            by_program: dict[str, list[str]] = {}
            for check in checks:
                if not isinstance(check, dict) or not check.get("program_id"):
                    continue
                by_program.setdefault(str(check["program_id"]), []).append(
                    str(check.get("status"))
                )
            for statuses in by_program.values():
                if "FAIL" in statuses:
                    observed.add("FAIL")
                elif "UNKNOWN" in statuses:
                    observed.add("UNKNOWN")
                elif statuses:
                    observed.add("PASS")
        if expected_admissions not in observed:
            failures.append(
                f"expected admissions_status={expected_admissions}; actual={sorted(observed)}"
            )
    return failures
