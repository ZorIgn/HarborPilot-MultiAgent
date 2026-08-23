from __future__ import annotations

from typing import Any, cast

from harbor_agent.core.llm import LLMProvider
from harbor_agent.llm.provider import OpenAICompatibleToolCallingProvider, RuntimeLLMProvider
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
    to_preliminary_writing_plan,
    to_workflow_result,
    to_writing_plan,
)
from harbor_agent.runtime.state import WorkflowGoal, WorkflowStatus
from harbor_agent.runtime.workflow import MultiAgentRuntime, WorkflowStartRequest


class WorkflowDeliveryBlockedError(RuntimeError):
    """A compatibility façade requested a formal artifact that runtime blocked.

    This is intentionally distinct from an execution failure.  The state holds
    structured Critic readiness and blockers that an API can expose as a 409
    rather than leaking an internal ``require_completed`` exception as a 500.
    """

    def __init__(self, state) -> None:
        self.state = state
        super().__init__(f"workflow delivery is {state.status.value}")


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
        model_driven: bool | None = None,
    ) -> None:
        # Preserve compatibility while forwarding a configured tool-calling model into the Supervisor runtime.
        # Providers without tool calling intentionally keep the deterministic runtime.
        self.llm = llm
        if runtime is not None:
            self.runtime = runtime
        else:
            runtime_llm = _as_runtime_provider(llm)
            enabled = bool(runtime_llm) if model_driven is None else bool(model_driven)
            self.runtime = MultiAgentRuntime(
                llm=runtime_llm if enabled else None,
                model_driven=enabled,
            )

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
        state = self._start(
            goal=WorkflowGoal.WRITING,
            payload=payload,
            user_request="兼容文书规划入口",
            questionnaire=questionnaire,
            selected_program_ids=selected_program_ids,
            document_type=document_type,
        )
        if state.status != WorkflowStatus.COMPLETED:
            try:
                return to_preliminary_writing_plan(state)
            except RuntimeError as exc:
                # A blocked workflow can expose a revisable draft when one was
                # produced, but it must report a structured delivery block
                # rather than leaking a compatibility RuntimeError as a 500.
                raise WorkflowDeliveryBlockedError(state) from exc
        return to_writing_plan(state)

    def run_assessment(self, payload: ApplicantProfileInput) -> WorkflowResult:
        state = self._start(
            goal=WorkflowGoal.FULL_APPLICATION_PLAN,
            payload=payload,
            user_request="兼容完整评估入口",
        )
        if state.status != WorkflowStatus.COMPLETED:
            raise WorkflowDeliveryBlockedError(state)
        return to_workflow_result(state)

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

def _as_runtime_provider(llm: Any | None) -> RuntimeLLMProvider | None:
    """Adapt a configured legacy provider to the runtime tool-call protocol.

    The compatibility façade receives the older ``complete_json`` provider,
    while runtime Agent turns require ``complete(messages=..., tools=...)``.
    Providers without tool calling (including the legacy mock) stay on the
    deterministic runtime instead of being presented as Agentic.
    """

    if llm is None:
        return None
    if callable(getattr(llm, "complete", None)):
        return cast(RuntimeLLMProvider, llm)

    headers = getattr(llm, "_headers", None)
    authorization = headers.get("authorization") if isinstance(headers, dict) else None
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        return None
    api_key = authorization[len("Bearer ") :].strip()
    model = getattr(llm, "name", None)
    provider = getattr(llm, "provider", None)
    base_url = getattr(llm, "base_url", None)
    if not api_key or not isinstance(model, str) or not model or not isinstance(provider, str) or not provider:
        return None
    return OpenAICompatibleToolCallingProvider(
        api_key=api_key,
        model=model,
        provider=provider,
        base_url=base_url if isinstance(base_url, str) else None,
    )
