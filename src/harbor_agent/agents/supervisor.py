from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, Field

from harbor_agent.agents.base import BaseAgent
from harbor_agent.agents.critic import CriticOutcome
from harbor_agent.runtime.decision import AgentDecision, DecisionType
from harbor_agent.runtime.errors import LLMStructuredOutputError
from harbor_agent.runtime.state import AgentState, WorkflowGoal, WorkflowTask, WorkflowTaskStatus

RouteTarget = Literal[
    "AssessmentAgent",
    "ResearchAgent",
    "MatchingAgent",
    "VerificationAgent",
    "PlanningAgent",
    "WritingAgent",
    "CriticAgent",
    "ASK_USER",
    "HUMAN_REVIEW",
    "END",
]


class SupervisorRoute(BaseModel):
    """A visible routing choice made from live state, never a fixed sequence."""

    next_agent: RouteTarget
    reason: str
    new_tasks: list[WorkflowTask] = Field(default_factory=list)
    state_patch: dict = Field(default_factory=dict)


class SupervisorAgent(BaseAgent):
    name = "SupervisorAgent"
    description = "Plans tasks, dynamically routes work, handles interrupts and stops only when the requested goal is fulfilled."
    allowed_tools: set[str] = set()
    can_ask_user = True
    can_request_human = True
    possible_handoffs = {"AssessmentAgent", "ResearchAgent", "MatchingAgent", "VerificationAgent", "PlanningAgent", "WritingAgent", "CriticAgent"}
    input_state_fields = ("goal", "tasks", "assessment", "candidate_program_ids", "program_matches", "timeline", "writing_draft")
    output_state_fields = (
        "tasks",
        "candidate_program_ids",
        "researched_program_ids",
        "program_matches",
        "selected_matches",
        "selected_program_ids",
        "fields_needing_verification",
        "verification_conflicts",
        "writing_draft",
        "writing_ready",
        "working_memory",
        "supervisor_replans",
        "user_question",
        "final_result",
    )
    deterministic_boundaries = ("never executes tools directly", "never skips admissions eligibility checks", "never turns community data into official evidence")
    def build_system_prompt(self) -> str:
        """Describe the Supervisor control contract to a model without exposing internals."""

        return (
            f"{super().build_system_prompt()}\n"
            "You are the workflow Supervisor. Return exactly one AgentDecision JSON. "
            "You never call tools. For a specialist handoff use HANDOFF with one of the "
            "runtime-provided `available_routes` targets and return no tool_calls. "
            "Use ASK_USER or HUMAN_REVIEW "
            "only when the runtime state requires it, and use COMPLETE only when the "
            "requested goal is fully satisfied. Do not provide a state_patch; the runtime "
            "policy applies the validated route patch. Never hand off to yourself or invent "
            "an agent name.\n"
            "Hard boundaries: never skip admissions eligibility, never turn preferences into "
            "eligibility, never use unverified official fields formally, and never treat "
            "community data as official evidence."
        )
    def build_model_messages(self, state: AgentState) -> list[dict[str, Any]]:
        """Give the model a compact routing view without dumping the shared state."""

        route_options = self.route_options(state)
        context = {
            "workflow_id": state.workflow_id,
            "goal": state.goal.value,
            "status": state.status.value,
            "current_agent": state.current_agent,
            "previous_agent": state.previous_agent,
            "profile_available": state.raw_profile is not None,
            "assessment_ready": state.normalized_profile is not None and state.assessment is not None,
            "candidate_count": len(state.candidate_program_ids),
            "researched_count": len(state.researched_program_ids),
            "match_count": len(state.program_matches),
            "selected_program_ids": state.selected_program_ids[:20],
            "verification_complete": bool(state.working_memory.get("verification_complete")),
            "verification_conflict_count": len(state.verification_conflicts),
            "timeline_ready": bool(state.timeline or state.timeline_ready),
            "writing_ready": bool(state.writing_draft or state.writing_ready),
            "critic_outcome": state.working_memory.get("critic_outcome"),
            "reverify_attempts": state.working_memory.get("reverify_attempts", 0),
            "supervisor_replans": state.supervisor_replans,
            "waiting_for_user": bool(state.user_question),
            "waiting_for_human": bool(state.human_review_reason),
            "tasks": [task.model_dump(mode="json") for task in state.tasks[-20:]],
            # The model can select only one of these policy-safe targets. This
            # keeps the routing decision genuinely model-driven without allowing
            # it to bypass evidence, eligibility, or human-review guards.
            "available_routes": [
                {"target": route.next_agent, "policy_reason": route.reason}
                for route in route_options
            ],
        }
        return [
            {"role": "system", "content": self.build_system_prompt()},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False, separators=(",", ":"))},
        ]


    def step(self, state: AgentState) -> AgentDecision:
        route = self.route(state)
        if route.next_agent == "END":
            return AgentDecision(decision=DecisionType.COMPLETE, reasoning_summary=route.reason, state_patch=route.state_patch)
        if route.next_agent == "ASK_USER":
            return AgentDecision(decision=DecisionType.ASK_USER, reasoning_summary=route.reason, state_patch=route.state_patch, user_question=state.user_question or "请补充继续所需的信息。")
        if route.next_agent == "HUMAN_REVIEW":
            return AgentDecision(decision=DecisionType.HUMAN_REVIEW, reasoning_summary=route.reason, state_patch=route.state_patch, human_review_reason=state.human_review_reason or "需要人工审核。")
        return AgentDecision(decision=DecisionType.HANDOFF, reasoning_summary=route.reason, state_patch=route.state_patch, next_agent=route.next_agent)

    def model_decision(
        self,
        state: AgentState,
        tool_schemas: list[dict[str, Any]],
        *,
        messages: list[dict[str, Any]] | None = None,
    ) -> AgentDecision | None:
        """Ask the configured model for a route, then apply the deterministic policy gate.

        The model is now part of every Supervisor turn (the workflow invokes this agent
        through :class:`AgentExecutor`).  The policy gate deliberately owns state patches
        and the set of legal transitions: a malformed or unsafe model route is retried by
        the executor instead of being allowed to skip required assessment, matching, or
        verification work.
        """

        decision = self._model_proposal(state, tool_schemas, messages=messages)
        if decision is None:
            return None

        selected_target = (
            "END"
            if decision.decision == DecisionType.COMPLETE
            else "ASK_USER"
            if decision.decision == DecisionType.ASK_USER
            else "HUMAN_REVIEW"
            if decision.decision == DecisionType.HUMAN_REVIEW
            else decision.next_agent
            if decision.decision == DecisionType.HANDOFF
            else None
        )
        policy_routes = {route.next_agent: route for route in self.route_options(state)}
        policy_route = policy_routes.get(selected_target)
        if policy_route is None:
            allowed = ", ".join(policy_routes)
            raise LLMStructuredOutputError(
                f"Supervisor model target {selected_target!r} is not permitted for the current "
                f"policy state. Allowed targets: {allowed}."
            )
        expected_decision = (
            DecisionType.COMPLETE
            if policy_route.next_agent == "END"
            else DecisionType.ASK_USER
            if policy_route.next_agent == "ASK_USER"
            else DecisionType.HUMAN_REVIEW
            if policy_route.next_agent == "HUMAN_REVIEW"
            else DecisionType.HANDOFF
        )
        if decision.decision != expected_decision:
            raise LLMStructuredOutputError(
                f"Supervisor model decision {decision.decision.value} is not permitted for "
                f"the selected policy route ({policy_route.next_agent})."
            )
        if decision.tool_calls:
            raise LLMStructuredOutputError("SupervisorAgent is not permitted to call tools directly.")
        if decision.state_patch:
            raise LLMStructuredOutputError("SupervisorAgent may not write an unvalidated state patch.")

        if expected_decision == DecisionType.HANDOFF:
            if decision.next_agent != policy_route.next_agent or decision.next_agent == self.name:
                raise LLMStructuredOutputError(
                    f"Supervisor handoff target {decision.next_agent!r} is not the validated "
                    f"target {policy_route.next_agent!r}."
                )
            return AgentDecision(
                decision=DecisionType.HANDOFF,
                reasoning_summary=decision.reasoning_summary,
                next_agent=policy_route.next_agent,
                state_patch=policy_route.state_patch,
                confidence=decision.confidence,
            )

        if decision.next_agent:
            raise LLMStructuredOutputError("Terminal Supervisor decisions must not include next_agent.")

        if expected_decision == DecisionType.ASK_USER:
            question = str(policy_route.state_patch.get("user_question") or state.user_question or "请补充继续所需的信息。")
            return AgentDecision(
                decision=DecisionType.ASK_USER,
                reasoning_summary=decision.reasoning_summary,
                state_patch=policy_route.state_patch,
                user_question=question,
                confidence=decision.confidence,
            )
        if expected_decision == DecisionType.HUMAN_REVIEW:
            reason = str(state.human_review_reason or "需要人工审核。")
            return AgentDecision(
                decision=DecisionType.HUMAN_REVIEW,
                reasoning_summary=decision.reasoning_summary,
                state_patch=policy_route.state_patch,
                human_review_reason=reason,
                confidence=decision.confidence,
            )
        # COMPLETE carries the canonical final_result patch generated by the policy.
        return AgentDecision(
            decision=DecisionType.COMPLETE,
            reasoning_summary=decision.reasoning_summary,
            state_patch=policy_route.state_patch,
            confidence=decision.confidence,
        )

    def route(self, state: AgentState) -> SupervisorRoute:
        """Route based on completed state rather than a predetermined DAG."""

        if state.human_review_reason:
            return self._route("HUMAN_REVIEW", "A prior agent requested human review.", state)
        if state.user_question:
            return self._route("ASK_USER", "A prior agent is waiting for missing user information.", state)

        if self._financial_hard_cap_requires_budget_choice(state):
            return self._route(
                "ASK_USER",
                "The stated hard budget cap excludes every otherwise actionable programme.",
                state,
                user_question=(
                    "当前预算已设为硬上限，全部可行动项目的已记录学费都超出预算。"
                    "请提高预算，或将预算模式改为 soft 后继续；soft 模式会保留超预算项目并明确标注费用风险。"
                ),
            )

        hint = state.working_memory.get("routing_hint")
        if isinstance(hint, dict) and hint.get("target") == "ResearchAgent":
            memory = deepcopy(state.working_memory)
            memory.pop("routing_hint", None)
            tool_results = dict(memory.get("tool_results", {}))
            tool_results.pop("search_program_catalog", None)
            memory["tool_results"] = tool_results
            replans = state.supervisor_replans + 1
            return self._route(
                "ResearchAgent",
                str(hint.get("reason") or "Matching requested broader programme research."),
                state,
                {
                    "candidate_program_ids": [],
                    "researched_program_ids": [],
                    "working_memory": memory,
                    "supervisor_replans": replans,
                },
            )

        outcome = str(state.working_memory.get("critic_outcome") or "")
        if outcome and outcome != CriticOutcome.PASS.value:
            return self._replan_route(state, outcome)

        if state.raw_profile is None:
            return self._route("ASK_USER", "A profile payload is required to start the workflow.", state, user_question="请先填写或上传申请背景资料。")
        if state.normalized_profile is None or state.assessment is None:
            return self._route("AssessmentAgent", "Profile normalization and deterministic assessment are not complete.", state)

        if state.goal == WorkflowGoal.BACKGROUND_ASSESSMENT:
            if outcome != CriticOutcome.PASS.value:
                return self._route("CriticAgent", "Background assessment needs a final bounded critic pass.", state)
            return self._route("END", "Background assessment is complete.", state, final=True)

        if not state.candidate_program_ids:
            return self._route("ResearchAgent", "No programme candidates have been researched yet.", state)
        if not state.program_matches:
            return self._route("MatchingAgent", "Candidates require separate eligibility, financial and fit evaluation.", state)
        if not state.selected_program_ids:
            return self._route(
                "ASK_USER",
                "Matching produced no viable selected programme; additional profile evidence is required.",
                state,
                user_question="当前资料无法形成可行动项目组合。请补充语言成绩、课程先修证据或调整目标方向。",
            )

        if not state.working_memory.get("verification_complete"):
            return self._route("VerificationAgent", "Selected programmes require official-source verification before formal use.", state)

        if state.goal == WorkflowGoal.PROGRAM_RECOMMENDATION:
            if outcome != CriticOutcome.PASS.value:
                return self._route("CriticAgent", "Programme portfolio requires grounded consistency review.", state)
            return self._route("END", "Grounded programme recommendation is complete.", state, final=True)

        if state.goal in {WorkflowGoal.APPLICATION_PLANNING, WorkflowGoal.FULL_APPLICATION_PLAN} and not state.timeline:
            return self._route("PlanningAgent", "Application planning has not generated an evidence-gated timeline.", state)
        if state.goal in {WorkflowGoal.WRITING, WorkflowGoal.FULL_APPLICATION_PLAN} and not state.writing_draft:
            return self._route("WritingAgent", "Writing work has not generated a fact-bound draft.", state)
        if outcome != CriticOutcome.PASS.value:
            return self._route("CriticAgent", "The requested deliverables need final consistency and grounding review.", state)
        return self._route("END", "All requested workflow deliverables are complete and reviewed.", state, final=True)

    def route_options(self, state: AgentState) -> list[SupervisorRoute]:
        """Return the policy-safe next routes available to a model-driven turn.

        Most states intentionally expose one route because a prerequisite is
        incomplete or a safety gate is active. Once official verification is
        complete for a full application plan, however, the timeline and
        fact-bound writing workstreams are independent. The model can choose
        their order while the deterministic policy still requires both before
        the final Critic pass.
        """

        primary = self.route(state)
        if not (
            primary.next_agent == "PlanningAgent"
            and state.goal == WorkflowGoal.FULL_APPLICATION_PLAN
            and not state.timeline
            and not state.timeline_ready
            and not state.writing_draft
            and not state.writing_ready
        ):
            return [primary]
        return [
            primary,
            self._route(
                "WritingAgent",
                "Both verified planning and fact-bound writing are pending; writing may safely run before the timeline.",
                state,
            ),
        ]

    @staticmethod
    def _financial_hard_cap_requires_budget_choice(state: AgentState) -> bool:
        """Recognize a MatchingAgent hard-cap outcome before considering replanning.

        ``financial_hard_cap_blocked`` is emitted only when every programme that
        would otherwise enter the portfolio is excluded by the user's hard budget
        constraint. The extra profile check prevents an old marker from changing
        routing after the user switches the budget mode on resume.
        """

        if state.selected_program_ids or not state.working_memory.get("financial_hard_cap_blocked"):
            return False
        profiles = (state.normalized_profile, state.raw_profile)
        return any(
            isinstance(profile, dict) and profile.get("budget_mode") == "hard_cap"
            for profile in profiles
        )

    def _replan_route(self, state: AgentState, outcome: str) -> SupervisorRoute:
        memory = deepcopy(state.working_memory)
        memory.pop("critic_outcome", None)
        memory["tool_results"] = {}
        replans = state.supervisor_replans + 1
        if outcome == CriticOutcome.REPLAN_RESEARCH.value:
            return self._route("ResearchAgent", "Critic requested broader or corrected programme research.", state, {"candidate_program_ids": [], "researched_program_ids": [], "working_memory": memory, "supervisor_replans": replans})
        if outcome == CriticOutcome.REPLAN_MATCHING.value:
            return self._route("MatchingAgent", "Critic found a recommendation inconsistency and requested new matching.", state, {"program_matches": {}, "selected_matches": [], "selected_program_ids": [], "working_memory": memory, "supervisor_replans": replans})
        if outcome == CriticOutcome.REVERIFY.value:
            memory["verification_complete"] = False
            memory["verification_cursor"] = 0
            return self._route("VerificationAgent", "Critic found insufficient official grounding and requested re-verification.", state, {"fields_needing_verification": {}, "verification_conflicts": [], "working_memory": memory, "supervisor_replans": replans})
        if outcome == CriticOutcome.REWRITE.value:
            return self._route("WritingAgent", "Critic found unsupported writing claims and requested a rewrite.", state, {"writing_draft": None, "writing_ready": False, "working_memory": memory, "supervisor_replans": replans})
        return self._route("CriticAgent", "Critic outcome was not recognized; require an explicit follow-up review.", state, {"working_memory": memory, "supervisor_replans": replans})

    def _route(
        self,
        next_agent: RouteTarget,
        reason: str,
        state: AgentState,
        patch: dict | None = None,
        *,
        user_question: str | None = None,
        final: bool = False,
    ) -> SupervisorRoute:
        state_patch = dict(patch or {})
        if user_question:
            state_patch["user_question"] = user_question
        if next_agent not in {"END", "ASK_USER", "HUMAN_REVIEW"}:
            task = WorkflowTask(
                task_id=f"{next_agent}:{state.step_count + 1}",
                description=reason,
                assigned_agent=next_agent,
                status=WorkflowTaskStatus.PENDING,
            )
            state_patch["tasks"] = [*state.tasks, task.model_dump(mode="json")]
            return SupervisorRoute(next_agent=next_agent, reason=reason, new_tasks=[task], state_patch=state_patch)
        if final:
            state_patch["final_result"] = _final_result(state)
        return SupervisorRoute(next_agent=next_agent, reason=reason, state_patch=state_patch)


def _final_result(state: AgentState) -> dict:
    return {
        "workflow_id": state.workflow_id,
        "goal": state.goal.value,
        "assessment": state.assessment,
        "evidence_review": state.evidence_review,
        "recommendations": list(state.program_matches.values()),
        "selected_program_ids": state.selected_program_ids,
        "timeline": state.timeline,
        "writing": state.writing_draft,
        "formal_use_ready": not any(state.fields_needing_verification.values()) and not state.verification_conflicts,
    }
