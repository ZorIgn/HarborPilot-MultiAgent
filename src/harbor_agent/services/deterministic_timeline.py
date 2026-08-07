"""Deterministic application-timeline construction behind PlanningAgent tools."""

from __future__ import annotations

from datetime import date, timedelta

from harbor_agent.models import ApplicationRound, DataStatus, Program, ProgramMatch, TimelineTask
from harbor_agent.services.external_candidates import (
    qs_previous_cycle_deadline,
    qs_previous_cycle_open_date,
    qs_source_url_for_program,
    qs_window_status_for_program,
)
from harbor_agent.services.formal_gate import accepted_deadline, accepted_url, formal_timeline_blockers, formal_timeline_ready
from harbor_agent.services.program_urls import student_application_url, student_program_url


def build_timeline_tasks(matches: list[ProgramMatch], today: date | None = None) -> list[TimelineTask]:
    """Build preparation and, where verified, formal application tasks deterministically."""

    today = today or date.today()
    selected = list(matches)
    if not selected:
        return []

    tasks: dict[str, TimelineTask] = {}
    shared_program_ids = [item.program.id for item in selected]
    earliest_reference = _earliest_known_deadline(selected)
    internal_start = max(today, date(today.year, 8, 15))
    source_review_due = _reference_due_date(today, earliest_reference, internal_start, days_before=150)
    transcript_due = _reference_due_date(today, earliest_reference, internal_start + timedelta(days=7), days_before=120)
    cv_due = _reference_due_date(today, earliest_reference, internal_start + timedelta(days=14), days_before=105)
    language_due = _reference_due_date(today, earliest_reference, internal_start + timedelta(days=21), days_before=90)

    tasks["source_review"] = _task(
        id="source_review",
        title="确认学校官网要求：截止日期、材料、学费、语言要求",
        due_date=source_review_due,
        priority="high",
        task_type="source_review",
        linked_program_ids=shared_program_ids,
        basis="正式时间线之前必须查看学校官网、申请系统、PDF/FAQ；社区经验不能替代学校要求。",
        date_basis="人工复核",
        official_deadline=None,
        previous_cycle_reference=earliest_reference,
        materials=["official_program_page", "official_pdf_or_faq", "application_system"],
        dependencies=["核对项目来源", "打开官方项目页", "记录原文摘录和页面快照"],
        status="需复核",
        risk_level="高",
        review_required=True,
    )
    tasks["common_transcript"] = _task(
        id="common_transcript",
        title="准备正式成绩单、在读证明和核心课程清单",
        due_date=transcript_due,
        priority="high",
        task_type="materials",
        linked_program_ids=shared_program_ids,
        basis="公共材料先行准备；项目级硬门槛按项目详情页、申请系统和往届参考逐项标注。",
        date_basis="学生准备动作",
        official_deadline=None,
        previous_cycle_reference=earliest_reference,
        materials=["transcript", "degree_certificate", "core_courses"],
        dependencies=["确认 GPA 口径", "补充排名", "标注先修课成绩"],
        status="未开始",
        risk_level="中",
        review_required=True,
    )
    tasks["common_cv"] = _task(
        id="common_cv",
        title="整理通用 CV、经历证据和推荐人素材包",
        due_date=cv_due,
        priority="high",
        task_type="materials",
        linked_program_ids=shared_program_ids,
        basis="公共材料合并维护，避免为每个项目重复创建成绩单、CV、推荐人任务。",
        date_basis="学生准备动作",
        official_deadline=None,
        previous_cycle_reference=earliest_reference,
        materials=["cv", "recommendation", "experience_proof"],
        dependencies=["完成故事卡", "确认推荐人关系", "整理量化结果"],
        status="未开始",
        risk_level="中",
    )
    tasks["language_delivery"] = _task(
        id="language_delivery",
        title="语言成绩重考、出分与官方送分缓冲",
        due_date=language_due,
        priority="medium",
        task_type="language",
        linked_program_ids=shared_program_ids,
        basis="不同项目单项要求、是否接受后补和送分周期不同，正式判断需逐项目确认。",
        date_basis="学生准备动作",
        official_deadline=None,
        previous_cycle_reference=earliest_reference,
        materials=["language_score"],
        dependencies=["补充语言单项", "确认 IELTS/TOEFL/PTE 要求"],
        status="未开始",
        risk_level="中",
        review_required=True,
    )

    for item in selected:
        program = item.program
        detail_url = accepted_url(program, "official_program_url") or student_program_url(program)
        source_url = detail_url or qs_source_url_for_program(program) or program.source.url
        application_url = accepted_url(program, "application_url") or student_application_url(program)
        program_name = program.name_zh or program.name
        institution = program.institution_zh or program.institution
        formal_deadline = accepted_deadline(program, include_previous=False)
        formal_ready = formal_timeline_ready(item) and formal_deadline is not None
        blocked_fields = formal_timeline_blockers(item)
        previous_deadline = qs_previous_cycle_deadline(program)
        reference = previous_deadline or accepted_deadline(program, include_previous=True)
        previous_open = qs_previous_cycle_open_date(program) if previous_deadline else None
        planning_open = _planning_reference_date(previous_open, today)
        window_status = qs_window_status_for_program(program)
        verify_due = _reference_due_date(today, reference, internal_start + timedelta(days=30), days_before=90, open_date=previous_open, days_from_open=-14)
        essay_prompt_due = _reference_due_date(today, reference, internal_start + timedelta(days=38), days_before=75, open_date=previous_open, days_from_open=7)
        upload_check_due = _reference_due_date(today, reference, internal_start + timedelta(days=52), days_before=30, open_date=previous_open, days_from_open=21)
        if not formal_ready:
            tasks[f"prepare_{program.id}"] = _task(
                id=f"prepare_{program.id}",
                title=f"核验申请轮次、材料和入口：{program_name}",
                due_date=verify_due,
                priority="medium",
                task_type="source_review",
                linked_program_ids=[program.id],
                basis=_reference_basis(program, previous_open, reference, window_status),
                date_basis="上一申请季参考" if reference else "学生准备动作",
                official_deadline="NOT_PUBLISHED",
                previous_cycle_reference=reference,
                institution=institution,
                program_name=program_name,
                program_round="当前季待发布",
                round_open_date=planning_open,
                round_deadline="NOT_PUBLISHED",
                application_url=application_url,
                submit_to="学校网申系统",
                source_url=source_url,
                materials=blocked_fields or ["deadline", "materials", "language_requirement", "application_url"],
                dependencies=[*(f"补齐字段：{field}" for field in blocked_fields), "确认官方项目页", "确认申请系统", "确认是否分轮次或 rolling"],
                status="准备中",
                risk_level="高",
                review_required=True,
            )
            if previous_open or reference:
                tasks[f"monitor_{program.id}"] = _task(
                    id=f"monitor_{program.id}",
                    title=f"关注申请开放窗口：{program.name_zh or program.name}",
                    due_date=max(today, (_planning_reference_date(previous_open or reference, today) or today) - timedelta(days=21)),
                    priority="high",
                    task_type="source_review",
                    linked_program_ids=[program.id],
                    basis="根据上一申请季官网窗口提前 3 周检查学校页面。这不是当前申请季正式日期，只用于提醒你何时核对开放入口。",
                    date_basis="上一申请季参考",
                    official_deadline="NOT_PUBLISHED",
                    previous_cycle_reference=reference,
                    institution=institution,
                    program_name=program_name,
                    program_round="开放窗口监控",
                    round_open_date=planning_open,
                    round_deadline="NOT_PUBLISHED",
                    application_url=application_url,
                    submit_to="学校项目页或网申系统",
                    source_url=source_url,
                    materials=["official_program_page", "application_system"],
                    dependencies=["打开项目页", "记录申请季", "截图或保存原文"],
                    status="准备中",
                    risk_level="中",
                    review_required=True,
                )
            tasks[f"essay_prompt_{program.id}"] = _task(
                id=f"essay_prompt_{program.id}",
                title=f"读取文书题目与字数要求：{program.name_zh or program.name}",
                due_date=essay_prompt_due,
                priority="medium",
                task_type="writing",
                linked_program_ids=[program.id],
                basis="未读取项目 prompt 前，只能生成通用大纲，不能声称满足学校指定题目。",
                date_basis="上一申请季参考" if reference else "学生准备动作",
                official_deadline="NOT_PUBLISHED",
                previous_cycle_reference=reference,
                institution=institution,
                program_name=program_name,
                program_round="文书题目核验",
                round_open_date=planning_open,
                round_deadline="NOT_PUBLISHED",
                application_url=application_url,
                submit_to="网申系统或项目 FAQ",
                source_url=source_url,
                materials=["essay_prompts", "cv", "personal_statement"],
                dependencies=["打开网申系统或项目 FAQ", "记录 prompt 原文", "确认字数和上传格式"],
                status="需复核",
                risk_level="中",
                review_required=True,
            )
            tasks[f"upload_check_{program.id}"] = _task(
                id=f"upload_check_{program.id}",
                title=f"建立网申账号并逐项核对上传材料：{program.name_zh or program.name}",
                due_date=upload_check_due,
                priority="high",
                task_type="submission",
                linked_program_ids=[program.id],
                basis="先按项目建立网申记录，把成绩单、在读/毕业证明、语言、推荐信、CV、PS/SOP 和项目特殊材料逐项映射到上传入口。当前季日期未发布时，本任务只安排材料动作，不生成正式提交日。",
                date_basis="上一申请季参考" if reference else "学生准备动作",
                official_deadline="NOT_PUBLISHED",
                previous_cycle_reference=reference,
                institution=institution,
                program_name=program_name,
                program_round="材料上传自查",
                round_open_date=planning_open,
                round_deadline="NOT_PUBLISHED",
                application_url=application_url,
                submit_to="学校网申系统",
                source_url=source_url,
                materials=["transcript", "degree_certificate", "language_score", "recommendation", "cv", "personal_statement"],
                dependencies=["建立网申账号", "逐项核对上传栏位", "记录推荐信提交方式", "确认是否有项目特殊材料"],
                status="待上传",
                risk_level="高",
                review_required=True,
            )
            continue

        application_round = _application_round_for(program, formal_deadline)
        round_name = application_round.name if application_round else "主轮次"
        round_open_date = application_round.open_date if application_round else program.open_date
        round_deadline = application_round.deadline if application_round and application_round.deadline else formal_deadline
        assert formal_deadline is not None
        tasks[f"essay_{program.id}"] = _task(
            id=f"essay_{program.id}",
            title=f"完成项目定制文书：{program.name_zh or program.name}",
            due_date=max(today, formal_deadline - timedelta(days=45)),
            priority="high",
            task_type="writing",
            linked_program_ids=[program.id],
            basis="按学校已确认截止日期倒推 45 天，预留项目定制、事实确认和英文润色时间。",
            date_basis="官方截止倒推",
            official_deadline=formal_deadline,
            previous_cycle_reference=None,
            institution=institution,
            program_name=program_name,
            program_round=round_name,
            round_open_date=round_open_date,
            round_deadline=round_deadline,
            application_url=application_url,
            submit_to="学校网申系统",
            source_url=source_url,
            materials=["personal_statement", "cv", "essay_prompts"],
            dependencies=["故事卡已确认", "Why Program 绑定学校官网信息", "完成事实确认"],
            status="未开始",
            risk_level="中",
        )
        tasks[f"final_check_{program.id}"] = _task(
            id=f"final_check_{program.id}",
            title=f"网申系统最终自查：{program.name_zh or program.name}",
            due_date=max(today, formal_deadline - timedelta(days=7)),
            priority="high",
            task_type="submission",
            linked_program_ids=[program.id],
            basis="按学校已确认截止日期倒推 7 天，避免最后一周补材料和系统拥堵。",
            date_basis="官方截止倒推",
            official_deadline=formal_deadline,
            institution=institution,
            program_name=program_name,
            program_round=f"{round_name} · 最终提交",
            round_open_date=round_open_date,
            round_deadline=round_deadline,
            application_url=application_url,
            submit_to="学校网申系统",
            source_url=source_url,
            materials=program.materials,
            dependencies=["推荐信状态", "语言送分", "网申预览 PDF", "付款状态"],
            status="未开始",
            risk_level="高",
        )

    return sorted(tasks.values(), key=lambda item: item.due_date)


def _earliest_known_deadline(matches: list[ProgramMatch]) -> date | None:
    dates: list[date] = []
    for item in matches:
        accepted = accepted_deadline(item.program, include_previous=True)
        if accepted:
            dates.append(accepted)
            continue
        previous = qs_previous_cycle_deadline(item.program)
        if previous:
            dates.append(previous)
    return min(dates) if dates else None


def _application_round_for(program: Program, deadline: date) -> ApplicationRound | None:
    """Choose the structured round that supports a current formal deadline."""

    rounds = list(getattr(program, "application_rounds", []) or [])
    for item in rounds:
        if item.deadline == deadline:
            return item
    for item in rounds:
        if item.deadline is not None:
            return item
    return rounds[0] if rounds else None


def _reference_due_date(
    today: date,
    reference_deadline: date | None,
    fallback: date,
    *,
    days_before: int,
    open_date: date | None = None,
    days_from_open: int | None = None,
) -> date:
    planning_open = _planning_reference_date(open_date, today)
    planning_deadline = _planning_reference_date(reference_deadline, today)
    if planning_open and days_from_open is not None:
        return max(today, planning_open + timedelta(days=days_from_open))
    if planning_deadline:
        return max(today, planning_deadline - timedelta(days=days_before))
    return fallback


def _planning_reference_date(value: date | None, today: date) -> date | None:
    if value is None:
        return None
    shifted = value
    while shifted < today:
        try:
            shifted = shifted.replace(year=shifted.year + 1)
        except ValueError:
            shifted = shifted.replace(year=shifted.year + 1, day=28)
    return shifted


def _reference_basis(
    program: object,
    previous_open: date | None,
    previous_deadline: date | None,
    window_status: str | None,
) -> str:
    del program
    if previous_open and previous_deadline:
        return (
            f"当前季日期尚未发布。已按上一申请季官方窗口倒推准备动作："
            f"{previous_open.isoformat()} 至 {previous_deadline.isoformat()}。"
            "本任务用于提前准备材料；正式提交时间必须以学校当前申请季原文为准。"
        )
    if previous_deadline:
        return (
            f"当前季日期尚未发布。上一申请季参考截止为 {previous_deadline.isoformat()}，任务按该日期倒推。"
            "本任务用于提前准备材料；正式提交时间必须以学校当前申请季原文为准。"
        )
    if window_status:
        return (
            "已定位到外部官网线索，但没有完整上一申请季窗口。"
            "请打开学校项目页或申请系统确认当前申请季的开放、截止、材料和语言要求。"
        )
    return "官网当前季截止日期未发布；只生成材料准备动作，不生成正式提交日期。"


def _task(**kwargs: object) -> TimelineTask:
    task_name = kwargs["title"]
    suggested_due_date = kwargs["due_date"]
    upload_materials = kwargs.get("materials", [])
    reminder_at = max(date.today(), suggested_due_date - timedelta(days=7))
    return TimelineTask(
        **kwargs,
        task_name=task_name,
        suggested_due_date=suggested_due_date,
        upload_materials=upload_materials,
        reminder_at=reminder_at,
        data_status=DataStatus.pending_review if kwargs.get("review_required") else DataStatus.extracted,
    )
