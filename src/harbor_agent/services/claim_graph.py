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
        nodes.extend(_student_binding_nodes(model, edges))
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


def _student_binding_nodes(draft: WritingDraft, edges: list[ClaimEdge]) -> list[ClaimNode]:
    nodes: list[ClaimNode] = []
    bindings = list(draft.fact_bindings or [])
    for index, binding in enumerate(bindings, start=1):
        text = str(binding.get("claim") or binding.get("text") or "").strip()
        source_ids = _split_ids(binding.get("fact_id") or binding.get("evidence_id"))
        if not text:
            text = f"未命名学生事实绑定 {index}"
        claim_id = _claim_id("student", index, text, None)
        if source_ids:
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
                    reason="显式 student fact binding",
                )
                for source_id in source_ids
            )
        else:
            node = ClaimNode(
                claim_id=claim_id,
                text=text,
                claim_type="student_fact",
                status=ClaimValidationStatus.BLOCKED,
                blockers=["学生事实 claim 缺少显式 fact/evidence id。"],
            )
        nodes.append(node)
    return nodes


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
        if not (_has_program_term(lower) or _SUBSTANTIVE_NUMBER.search(lower)):
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

    decision_fact_ids: list[str] = []
    evidence_ids: list[str] = []
    blockers: list[str] = []
    edges: list[ClaimEdge] = []
    statuses: list[DecisionStatus] = []
    for field_name in field_names:
        fact = view.fact(field_name)
        statuses.append(fact.decision_status)
        if fact.decision_status == DecisionStatus.PASS and fact.formal_use_ready and fact.normalized_value is not None:
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
