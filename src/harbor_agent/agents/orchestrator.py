from __future__ import annotations

from harbor_agent.core.llm import LLMProvider
from harbor_agent.models import (
    ApplicantProfileInput,
    ApplicationPlanResult,
    BackgroundStageResult,
    NormalizedProfile,
    ProgramMatch,
    ProgramPlanResult,
    QuestionnaireResponse,
    WorkflowResult,
    WritingPlanResult,
)
from harbor_agent.runtime.compat import (
    to_application_plan,
    to_background,
    to_program_plan,
    to_workflow_result,
    to_writing_plan,
)
from harbor_agent.runtime.state import WorkflowGoal
from harbor_agent.runtime.workflow import MultiAgentRuntime, WorkflowStartRequest


class WorkflowOrchestrator:
    """Compatibility façade for established stage endpoints.

    The Supervisor runtime owns all workflow execution. This class only adapts
    legacy method names and response models to one runtime start request.
    """

    def __init__(
        self,
        llm: LLMProvider | None = None,
        *,
        runtime: MultiAgentRuntime | None = None,
    ) -> None:
        # Keep the constructor compatible with existing callers. Runtime policy
        # determines whether a configured model participates in a given run.
        self.llm = llm
        self.runtime = runtime or MultiAgentRuntime()

    def run_background_stage(self, payload: ApplicantProfileInput) -> BackgroundStageResult:
        return to_background(
            self._start(
                goal=WorkflowGoal.BACKGROUND_ASSESSMENT,
                payload=payload,
                user_request="兼容背景评估入口",
            )
        )

    def run_program_plan_stage(self, payload: ApplicantProfileInput) -> ProgramPlanResult:
        return to_program_plan(
            self._start(
                goal=WorkflowGoal.PROGRAM_RECOMMENDATION,
                payload=payload,
                user_request="兼容择校方案入口",
            )
        )

    def run_application_plan_stage(
        self,
        payload: ApplicantProfileInput,
        selected_program_ids: list[str],
    ) -> ApplicationPlanResult:
        return to_application_plan(
            self._start(
                goal=WorkflowGoal.APPLICATION_PLANNING,
                payload=payload,
                user_request="兼容申请规划入口",
                selected_program_ids=selected_program_ids,
            )
        )

    def run_writing_plan_stage(
        self,
        payload: ApplicantProfileInput,
        questionnaire: QuestionnaireResponse,
        selected_program_ids: list[str],
        document_type: str = "PS",
    ) -> WritingPlanResult:
        return to_writing_plan(
            self._start(
                goal=WorkflowGoal.WRITING,
                payload=payload,
                user_request="兼容文书规划入口",
                questionnaire=questionnaire,
                selected_program_ids=selected_program_ids,
                document_type=document_type,
            )
        )

    def run_assessment(self, payload: ApplicantProfileInput) -> WorkflowResult:
        return to_workflow_result(
            self._start(
                goal=WorkflowGoal.FULL_APPLICATION_PLAN,
                payload=payload,
                user_request="兼容完整评估入口",
            )
        )

    def selected_program_matches(
        self,
        payload: ApplicantProfileInput,
        selected_program_ids: list[str],
    ) -> tuple[NormalizedProfile, list[ProgramMatch]]:
        """Return an established helper shape from a completed runtime run."""

        state = self._start(
            goal=WorkflowGoal.APPLICATION_PLANNING,
            payload=payload,
            user_request="兼容已选项目入口",
            selected_program_ids=selected_program_ids,
        )
        plan = to_application_plan(state)
        if state.normalized_profile is None:
            raise RuntimeError("runtime completed without a normalized profile")
        return NormalizedProfile.model_validate(state.normalized_profile), plan.selected_programs

    def _start(
        self,
        *,
        goal: WorkflowGoal,
        payload: ApplicantProfileInput,
        user_request: str,
        questionnaire: QuestionnaireResponse | None = None,
        selected_program_ids: list[str] | None = None,
        document_type: str = "PS",
    ):
        return self.runtime.start(
            WorkflowStartRequest(
                goal=goal,
                profile=payload.model_dump(mode="json"),
                user_request=user_request,
                questionnaire=questionnaire.model_dump(mode="json") if questionnaire else None,
                selected_program_ids=list(selected_program_ids or []),
                document_type=document_type,
            )
        )
