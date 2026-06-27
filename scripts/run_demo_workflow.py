from __future__ import annotations

import json
from pathlib import Path

from harbor_agent.agents.orchestrator import WorkflowOrchestrator
from harbor_agent.config import get_settings
from harbor_agent.core.llm import build_llm_provider
from harbor_agent.models import ApplicantProfileInput


def main() -> None:
    payload = ApplicantProfileInput.model_validate_json(
        Path("examples/sample_profile.json").read_text(encoding="utf-8")
    )
    result = WorkflowOrchestrator(build_llm_provider(get_settings())).run_assessment(payload)
    print(
        json.dumps(
            {
                "workflow_id": result.workflow_id,
                "overall_level": result.assessment.overall_level,
                "top_programs": [
                    {
                        "id": item.program.id,
                        "tier": item.tier,
                        "fit_score": item.fit_score,
                        "hard_rule_passed": item.hard_rule_passed,
                    }
                    for item in result.recommendations[:5]
                ],
                "trace_nodes": [event.node for event in result.trace],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

