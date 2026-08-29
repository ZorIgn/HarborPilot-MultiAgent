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
    if "critic_readiness" in expectations and expectations.get("critic_readiness") is not None:
        expected_readiness = str(expectations["critic_readiness"])
        final_result = state.final_result if isinstance(state.final_result, dict) else {}
        actual_readiness = final_result.get("critic_readiness")
        if actual_readiness is None:
            actual_readiness = state.working_memory.get("critic_readiness")
        if str(actual_readiness) != expected_readiness:
            failures.append(
                f"expected critic_readiness={expected_readiness}; actual={actual_readiness}"
            )
    if expectations.get("expect_blockers") is True:
        final_result = state.final_result if isinstance(state.final_result, dict) else {}
        blockers = final_result.get("blockers")
        if not isinstance(blockers, list) or not blockers:
            blockers = state.working_memory.get("critic_blockers")
        if not isinstance(blockers, list) or not blockers:
            failures.append("expected at least one critic blocker")
    if "financial_status" in expectations and expectations.get("financial_status") is not None:
        expected_financial = str(expectations["financial_status"])
        tool_results = state.working_memory.get("tool_results", {})
        financial_result = (
            tool_results.get("evaluate_financial_feasibility", {})
            if isinstance(tool_results, dict)
            else {}
        )
        assessments = (
            financial_result.get("assessments", [])
            if isinstance(financial_result, dict)
            else []
        )
        observed_financial: set[str] = set()
        for item in assessments:
            if not isinstance(item, dict):
                continue
            value = item.get("financial_status")
            if value is None:
                value = item.get("status")
            if value is not None:
                observed_financial.add(str(value))
        if expected_financial not in observed_financial:
            failures.append(
                f"expected financial_status={expected_financial}; actual={sorted(observed_financial)}"
            )
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
