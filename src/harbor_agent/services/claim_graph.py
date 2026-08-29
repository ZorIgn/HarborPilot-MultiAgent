"""Deterministic claim/evidence graph for writing gates.

The writing composer is intentionally allowed to produce a useful draft before
all programme sources have been reviewed.  This module is the boundary between
that exploratory draft and a formal ``writing_ready`` decision.  It does not
read ``Program.field_evidence`` or ``WritingDraft.review_flags`` as evidence.
Programme claims can only be supported by a current, formal-use-ready
``DecisionFact`` projected through ``ResolvedProgramView``.

Student story claims use the explicit ``WritingDraft.fact_bindings`` contract.
Those bindings are source identifiers supplied by the questionnaire/story-card
path; they are kept separate from programme claims because a student's own
fact is not an official programme fact.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from harbor_agent.models import (
    ClaimEdge,
    ClaimGraph,
    ClaimNode,
    ClaimValidationStatus,
    DecisionStatus,
    Program,
    ProgramMatch,
    ResolvedProgramView,
    WritingDraft,
)
from harbor_agent.services.resolved_program import resolve_program_view

# These aliases deliberately describe *fields*, rather than trying to infer a
# claim's truth from a phrase.  The value and provenance still come from the
# matching DecisionFact below.
PROGRAM_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "institution": (
        "institution",
        "university",
        "school",
        "大学",
        "学校",
        "院校",
        "学院",
    ),
    "program_name": (
        "program name",
        "course name",
        "项目",
        "项目名称",
        "课程项目",
    ),
    "official_program_url": (
        "official programme page",
        "official program page",
        "项目官网",
        "官网项目页",
        "official url",
    ),
    "application_url": (
        "application portal",
        "apply online",
        "application url",
        "申请系统",
        "申请链接",
    ),
    "deadline": (
        "deadline",
        "application closes",
        "closing date",
        "due date",
        "截止日期",
        "申请截止",
        "截止时间",
    ),
    "tuition_hkd": (
        "tuition",
        "tuition fee",
        "fees",
        "fee",
        "hkd",
        "hk$",
        "学费",
        "学费金额",
        "费用",
    ),
    "application_fee_hkd": (
        "application fee",
        "application fees",
        "申请费",
        "申请费用",
    ),
    "language_requirement": (
        "language requirement",
        "english requirement",
        "ielts",
        "toefl",
        "pte",
        "语言要求",
        "英语要求",
    ),
    "min_gpa": (
        "minimum gpa",
        "min gpa",
        "gpa requirement",
        "gpa",
        "最低绩点",
        "绩点要求",
    ),
    "required_backgrounds": (
        "admission requirement",
        "admissions requirement",
        "entry requirement",
        "prerequisite",
        "required background",
        "录取要求",
        "入学要求",
        "先修",
        "背景要求",
    ),
    "portfolio_required": (
        "portfolio required",
        "portfolio requirement",
        "portfolio",
        "作品集要求",
        "作品集",
    ),
    "materials": (
        "application materials",
        "required documents",
        "supporting documents",
        "申请材料",
        "所需材料",
    ),
    "essay_prompts": (
        "essay prompt",
        "writing prompt",
        "文书题目",
        "申请题目",
    ),
}

_ALL_PROGRAM_TERMS = tuple(
    sorted(
        {
            term.lower()
            for aliases in PROGRAM_FIELD_ALIASES.values()
            for term in aliases
            if term
        },
        key=len,
        reverse=True,
    )
)

# Context terms identify a programme-related sentence, but are not evidence
# for any particular field.  Keeping them separate prevents a claim such as
# ``the programme has a high employment rate`` from being accidentally mapped
# to a perfectly valid (but irrelevant) programme-name fact.
_PROGRAM_CONTEXT_TERMS = (
    "programme",
    "program",
    "university",
    "school",
    "faculty",
    "department",
    "course",
    "module",
    "professor",
    "employment",
    "placement",
    "salary",
    "admission",
    "acceptance",
    "学校",
    "大学",
    "学院",
    "项目",
    "课程",
    "模块",
    "教授",
    "导师",
    "就业",
    "薪资",
    "录取",
)

_UNSUPPORTED_PROGRAM_FACT_TERMS = (
    "employment rate",
    "placement rate",
    "salary",
    "admission chance",
    "admission odds",
    "acceptance rate",
    "录取率",
    "录取概率",
    "就业率",
    "就业数据",
    "薪资",
    "教授",
    "导师",
    "professor",
    "course",
    "courses",
    "curriculum",
    "module",
    "modules",
    "课程",
    "模块",
)

# A boundary/disclaimer sentence does not assert a programme fact.  It should
# not create a false claim merely because a draft explains that a source is
# still needed.  The check is only used when no concrete field term/value was
# detected; an assertion such as ``Tuition is ...; verify it`` remains a claim
# and is blocked until a DecisionFact supports it.
_BOUNDARY_TERMS = (
    "unverified",
    "needs verification",
    "need to verify",
    "must be verified",
    "before final submission",
    "until it has a source",
    "without a source",
    "should remain outside",
    "must not",
    "do not write",
    "cannot write",
    "requires a source",
    "待核验",
    "需要核验",
    "需核验",
    "不得写",
    "不能写",
    "不能进入最终稿",
    "补来源",
    "缺少来源",
    "需要绑定",
)

_SUBSTANTIVE_NUMBER = re.compile(
    r"(?:\b\d+(?:[.,]\d+)?\s*(?:%|percent|hkd|hk\$|usd|months?|days?)?\b|"
    r"\b(?:ielts|toefl|pte)\s*[:>=-]?\s*\d+(?:\.\d+)?\b)",
    re.IGNORECASE,
)


def build_claim_graph(
    draft: WritingDraft | Mapping[str, Any] | None,
    matches: Iterable[ProgramMatch | ResolvedProgramView | Mapping[str, Any] | Program] = (),
    *,
    resolved_views: Mapping[str, ResolvedProgramView]
    | Iterable[ResolvedProgramView]
    | None = None,
    student_facts: Mapping[str, Any] | Iterable[Any] | None = None,
) -> ClaimGraph:
    """Build a stable claim graph for one writing draft.

    ``matches`` may contain compatibility ``ProgramMatch`` objects, but their
    embedded catalogue fields are never considered evidence.  The resolver is
    re-run for each programme unless a caller supplies an explicit
    ``ResolvedProgramView`` mapping (useful for an isolated offline fixture).
    ``ProgramMatch.decision_facts`` is intentionally not used as an implicit
    fallback: a checkpointed match is not proof that the current evidence
    store still accepts that fact.
    """

    model = _coerce_draft(draft)
    normalized_matches = [_coerce_match(item) for item in matches]
    explicit_views = _normalise_views(resolved_views)
    views: dict[str, ResolvedProgramView] = {}
    for match in normalized_matches:
        program_id = match.program.id
        if program_id in explicit_views:
            views[program_id] = explicit_views[program_id]
            continue
        views[program_id] = _resolve_current_view(match.program)

    target_ids = list(model.target_program_ids) if model else []
    if not target_ids:
        target_ids = [
            item.catalog.program_id if isinstance(item, ResolvedProgramView) else item.program.id
            for item in normalized_matches
        ]

    nodes: list[ClaimNode] = []
    edges: list[ClaimEdge] = []
    graph_blockers: list[str] = []

    if model is None:
        graph_blockers.append("尚未生成文书草稿，无法建立 ClaimGraph。")
    else:
        nodes.extend(_student_binding_nodes(model, edges, student_facts=student_facts))
        program_claims = _extract_program_claims(model, target_ids, normalized_matches)
        for claim_index, (text, field_names, program_id) in enumerate(program_claims, start=1):
            claim_id = _claim_id("program", claim_index, text, program_id)
            node, claim_edges = _validate_program_claim(
                claim_id=claim_id,
                text=text,
                field_names=field_names,
                program_id=program_id,
                views=views,
            )
            nodes.append(node)
            edges.extend(claim_edges)

    nodes = _stable_nodes(nodes)
    edges = _stable_edges(edges)
    required_nodes = [node for node in nodes if node.required_for_formal]
    unsupported = [node for node in required_nodes if node.status != ClaimValidationStatus.SUPPORTED]
    for node in unsupported:
        graph_blockers.extend(f"{node.claim_id}: {blocker}" for blocker in node.blockers)
    if not nodes and model is not None:
        graph_blockers.append("文书中没有可验证的事实绑定。")
    graph_blockers = _stable_unique(graph_blockers)

    if graph_blockers or unsupported:
        if any(node.status == ClaimValidationStatus.CONFLICTED for node in unsupported):
            formal_status = DecisionStatus.FAIL
        else:
            formal_status = DecisionStatus.UNKNOWN
    elif required_nodes:
        formal_status = DecisionStatus.PASS
    else:
        formal_status = DecisionStatus.UNKNOWN
        graph_blockers.append("没有足够的必需事实 claim 通过正式门禁。")

    graph_id = _graph_id(model, views, nodes)
    return ClaimGraph(
        graph_id=graph_id,
        nodes=nodes,
        edges=edges,
        formal_status=formal_status,
        blockers=_stable_unique(graph_blockers),
    )


def claim_graph_passed(graph: ClaimGraph | Mapping[str, Any] | None) -> bool:
    """Return the strict formal result consumed by WritingAgent and Critic."""

    if graph is None:
        return False
    value = graph.formal_status if isinstance(graph, ClaimGraph) else graph.get("formal_status")
    status = value.value if isinstance(value, DecisionStatus) else str(value or "")
    blockers = graph.blockers if isinstance(graph, ClaimGraph) else graph.get("blockers", [])
    return status == DecisionStatus.PASS.value and not blockers and all(
        _status_value(node.status) == ClaimValidationStatus.SUPPORTED.value
        for node in (graph.nodes if isinstance(graph, ClaimGraph) else graph.get("nodes", []))
        if _node_required(node)
    )


def _coerce_draft(draft: WritingDraft | Mapping[str, Any] | None) -> WritingDraft | None:
    if draft is None:
        return None
    if isinstance(draft, WritingDraft):
        return draft
    return WritingDraft.model_validate(draft)


def _coerce_match(
    value: ProgramMatch | ResolvedProgramView | Mapping[str, Any] | Program,
) -> ProgramMatch | ResolvedProgramView:
    if isinstance(value, (ProgramMatch, ResolvedProgramView)):
        return value
    if isinstance(value, Program):
        return ProgramMatch(
            program=value,
            tier="candidate",
            fit_score=0,
            hard_rule_passed=False,
            reasons=[],
            risks=[],
            actions=[],
            rule_checks=[],
        )
    if "catalog" in value and "facts" in value:
        return ResolvedProgramView.model_validate(value)
    return ProgramMatch.model_validate(value)


def _normalise_views(
    values: Mapping[str, ResolvedProgramView]
    | Iterable[ResolvedProgramView]
    | None,
) -> dict[str, ResolvedProgramView]:
    if values is None:
        return {}
    if isinstance(values, Mapping):
        output: dict[str, ResolvedProgramView] = {}
        for key, value in values.items():
            output[str(key)] = value if isinstance(value, ResolvedProgramView) else ResolvedProgramView.model_validate(value)
        return output
    return {
        value.program_id: value if isinstance(value, ResolvedProgramView) else ResolvedProgramView.model_validate(value)
        for value in values
    }


def _resolve_current_view(program: Program) -> ResolvedProgramView:
    """Resolve from the persisted evidence store, never from catalogue seeds."""

    try:
        return resolve_program_view(program)
    except Exception as exc:  # noqa: BLE001 - fail closed when the evidence store is unavailable.
        return ResolvedProgramView(
            program_id=program.id,
            cycle=program.cycle,
            catalog=program,
            formal_readiness=DecisionStatus.UNKNOWN,
            formal_blockers=[f"当前证据 resolver 不可用：{type(exc).__name__}。"],
        )


def _student_binding_nodes(
    draft: WritingDraft,
    edges: list[ClaimEdge],
    *,
    student_facts: Mapping[str, Any] | Iterable[Any] | None = None,
) -> list[ClaimNode]:
    """Validate student bindings against the trusted story/fact registry.

    A draft controls neither the registry nor the meaning of an identifier.
    Consequently an arbitrary non-empty ``fact_id`` is blocked unless the
    caller supplies a matching trusted record.  Concrete numbers in a claim
    are also checked against the registered record so a valid ID cannot be
    reused to support a changed claim.
    """

    nodes: list[ClaimNode] = []
    bindings = list(draft.fact_bindings or [])
    registry = _normalise_student_facts(student_facts)
    for index, binding in enumerate(bindings, start=1):
        binding_map = binding if isinstance(binding, Mapping) else _as_mapping(binding)
        text = str(binding_map.get("claim") or binding_map.get("text") or "").strip()
        source_ids = _split_ids(binding_map.get("fact_id") or binding_map.get("evidence_id"))
        if not text:
            text = f"未命名学生事实绑定 {index}"
        claim_id = _claim_id("student", index, text, None)
        blockers: list[str] = []
        if not source_ids:
            blockers.append("学生事实 claim 缺少显式 fact/evidence id。")
        else:
            unknown_ids = [source_id for source_id in source_ids if source_id not in registry]
            if unknown_ids:
                blockers.append(
                    "学生事实 ID 不存在于可信 registry：" + ", ".join(unknown_ids) + "。"
                )
            for source_id in source_ids:
                record = registry.get(source_id)
                if record is None:
                    continue
                if not _student_binding_content_matches(text, binding_map, record):
                    blockers.append(
                        f"学生事实绑定 {source_id} 的 claim 内容与可信记录不一致。"
                    )
                binding_cycle = binding_map.get("cycle") or binding_map.get("target_cycle")
                record_cycle = record.get("cycle")
                if binding_cycle and not record_cycle:
                    blockers.append(
                        f"学生事实绑定 {source_id} 声明了 cycle，但可信记录没有可核验的 cycle。"
                    )
                elif binding_cycle and _cycle_key(binding_cycle) != _cycle_key(record_cycle):
                    blockers.append(
                        f"学生事实绑定 {source_id} 的 cycle 与可信记录不一致。"
                    )

                # A cycle embedded in the claimed prose is still an objective
                # assertion.  It cannot evade the registry contract merely by
                # omitting the optional binding metadata field.
                claim_cycles = _claim_cycle_hints(text)
                if claim_cycles and not record_cycle:
                    blockers.append(
                        f"学生事实绑定 {source_id} 的 claim 包含 cycle，但可信记录没有可核验的 cycle。"
                    )
                elif claim_cycles and any(
                    claim_cycle != _cycle_key(record_cycle)
                    for claim_cycle in claim_cycles
                ):
                    blockers.append(
                        f"学生事实绑定 {source_id} 的 claim cycle 与可信记录不一致。"
                    )

        if not blockers:
            node = ClaimNode(
                claim_id=claim_id,
                text=text,
                claim_type="student_fact",
                status=ClaimValidationStatus.SUPPORTED,
                evidence_ids=source_ids,
                blockers=[],
            )
            edges.extend(
                ClaimEdge(
                    source_id=source_id,
                    target_claim_id=claim_id,
                    relation="SUPPORTS",
                    reason="可信 student fact registry 中的显式 binding",
                )
                for source_id in source_ids
            )
        else:
            node = ClaimNode(
                claim_id=claim_id,
                text=text,
                claim_type="student_fact",
                status=ClaimValidationStatus.BLOCKED,
                evidence_ids=source_ids,
                blockers=_stable_unique(blockers),
            )
        nodes.append(node)
    return nodes


def _normalise_student_facts(
    values: Mapping[str, Any] | Iterable[Any] | None,
) -> dict[str, dict[str, Any]]:
    """Convert story cards/fact records into an ID-indexed trusted registry."""

    if values is None:
        return {}
    items: list[tuple[Any, Any]]
    if isinstance(values, Mapping):
        direct_fields = {
            "id", "fact_id", "evidence_id", "claim", "text", "title", "content", "value"
        }
        items = [(None, values)] if direct_fields.intersection(values) else list(values.items())
    elif isinstance(values, (str, bytes)):
        items = [(None, values)]
    else:
        items = [(None, value) for value in values]

    registry: dict[str, dict[str, Any]] = {}
    for key, value in items:
        payload = _as_mapping(value)
        candidate_ids: list[str] = []
        if key is not None and not isinstance(key, (dict, list, tuple, set)):
            candidate_ids.extend(_split_ids(key))
        for field_name in ("id", "fact_id", "evidence_id", "source_id"):
            candidate_ids.extend(_split_ids(payload.get(field_name)))
        candidate_ids.extend(_split_ids(payload.get("evidence_ids")))
        candidate_ids = _stable_unique(candidate_ids)
        if not candidate_ids:
            continue

        text_parts: list[str] = []
        for field_name in (
            "claim", "text", "content", "title", "situation", "task", "action",
            "result", "reflection", "related_skills", "target_relevance", "value", "fact_value",
            "target_program_relevance",
        ):
            field_value = payload.get(field_name)
            if field_value is not None and str(field_value).strip():
                text_parts.append(_stringify_fact_value(field_value))
        record = {
            "id": candidate_ids[0],
            "text": " ".join(dict.fromkeys(part for part in text_parts if part)),
            "value": payload.get("value", payload.get("fact_value")),
            "cycle": payload.get("cycle", payload.get("target_cycle")),
        }
        for candidate_id in candidate_ids:
            registry[candidate_id] = record
    return registry


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="json")
        except TypeError:
            dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dict(dumped)
    return {"value": value}


def _stringify_fact_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Mapping):
        return " ".join(
            f"{key} {_stringify_fact_value(item)}" for key, item in value.items() if item is not None
        )
    if isinstance(value, (list, tuple, set)):
        return " ".join(_stringify_fact_value(item) for item in value)
    return str(value).strip()


def _student_binding_content_matches(
    claim_text: str,
    binding: Mapping[str, Any],
    record: Mapping[str, Any],
) -> bool:
    record_text = " ".join(
        part for part in (str(record.get("text") or ""), _stringify_fact_value(record.get("value"))) if part
    ).lower()
    if not record_text:
        return False
    claim_terms = _meaningful_terms(claim_text)
    record_terms = _meaningful_terms(record_text)
    # A trusted ID may support a concise excerpt of its registry record, but
    # must not be reused to add new substantive details.  Lexical containment
    # is intentionally stricter than a loose overlap: a shared word such as
    # "dashboard" cannot validate an invented client, outcome or role.
    if claim_terms and (not record_terms or not claim_terms.issubset(record_terms)):
        return False
    claim_numbers = _number_tokens(claim_text)
    if claim_numbers:
        record_numbers = _number_tokens(record_text)
        if not all(any(_numbers_equal(number, candidate) for candidate in record_numbers) for number in claim_numbers):
            return False
    explicit_value = binding.get("value") or binding.get("fact_value")
    if explicit_value is not None:
        expected = _stringify_fact_value(explicit_value).strip().lower()
        if expected and expected not in record_text:
            expected_numbers = _number_tokens(expected)
            if not expected_numbers or not all(
                any(_numbers_equal(number, candidate) for candidate in _number_tokens(record_text))
                for number in expected_numbers
            ):
                return False
    return True


def _meaningful_terms(value: Any) -> set[str]:
    lowered = str(value or "").lower()
    stop_words = {
        "a", "an", "and", "the", "for", "of", "to", "in", "on", "with", "by",
        "my", "our", "this", "that", "student", "story", "experience", "经历", "项目",
        "我的", "一个", "一段", "负责", "参与",
    }
    terms = set(re.findall(r"[a-z][a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", lowered))
    return {term for term in terms if term not in stop_words}


def _extract_program_claims(
    draft: WritingDraft,
    target_ids: list[str],
    matches: list[ProgramMatch | ResolvedProgramView],
) -> list[tuple[str, list[str], str | None]]:
    target_names: dict[str, list[str]] = {}
    for item in matches:
        program = item.catalog if isinstance(item, ResolvedProgramView) else item.program
        target_names[program.id] = [
            str(value).strip().lower()
            for value in (
                program.id,
                program.institution,
                program.institution_zh,
                program.name,
                program.name_zh,
                program.school,
                program.school_zh,
            )
            if value and len(str(value).strip()) >= 2
        ]

    # A few compatibility callers construct a skeletal draft solely to run a
    # deterministic gate.  Treat missing prose fields as empty rather than
    # crashing the gate: an incomplete artifact must fail closed, not turn an
    # input-shape edge case into a 500.
    sections = [
        getattr(draft, "draft", "") or "",
        getattr(draft, "draft_zh", "") or "",
        getattr(draft, "draft_en", "") or "",
        *(getattr(draft, "school_customization", []) or []),
    ]
    extracted: list[tuple[str, list[str], str | None]] = []
    seen: set[str] = set()
    for section in sections:
        for sentence in _sentences(section):
            text = sentence.strip()
            if not text:
                continue
            lower = text.lower()
            program_id = _program_id_for_text(lower, target_ids, target_names)
            field_names = _field_hints(lower, target_names.get(program_id or "", []))
            has_program_context = bool(field_names or _has_program_term(lower))
            if not has_program_context:
                continue
            if program_id is None and len(target_ids) == 1:
                program_id = target_ids[0]
            concrete_fields = set(field_names) - {"program_name", "institution"}
            has_url_or_value = bool(_SUBSTANTIVE_NUMBER.search(lower) or re.search(r"https?://", lower))
            has_identity_name = bool(
                program_id
                and any(
                    name in lower
                    for name in target_names.get(program_id, [])
                    if len(name) >= 3
                )
            )
            if _contains_unsupported_program_term(lower) and not concrete_fields:
                # An unsupported programme assertion must remain a claim so it
                # is blocked; it must not be downgraded to an identity claim.
                field_names = []
                concrete_fields = set()
                has_identity_name = False
            if _is_disclaimer(lower) and not (concrete_fields or has_url_or_value or has_identity_name):
                continue
            if not field_names:
                # A concrete programme/school assertion still needs the
                # identity facts, even when no specialised field alias was
                # detected.
                field_names = ["__unresolved_program_fact__"]
            key = _claim_text_key(text, program_id)
            if key in seen:
                continue
            seen.add(key)
            extracted.append((text, field_names, program_id))

    # An explicit fact binding can identify a programme claim even if the
    # wording uses no known alias.  The resolver will decide whether the
    # referenced fact is actually current and formal-use-ready.
    for binding in draft.fact_bindings or []:
        text = str(binding.get("claim") or binding.get("text") or "").strip()
        if not text:
            continue
        lower = text.lower()
        # A numerical student story (for example, an error-rate reduction) is
        # not a programme claim merely because it contains a number.  Concrete
        # programme assertions are already extracted from the actual draft
        # prose above; binding-only claims must explicitly refer to a programme
        # context before they enter programme-fact validation.
        if not _has_program_term(lower):
            continue
        program_id = _program_id_for_text(lower, target_ids, target_names)
        if program_id is None and len(target_ids) == 1:
            program_id = target_ids[0]
        field_names = _field_hints(lower, target_names.get(program_id or "", []))
        if not field_names:
            field_names = ["__unresolved_program_fact__"]
        key = _claim_text_key(text, program_id)
        if key not in seen:
            seen.add(key)
            extracted.append((text, field_names, program_id))
    return extracted


def _program_id_for_text(
    text: str,
    target_ids: list[str],
    target_names: Mapping[str, list[str]],
) -> str | None:
    for program_id in target_ids:
        names = target_names.get(program_id, [])
        if str(program_id).lower() in text:
            return program_id
        if any(name in text for name in names):
            return program_id
    return None


def _field_hints(text: str, target_names: Iterable[str]) -> list[str]:
    fields: list[str] = []
    # Match longest aliases first so ``application fee`` is not classified as
    # a generic application URL or a generic fee claim.
    for field_name, aliases in PROGRAM_FIELD_ALIASES.items():
        if any(_term_in_text(alias.lower(), text) for alias in aliases):
            fields.append(field_name)
    names = [name for name in target_names if name]
    if names and any(name in text for name in names):
        if "program_name" not in fields:
            fields.append("program_name")
        if any(name in text for name in names if "university" in name or "大学" in name or "institution" in name):
            fields.append("institution")
    fields = _stable_unique(fields)
    # ``program``/``school`` are often grammatical context around a more
    # specific claim (for example, ``programme tuition``).  They must not
    # silently add an identity-fact requirement to that specialised claim.
    concrete = set(fields) - {"program_name", "institution"}
    if concrete:
        fields = [field for field in fields if field not in {"program_name", "institution"}]
    return fields


def _validate_program_claim(
    *,
    claim_id: str,
    text: str,
    field_names: list[str],
    program_id: str | None,
    views: Mapping[str, ResolvedProgramView],
) -> tuple[ClaimNode, list[ClaimEdge]]:
    if not field_names:
        return (
            ClaimNode(
                claim_id=claim_id,
                text=text,
                claim_type="program_fact",
                program_id=program_id,
                status=ClaimValidationStatus.BLOCKED,
                blockers=["无法将 programme claim 映射到已定义的 DecisionFact 字段。"],
            ),
            [],
        )
    if not program_id:
        return (
            ClaimNode(
                claim_id=claim_id,
                text=text,
                claim_type="program_fact",
                program_id=None,
                status=ClaimValidationStatus.BLOCKED,
                blockers=["无法将 programme claim 绑定到唯一目标项目。"],
            ),
            [],
        )
    view = views.get(program_id)
    if view is None:
        return (
            ClaimNode(
                claim_id=claim_id,
                text=text,
                claim_type="program_fact",
                program_id=program_id,
                status=ClaimValidationStatus.BLOCKED,
                blockers=["目标项目没有当前周期的 ResolvedProgramView。"],
            ),
            [],
        )

    identity_fields = {"institution", "program_name"}
    if set(field_names).issubset(identity_fields) and _matches_catalog_identity(
        text,
        view,
        field_names,
    ):
        # The acquisition contract deliberately collects decision-bearing
        # admissions fields, not duplicate display-name rows.  A current,
        # reviewed official-program URL is the durable binding between the
        # selected catalogue identity and its official programme page.  It may
        # therefore support an identity-only sentence ("X at Y"), while any
        # tuition, deadline, requirement or other objective claim still goes
        # through its own field-specific DecisionFact below.
        binding_fact = view.fact("official_program_url")
        if (
            binding_fact.program_id == view.program_id
            and _cycle_key(binding_fact.cycle) == _cycle_key(view.cycle)
            and binding_fact.decision_status == DecisionStatus.PASS
            and binding_fact.formal_use_ready
            and binding_fact.normalized_value
        ):
            evidence_ids = [binding_fact.evidence_id] if binding_fact.evidence_id else []
            edges = [
                ClaimEdge(
                    source_id=binding_fact.fact_id,
                    target_claim_id=claim_id,
                    relation="SUPPORTS",
                    reason="current reviewed official programme binding",
                )
            ]
            if binding_fact.evidence_id:
                edges.append(
                    ClaimEdge(
                        source_id=binding_fact.evidence_id,
                        target_claim_id=claim_id,
                        relation="SUPPORTS",
                        reason="published official programme binding evidence",
                    )
                )
            return (
                ClaimNode(
                    claim_id=claim_id,
                    text=text,
                    claim_type="program_fact",
                    program_id=program_id,
                    status=ClaimValidationStatus.SUPPORTED,
                    decision_fact_ids=[binding_fact.fact_id],
                    evidence_ids=evidence_ids,
                    blockers=[],
                ),
                edges,
            )

    decision_fact_ids: list[str] = []
    evidence_ids: list[str] = []
    blockers: list[str] = []
    edges: list[ClaimEdge] = []
    statuses: list[DecisionStatus] = []
    for field_name in field_names:
        fact = view.fact(field_name)
        statuses.append(fact.decision_status)
        if (
            fact.program_id != view.program_id
            or _cycle_key(fact.cycle) != _cycle_key(view.cycle)
        ):
            blockers.append(
                f"{field_name}: DecisionFact 的 program/cycle 与当前 ResolvedProgramView 不一致。"
            )
            continue
        if (
            fact.decision_status == DecisionStatus.PASS
            and fact.formal_use_ready
            and fact.normalized_value is not None
        ):
            value_matches, value_blocker = _claim_value_matches(
                field_name,
                text,
                fact.normalized_value,
                cycle=view.cycle,
            )
            if not value_matches:
                blockers.append(f"{field_name}: {value_blocker or 'claim 中的值与 DecisionFact 不一致。'}")
                continue
            decision_fact_ids.append(fact.fact_id)
            if fact.evidence_id:
                evidence_ids.append(fact.evidence_id)
            edges.append(
                ClaimEdge(
                    source_id=fact.fact_id,
                    target_claim_id=claim_id,
                    relation="SUPPORTS",
                    reason=f"current reviewed DecisionFact: {field_name}",
                )
            )
            if fact.evidence_id:
                edges.append(
                    ClaimEdge(
                        source_id=fact.evidence_id,
                        target_claim_id=claim_id,
                        relation="SUPPORTS",
                        reason=f"published evidence for {field_name}",
                    )
                )
            continue
        if fact.decision_status == DecisionStatus.FAIL:
            blockers.extend(f"{field_name}: {item}" for item in (fact.blockers or ["DecisionFact 明确不通过。"]))
        else:
            blockers.extend(
                f"{field_name}: {item}"
                for item in (fact.blockers or ["字段没有当前周期的已审核正式事实。"])
            )

    # A claim that mentions several aliases (e.g. institution and programme
    # name) is supported only when every objective field is supported.
    if all(status == DecisionStatus.PASS for status in statuses) and not blockers:
        status = ClaimValidationStatus.SUPPORTED
    elif any(status == DecisionStatus.FAIL for status in statuses):
        status = ClaimValidationStatus.CONFLICTED
    else:
        status = ClaimValidationStatus.BLOCKED
    return (
        ClaimNode(
            claim_id=claim_id,
            text=text,
            claim_type="program_fact",
            program_id=program_id,
            status=status,
            decision_fact_ids=_stable_unique(decision_fact_ids),
            evidence_ids=_stable_unique(evidence_ids),
            blockers=_stable_unique(blockers),
        ),
        edges,
    )


def _matches_catalog_identity(
    text: str,
    view: ResolvedProgramView,
    field_names: Iterable[str],
) -> bool:
    """Require exact selected-program names before using the URL binding."""

    lowered = str(text or "").lower()
    program = view.catalog
    values_by_field = {
        "program_name": (program.name, program.name_zh),
        "institution": (
            program.institution,
            program.institution_zh,
            program.school,
            program.school_zh,
        ),
    }
    for field_name in field_names:
        candidates = [
            str(value).strip().lower()
            for value in values_by_field.get(field_name, ())
            if value and len(str(value).strip()) >= 2
        ]
        if not candidates or not any(candidate in lowered for candidate in candidates):
            return False
    return True


_NUMERIC_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![A-Za-z0-9_])"
)
_ISO_DATE_TOKEN = re.compile(r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
_CHINESE_DATE_TOKEN = re.compile(r"(?<!\d)(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?")
_MONTH_DATE_TOKEN = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})\b",
    re.IGNORECASE,
)
_DAY_MONTH_DATE_TOKEN = re.compile(
    r"\b(\d{1,2})\s+(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|"
    r"May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|"
    r"Nov(?:ember)?|Dec(?:ember)?)\s+(20\d{2})\b",
    re.IGNORECASE,
)
_CYCLE_TOKEN = re.compile(
    r"(?<!\d)(20\d{2})\s*(?:[-/]\s*|\s+)?(fall|autumn|spring|summer)(?![a-z])|"
    r"(?<!\d)(20\d{2})\s*年\s*(春季?|秋季?|夏季?)(?![\u4e00-\u9fff])",
    re.IGNORECASE,
)
_LANGUAGE_SCORE_TOKEN = re.compile(
    r"\b(ielts|toefl|pte)\s*(?:score\s*)?[:>=-]?\s*(\d+(?:\.\d+)?)\b",
    re.IGNORECASE,
)

_LIST_TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "computing": ("computing", "computer science", "computer engineering", "计算机", "计算"),
    "transcript": ("transcript", "academic record", "成绩单"),
    "recommendation": ("recommendation", "reference letter", "推荐信"),
    "cv": ("cv", "resume", "curriculum vitae", "简历"),
    "personal_statement": ("personal statement", "statement of purpose", "sop", "个人陈述"),
    "portfolio": ("portfolio", "作品集"),
    "writing_sample": ("writing sample", "writing example", "写作样本"),
    "passport": ("passport", "护照"),
}


def _claim_value_matches(
    field_name: str,
    text: str,
    expected: Any,
    *,
    cycle: str | None = None,
) -> tuple[bool, str | None]:
    """Compare concrete claim content with a canonical normalized fact.

    The claim extractor intentionally remains lightweight; this comparator is
    the fail-closed boundary that prevents a valid evidence ID from being
    reused to support a different number, URL, currency, date or cycle.
    """

    claim_text = str(text or "").strip()
    if not claim_text:
        return False, "claim 文本为空。"
    if cycle:
        claim_cycles = _claim_cycle_hints(claim_text)
        expected_cycle = _cycle_key(cycle)
        if claim_cycles and any(item != expected_cycle for item in claim_cycles):
            return False, "claim 中的申请季与当前 DecisionFact cycle 不一致。"

    if field_name in {"official_program_url", "application_url"}:
        expected_url = _canonical_url(expected)
        claim_urls = [_canonical_url(item) for item in re.findall(r"https?://[^\s<>\]})]+", claim_text)]
        if not expected_url or expected_url not in claim_urls:
            return False, "claim 未包含与 DecisionFact 一致的完整 URL。"
        return True, None

    if field_name == "deadline":
        expected_dates = _date_keys(str(expected))
        claim_dates = _date_keys(claim_text)
        if not expected_dates or not claim_dates or not expected_dates.intersection(claim_dates):
            return False, "claim 中的截止日期与 DecisionFact 不一致或缺失。"
        return True, None

    if field_name in {"tuition_hkd", "application_fee_hkd"}:
        if not _has_hkd_currency(claim_text):
            return False, "claim 未明确使用 HKD/HK$（货币单位不可信）。"
        return _numeric_claim_matches(claim_text, expected, cycle=cycle)

    if field_name == "min_gpa":
        return _numeric_claim_matches(claim_text, expected, cycle=cycle, allow_scale=True)

    if field_name == "language_requirement":
        return _language_claim_matches(claim_text, expected)

    if field_name == "portfolio_required":
        return _boolean_claim_matches(claim_text, expected)

    if isinstance(expected, (list, tuple, set)):
        return _list_claim_matches(claim_text, expected, field_name)
    if isinstance(expected, Mapping):
        expected_text = _stringify_fact_value(expected).lower()
        if expected_text and expected_text in claim_text.lower():
            return True, None
        return False, "claim 内容未包含与 DecisionFact 一致的结构化值。"

    expected_text = str(expected).strip().lower()
    if not expected_text:
        return False, "DecisionFact 的 normalized_value 为空。"
    if expected_text in claim_text.lower():
        return True, None
    return False, "claim 内容未包含与 DecisionFact 一致的值。"


def _numeric_claim_matches(
    text: str,
    expected: Any,
    *,
    cycle: str | None = None,
    allow_scale: bool = False,
) -> tuple[bool, str | None]:
    expected_numbers = _number_tokens(_stringify_fact_value(expected))
    claim_numbers = _number_tokens(text)
    if not expected_numbers:
        return False, "DecisionFact 的数值不可确定性比较。"
    if not claim_numbers:
        return False, "claim 未提供该字段的具体数值。"
    if not all(
        any(_numbers_equal(expected_number, candidate) for candidate in claim_numbers)
        for expected_number in expected_numbers
    ):
        return False, "claim 中的数值与 DecisionFact 不一致。"

    expected_decimal = _to_decimal(expected_numbers[0])
    cycle_year = str(_cycle_key(cycle) or "")[:4]
    for candidate in claim_numbers:
        if any(_numbers_equal(candidate, expected_number) for expected_number in expected_numbers):
            continue
        # A sentence may identify the supported cycle (for example, “2027
        # fall tuition ...”) without changing the tuition/GPA value.
        if cycle_year and candidate == cycle_year:
            continue
        if allow_scale and expected_decimal is not None and expected_decimal <= 100:
            if _numbers_equal(candidate, "100") and re.search(r"/\s*100\b|满分\s*100", text, re.IGNORECASE):
                continue
        return False, "claim 附带了与该 DecisionFact 不一致的额外数值。"
    return True, None


def _language_claim_matches(text: str, expected: Any) -> tuple[bool, str | None]:
    expected_pairs = _language_pairs(expected)
    claim_pairs = _language_pairs(text)
    if not expected_pairs:
        return False, "DecisionFact 的语言要求不是可比较的结构化值。"
    if not claim_pairs:
        return False, "claim 未提供 IELTS/TOEFL/PTE 的具体分数。"
    for provider, score in claim_pairs.items():
        expected_score = expected_pairs.get(provider)
        if expected_score is None or not _numbers_equal(score, expected_score):
            return False, "claim 中的语言考试分数与 DecisionFact 不一致。"
    return True, None


def _language_pairs(value: Any) -> dict[str, str]:
    if isinstance(value, Mapping):
        output: dict[str, str] = {}
        for key, score in value.items():
            provider = str(key).strip().lower()
            if provider in {"ielts", "toefl", "pte"}:
                output[provider] = str(score)
        return output
    return {
        provider.lower(): score
        for provider, score in _LANGUAGE_SCORE_TOKEN.findall(str(value or ""))
    }


def _boolean_claim_matches(text: str, expected: Any) -> tuple[bool, str | None]:
    expected_bool = bool(expected)
    lowered = text.lower()
    negative = re.search(
        r"\b(?:not|no|without)\s+(?:required|need|needed|mandatory)\b|"
        r"\b(?:unnecessary|optional)\b|不需要|无需|不要求|否|免提交",
        lowered,
        re.IGNORECASE,
    )
    positive = re.search(
        r"\b(?:required|need|needed|mandatory|yes)\b|需要|要求|必须|是",
        lowered,
        re.IGNORECASE,
    )
    if negative:
        mentioned = False
    elif positive:
        mentioned = True
    else:
        return False, "claim 未明确说明该布尔要求是否需要。"
    if mentioned != expected_bool:
        return False, "claim 中的布尔要求与 DecisionFact 不一致。"
    return True, None


def _list_claim_matches(
    text: str,
    expected: Iterable[Any],
    field_name: str,
) -> tuple[bool, str | None]:
    expected_values = [_canonical_list_term(item) for item in expected if str(item).strip()]
    lowered = text.lower()
    if not expected_values:
        if re.search(r"无(?:需|特殊)?|none|not required|无需|不要求", lowered, re.IGNORECASE):
            return True, None
        return False, "claim 未明确说明该列表字段为空/无要求。"

    matched = [
        value
        for value in expected_values
        if any(_term_in_text(alias, lowered) for alias in _list_aliases(value))
    ]
    if not matched:
        return False, f"claim 未包含 {field_name} 的可核验具体项。"

    # If a claim names a well-known material/background that is absent from
    # the canonical list, do not silently treat a different item as supported.
    known_mentioned = {
        key
        for key, aliases in _LIST_TERM_ALIASES.items()
        if any(_term_in_text(alias, lowered) for alias in aliases)
    }
    expected_known = set(expected_values).intersection(_LIST_TERM_ALIASES)
    unexpected = known_mentioned - expected_known
    if unexpected and field_name in {"materials", "required_backgrounds", "essay_prompts"}:
        return False, "claim 包含不在 DecisionFact 列表中的具体项。"
    return True, None


def _list_aliases(value: str) -> tuple[str, ...]:
    return _LIST_TERM_ALIASES.get(value, (value,))


def _canonical_list_term(value: Any) -> str:
    lowered = str(value).strip().lower().replace("-", "_")
    for key, aliases in _LIST_TERM_ALIASES.items():
        if lowered == key or lowered in {alias.lower() for alias in aliases}:
            return key
    return lowered


def _canonical_url(value: Any) -> str:
    return str(value or "").strip().lower().rstrip("/")


def _has_hkd_currency(text: str) -> bool:
    return re.search(r"(?:\bhkd\b|hk\s*\$|港币|港幣)", text, re.IGNORECASE) is not None


def _number_tokens(value: Any) -> list[str]:
    return [match.group(0).replace(",", "") for match in _NUMERIC_TOKEN.finditer(str(value or ""))]


def _to_decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _numbers_equal(left: Any, right: Any) -> bool:
    left_decimal = _to_decimal(left)
    right_decimal = _to_decimal(right)
    return left_decimal is not None and right_decimal is not None and left_decimal == right_decimal


def _date_keys(value: str) -> set[str]:
    keys = {
        f"{year}-{int(month):02d}-{int(day):02d}"
        for year, month, day in _ISO_DATE_TOKEN.findall(value)
    }
    keys.update(
        f"{year}-{int(month):02d}-{int(day):02d}"
        for year, month, day in _CHINESE_DATE_TOKEN.findall(value)
    )
    month_numbers = {
        name.lower(): number
        for number, names in enumerate(
            (
                ("jan", "january"), ("feb", "february"), ("mar", "march"),
                ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
                ("aug", "august"), ("sep", "september"), ("oct", "october"),
                ("nov", "november"), ("dec", "december"),
            ),
            start=1,
        )
        for name in names
    }
    for month_text, day, year in _MONTH_DATE_TOKEN.findall(value):
        month = month_numbers.get(month_text[:3].lower())
        if month:
            keys.add(f"{year}-{month:02d}-{int(day):02d}")
    for day, month_text, year in _DAY_MONTH_DATE_TOKEN.findall(value):
        month = month_numbers.get(month_text[:3].lower())
        if month:
            keys.add(f"{year}-{month:02d}-{int(day):02d}")
    return keys


def _cycle_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s_/]+", "-", text)
    text = text.replace("autumn", "fall").replace("秋季", "fall").replace("秋", "fall")
    text = text.replace("春季", "spring").replace("春", "spring").replace("夏季", "summer").replace("夏", "summer")
    return text.strip("-")


def _claim_cycle_hints(text: str) -> set[str]:
    hints: set[str] = set()
    for year, season, chinese_year, chinese_season in _CYCLE_TOKEN.findall(text):
        if year and season:
            hints.add(_cycle_key(f"{year}-{season}"))
        elif chinese_year and chinese_season:
            hints.add(_cycle_key(f"{chinese_year}-{chinese_season}"))
    return hints


def _sentences(value: str | None) -> list[str]:
    if not value:
        return []
    # Keep URLs intact while splitting common Chinese/English sentence and
    # list boundaries.  Deterministic snippets are more useful to reviewers
    # than a NLP sentence model here.
    return [
        part.strip()
        for part in re.split(r"(?:[。！？!?]+|\n+|(?<=\.)\s+|[;；])", str(value))
        if part.strip()
    ]


def _has_program_term(text: str) -> bool:
    return any(_term_in_text(term, text) for term in (*_ALL_PROGRAM_TERMS, *_PROGRAM_CONTEXT_TERMS))


def _contains_unsupported_program_term(text: str) -> bool:
    return any(_term_in_text(term, text) for term in _UNSUPPORTED_PROGRAM_FACT_TERMS)


def _term_in_text(term: str, text: str) -> bool:
    if not term:
        return False
    if re.search(r"[a-z]", term, flags=re.IGNORECASE):
        return re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", text, flags=re.IGNORECASE) is not None
    return term in text


def _is_disclaimer(text: str) -> bool:
    lowered = text.lower()
    if any(term in lowered for term in _BOUNDARY_TERMS):
        return True
    # Generic source-boundary prose such as ``official claims must be tied to
    # a page`` is instructional, not an assertion about the selected program.
    return (
        any(term in lowered for term in ("official", "官网", "source", "来源"))
        and any(term in lowered for term in ("must", "should", "需要", "不得", "不能", "需"))
        and not _SUBSTANTIVE_NUMBER.search(lowered)
    )


def _claim_text_key(text: str, program_id: str | None) -> str:
    return "|".join([program_id or "", re.sub(r"\s+", " ", text).strip().lower()])


def _split_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[,;\s]+", str(value))
    return _stable_unique(str(item).strip() for item in values if str(item).strip())


def _claim_id(kind: str, index: int, text: str, program_id: str | None) -> str:
    raw = json.dumps(
        {"kind": kind, "index": index, "text": text, "program_id": program_id},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "claim_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _graph_id(
    draft: WritingDraft | None,
    views: Mapping[str, ResolvedProgramView],
    nodes: Iterable[ClaimNode],
) -> str:
    payload = {
        "draft": draft.model_dump(mode="json") if draft else None,
        "programs": sorted(
            (
                program_id,
                view.cycle,
                sorted((field, fact.fact_id, fact.decision_status.value, fact.formal_use_ready) for field, fact in view.facts.items()),
            )
            for program_id, view in views.items()
        ),
        "nodes": [node.model_dump(mode="json") for node in nodes],
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8"))
    return "claim_graph_" + digest.hexdigest()[:24]


def _stable_nodes(nodes: Iterable[ClaimNode]) -> list[ClaimNode]:
    return sorted(nodes, key=lambda node: node.claim_id)


def _stable_edges(edges: Iterable[ClaimEdge]) -> list[ClaimEdge]:
    unique: dict[tuple[str, str, str, str], ClaimEdge] = {}
    for edge in edges:
        key = (edge.source_id, edge.target_claim_id, edge.relation, edge.reason)
        unique[key] = edge
    return [unique[key] for key in sorted(unique)]


def _stable_unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value).strip()))


def _status_value(value: Any) -> str:
    return value.value if isinstance(value, ClaimValidationStatus) else str(value or "")


def _node_required(value: Any) -> bool:
    return bool(value.required_for_formal if isinstance(value, ClaimNode) else value.get("required_for_formal", True))
