from __future__ import annotations

from datetime import date, timedelta

from harbor_agent.models import DataStatus, ProgramMatch, TimelineTask
from harbor_agent.services.external_candidates import (
    qs_previous_cycle_deadline,
    qs_previous_cycle_open_date,
    qs_source_url_for_program,
    qs_window_status_for_program,
)


class TimelineAgent:
    name = "TimelineAgent"

    def run(self, matches: list[ProgramMatch], today: date | None = None) -> list[TimelineTask]:
        today = today or date.today()
        selected = [item for item in matches if item.tier != "not_recommended"][:5]
        if not selected:
            return []

        tasks: dict[str, TimelineTask] = {}
        shared_program_ids = [item.program.id for item in selected]
        earliest_reference = _earliest_known_deadline(selected)
        internal_start = max(today, date(today.year, 8, 15))

        tasks["source_review"] = _task(
            id="source_review",
            title="确认学校官网要求：截止日期、材料、学费、语言要求",
            due_date=internal_start,
            priority="high",
            task_type="source_review",
            linked_program_ids=shared_program_ids,
            basis="正式时间线之前必须查看学校官网、申请系统、PDF/FAQ；社区经验不能替代学校要求。",
            date_basis="人工复核",
            official_deadline=None,
            previous_cycle_reference=earliest_reference,
            materials=["official_program_page", "official_pdf_or_faq", "application_system"],
            dependencies=["刷新学校官网信息", "打开官方项目页", "记录原文摘录和页面快照"],
            status="需人工复核",
            risk_level="高",
            review_required=True,
        )
        tasks["common_transcript"] = _task(
            id="common_transcript",
            title="准备正式成绩单、在读证明和核心课程清单",
            due_date=internal_start + timedelta(days=7),
            priority="high",
            task_type="materials",
            linked_program_ids=shared_program_ids,
            basis="公共材料可先准备；项目级硬门槛需等待学校官网确认后再判断。",
            date_basis="内部准备建议",
            official_deadline=None,
            previous_cycle_reference=earliest_reference,
            materials=["transcript", "degree_certificate", "core_courses"],
            dependencies=["确认 GPA 口径", "补充排名", "标注先修课成绩"],
            status="待办",
            risk_level="中",
            review_required=True,
        )
        tasks["common_cv"] = _task(
            id="common_cv",
            title="整理通用 CV、经历证据和推荐人素材包",
            due_date=internal_start + timedelta(days=14),
            priority="high",
            task_type="materials",
            linked_program_ids=shared_program_ids,
            basis="公共材料合并维护，避免为每个项目重复创建成绩单、CV、推荐人任务。",
            date_basis="内部准备建议",
            official_deadline=None,
            previous_cycle_reference=earliest_reference,
            materials=["cv", "recommendation", "experience_proof"],
            dependencies=["完成故事卡", "确认推荐人关系", "整理量化结果"],
            status="待办",
            risk_level="中",
        )
        tasks["language_delivery"] = _task(
            id="language_delivery",
            title="语言成绩重考、出分与官方送分缓冲",
            due_date=internal_start + timedelta(days=21),
            priority="medium",
            task_type="language",
            linked_program_ids=shared_program_ids,
            basis="不同项目单项要求、是否接受后补和送分周期不同，正式判断需逐项目确认。",
            date_basis="内部准备建议",
            official_deadline=None,
            previous_cycle_reference=earliest_reference,
            materials=["language_score"],
            dependencies=["补充语言单项", "确认 IELTS/TOEFL/PTE 要求"],
            status="待办",
            risk_level="中",
            review_required=True,
        )

        for item in selected:
            program = item.program
            source_url = qs_source_url_for_program(program) or program.application_url or program.official_program_url or program.source.url
            deadline_verified = _deadline_verified(item)
            previous_deadline = qs_previous_cycle_deadline(program)
            reference = previous_deadline or (program.deadline if program.deadline != "NOT_PUBLISHED" else None)
            previous_open = qs_previous_cycle_open_date(program) if previous_deadline else None
            window_status = qs_window_status_for_program(program)
            if not deadline_verified:
                tasks[f"prepare_{program.id}"] = _task(
                    id=f"prepare_{program.id}",
                    title=f"准备建议：{program.name_zh or program.name}",
                    due_date=internal_start + timedelta(days=30),
                    priority="medium",
                    task_type="source_review",
                    linked_program_ids=[program.id],
                    basis=_reference_basis(program, previous_open, reference, window_status),
                    date_basis="上一申请季参考" if reference else "内部准备建议",
                    official_deadline="NOT_PUBLISHED",
                    previous_cycle_reference=reference,
                    source_url=source_url,
                    materials=["deadline", "materials", "language_requirement", "application_url"],
                    dependencies=["确认官方项目页", "确认申请系统", "确认是否分轮次或 rolling"],
                    status="等待官方发布",
                    risk_level="高",
                    review_required=True,
                )
                if previous_open or reference:
                    tasks[f"monitor_{program.id}"] = _task(
                        id=f"monitor_{program.id}",
                        title=f"关注申请开放窗口：{program.name_zh or program.name}",
                        due_date=max(today, _shift_previous_cycle_date(previous_open or reference, 365) - timedelta(days=21)),
                        priority="high",
                        task_type="source_review",
                        linked_program_ids=[program.id],
                        basis="根据上一申请季官网窗口提前 3 周检查学校页面。这不是当前申请季正式日期，只用于提醒你何时开始盯官网。",
                        date_basis="上一申请季参考",
                        official_deadline="NOT_PUBLISHED",
                        previous_cycle_reference=reference,
                        source_url=source_url,
                        materials=["official_program_page", "application_system"],
                        dependencies=["打开项目页", "记录申请季", "截图或保存原文"],
                        status="等待官方发布",
                        risk_level="中",
                        review_required=True,
                    )
                tasks[f"essay_prompt_{program.id}"] = _task(
                    id=f"essay_prompt_{program.id}",
                    title=f"读取文书题目与字数要求：{program.name_zh or program.name}",
                    due_date=internal_start + timedelta(days=38),
                    priority="medium",
                    task_type="writing",
                    linked_program_ids=[program.id],
                    basis="未读取项目 prompt 前，只能生成通用大纲，不能声称满足学校指定题目。",
                    date_basis="内部准备建议",
                    official_deadline="NOT_PUBLISHED",
                    previous_cycle_reference=reference,
                    source_url=source_url,
                    materials=["essay_prompts", "cv", "personal_statement"],
                    dependencies=["打开网申系统或项目 FAQ", "记录 prompt 原文", "确认字数和上传格式"],
                    status="需人工复核",
                    risk_level="中",
                    review_required=True,
                )
                continue

            assert program.deadline != "NOT_PUBLISHED"
            tasks[f"essay_{program.id}"] = _task(
                id=f"essay_{program.id}",
                title=f"完成项目定制文书：{program.name_zh or program.name}",
                due_date=max(today, program.deadline - timedelta(days=45)),
                priority="high",
                task_type="writing",
                linked_program_ids=[program.id],
                basis="按学校已确认截止日期倒推 45 天，预留项目定制、事实确认和英文润色时间。",
                date_basis="官方截止倒推",
                official_deadline=program.deadline,
                previous_cycle_reference=None,
                source_url=source_url,
                materials=["personal_statement", "cv", "essay_prompts"],
                dependencies=["故事卡已确认", "Why Program 绑定学校官网信息", "完成事实确认"],
                status="待办",
                risk_level="中",
            )
            tasks[f"final_check_{program.id}"] = _task(
                id=f"final_check_{program.id}",
                title=f"网申系统最终自查：{program.name_zh or program.name}",
                due_date=max(today, program.deadline - timedelta(days=7)),
                priority="high",
                task_type="submission",
                linked_program_ids=[program.id],
                basis="按学校已确认截止日期倒推 7 天，避免最后一周补材料和系统拥堵。",
                date_basis="官方截止倒推",
                official_deadline=program.deadline,
                source_url=source_url,
                materials=program.materials,
                dependencies=["推荐信状态", "语言送分", "网申预览 PDF", "付款状态"],
                status="待办",
                risk_level="高",
            )

        return sorted(tasks.values(), key=lambda item: item.due_date)


def _earliest_known_deadline(matches: list[ProgramMatch]) -> date | None:
    dates = [item.program.deadline for item in matches if item.program.deadline != "NOT_PUBLISHED"]
    return min(dates) if dates else None


def _deadline_verified(match: ProgramMatch) -> bool:
    return (
        match.program.deadline != "NOT_PUBLISHED"
        and match.program.data_status == DataStatus.verified
        and match.program.last_verified_at is not None
    )


def _reference_basis(
    program,
    previous_open: date | None,
    previous_deadline: date | None,
    window_status: str | None,
) -> str:
    del program
    if previous_open and previous_deadline:
        return (
            f"当前申请季尚未完成学校官网确认。GradWindow 已导入上一申请季官网窗口："
            f"{previous_open.isoformat()} 至 {previous_deadline.isoformat()}。"
            "本任务只作为准备参考，正式提交时间必须以学校当前申请季原文为准。"
        )
    if previous_deadline:
        return (
            f"当前申请季尚未完成学校官网确认。上一申请季参考截止为 {previous_deadline.isoformat()}。"
            "本任务只作为准备参考，正式提交时间必须以学校当前申请季原文为准。"
        )
    if window_status:
        return (
            "已定位到外部官网线索，但没有完整上一申请季窗口。"
            "请打开学校项目页或申请系统确认当前申请季的开放、截止、材料和语言要求。"
        )
    return "学校暂未发布当前申请季截止日期；只生成准备建议，不生成正式提交日期。"


def _shift_previous_cycle_date(value: date | None, days: int) -> date:
    return (value or date.today()) + timedelta(days=days)


def _task(**kwargs) -> TimelineTask:
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
