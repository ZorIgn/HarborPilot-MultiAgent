from dataclasses import replace
from datetime import UTC, datetime, timedelta

from harbor_agent.services import data_acquisition
from harbor_agent.models import (
    AcquisitionSourcePlan,
    DataQualityMetric,
    FieldEvidenceRecord,
    FieldVerificationStatus,
    ProgramDataPackage,
    SourceCategory,
    SourceHealthSummary,
    SourcePolicy,
    SourceScope,
    SourceTrustLevel,
    ReviewQueueItem,
)
from harbor_agent.services.information_store import (
    finish_information_run,
    record_fetch_attempt,
    source_health_summary,
    start_information_run,
)
from harbor_agent.services.source_snapshot import SnapshotResult, extract_field_candidates
from harbor_agent.services.review_gate import _validate_confirmed_value
from harbor_agent.services.program_store import upsert_field_evidence_records


def _package(plan: AcquisitionSourcePlan, name: str = "MSc Data Science") -> ProgramDataPackage:
    return ProgramDataPackage(
        program_id="demo-data-science-2027",
        institution="Demo University",
        program_name=name,
        cycle="2027-fall",
        official_url=plan.url,
        application_url=None,
        production_ready=False,
        freshness_warning="待核验",
        acquisition_plan=[plan],
        quality_metric=DataQualityMetric(
            scope="demo-data-science-2027",
            official_field_coverage=0,
            verified_current_coverage=0,
        ),
    )


def _snapshot(
    html: str,
    *,
    url: str = "https://demo.edu/programmes",
    page_title: str = "Demo University programmes",
) -> SnapshotResult:
    checked = datetime.now(UTC)
    return SnapshotResult(
        ok=True,
        url=url,
        final_url=url,
        status="FETCH_OK",
        checked_at=checked,
        http_status=200,
        page_hash="sha256:test-page",
        snapshot_path="data/source_snapshots/test.html",
        snapshot_mime="text/html",
        content_bytes=len(html.encode()),
        text=" ".join(html.replace("<", " <").split()),
        html=html,
        page_title=page_title,
        attempts=1,
        duration_ms=12,
    )


def test_institution_index_discovers_then_fetches_bound_detail_page(monkeypatch) -> None:
    plan = AcquisitionSourcePlan(
        source_id="demo-index",
        name="Demo programme index",
        url="https://demo.edu/programmes",
        channel="official_requirement",
        trust_level=SourceTrustLevel.official,
        allowed_fields=["official_program_url"],
        crawler_method="html",
        source_scope=SourceScope.institution_index,
        target_program_id="demo-data-science-2027",
    )
    package = _package(plan)
    html = (
        "<html><title>Demo University programmes</title><body>"
        "<a href='/msc-data-science'>MSc Data Science</a>"
        "<p>Application deadline: 31 January 2027; tuition HK$200000</p>"
        "</body></html>"
    )
    detail_html = (
        "<html><title>MSc Data Science</title><body>"
        "<h1>MSc Data Science</h1><p>Application deadline: 31 January 2027; tuition HK$200000</p>"
        "</body></html>"
    )

    def fake_snapshot(url, **kwargs):
        if str(url).endswith("/msc-data-science"):
            return _snapshot(detail_html, url=str(url), page_title="MSc Data Science")
        return _snapshot(html, url=str(url))

    monkeypatch.setattr(data_acquisition, "snapshot_source", fake_snapshot)
    monkeypatch.setattr(data_acquisition, "record_fetch_attempt", lambda *args, **kwargs: None)

    records, results, stats, warnings = data_acquisition._run_live_snapshot_pipeline_with_run(
        [package], datetime.now(UTC), "test_run"
    )

    index_records = [record for record in records if record.source_scope == SourceScope.institution_index]
    detail_records = [record for record in records if record.source_scope == SourceScope.programme_detail]
    assert [record.field_name for record in index_records] == ["official_program_url"]
    assert {"official_program_url", "deadline", "tuition_hkd"} <= {
        record.field_name for record in detail_records
    }
    assert results[0].binding_status == "index_only"
    assert results[0].extracted_fields == []
    assert results[1].binding_status == "matched"
    assert stats["successful"] == 2
    assert warnings == []


def test_program_binding_gate_rejects_unrelated_detail_page(monkeypatch) -> None:
    plan = AcquisitionSourcePlan(
        source_id="demo-detail",
        name="Demo programme detail",
        url="https://demo.edu/msc-data-science",
        channel="official_requirement",
        trust_level=SourceTrustLevel.official,
        allowed_fields=["deadline", "tuition_hkd"],
        crawler_method="html",
        source_scope=SourceScope.programme_detail,
        target_program_id="demo-data-science-2027",
    )
    package = _package(plan)
    html = "<html><title>MSc Accounting</title><body>Application deadline: 31 January 2027</body></html>"
    monkeypatch.setattr(data_acquisition, "snapshot_source", lambda *args, **kwargs: _snapshot(html, url=str(plan.url)))
    monkeypatch.setattr(data_acquisition, "record_fetch_attempt", lambda *args, **kwargs: None)

    records, results, stats, warnings = data_acquisition._run_live_snapshot_pipeline_with_run(
        [package], datetime.now(UTC), "test_run"
    )

    assert records == []
    assert results[0].binding_status == "unrelated"
    assert stats["binding_warnings"] == 1
    assert warnings


def test_program_binding_gate_rejects_undergraduate_page_for_masters_target() -> None:
    plan = AcquisitionSourcePlan(
        source_id="demo-detail",
        name="Demo programme detail",
        url="https://demo.edu/bsc-computer-science",
        channel="official_requirement",
        trust_level=SourceTrustLevel.official,
        allowed_fields=["deadline"],
        crawler_method="html",
        source_scope=SourceScope.programme_detail,
        target_program_id="demo-computer-science-2027",
    )
    package = _package(plan, name="MSc Computer Science")
    snapshot = _snapshot(
        "<html><title>BSc Computer Science</title><body>Bachelor undergraduate Computer Science</body></html>",
        url=str(plan.url),
        page_title="BSc Computer Science",
    )

    status, score = data_acquisition._bind_program_page(package, snapshot)

    assert status == "unrelated"
    assert score == 0


def test_program_binding_gate_rejects_same_name_from_another_university() -> None:
    plan = AcquisitionSourcePlan(
        source_id="hku-detail",
        name="HKU programme detail",
        url="https://admissions.hku.hk/tpg/msc-data-science",
        channel="official_requirement",
        trust_level=SourceTrustLevel.official,
        allowed_fields=["deadline"],
        crawler_method="html",
        source_scope=SourceScope.programme_detail,
        target_program_id="hku-data-science-2027",
    )
    package = _package(plan, name="MSc Data Science")
    snapshot = _snapshot(
        "<html><title>MSc Data Science</title><body>Master of Science in Data Science</body></html>",
        url="https://www.nus.edu.sg/graduate/msc-data-science",
        page_title="MSc Data Science",
    )

    status, score = data_acquisition._bind_program_page(package, snapshot)

    assert status == "unrelated"
    assert score == 0


def test_non_hkd_tuition_never_enters_hkd_field() -> None:
    candidates = extract_field_candidates("Tuition fee SGD 60,000 for the full programme.")

    assert any(item.field_name == "tuition_original" and item.value == "SGD 60,000" for item in candidates)
    assert not any(item.field_name == "tuition_hkd" for item in candidates)


def test_shared_institution_index_is_fetched_once_for_multiple_programmes(monkeypatch) -> None:
    first_plan = AcquisitionSourcePlan(
        source_id="demo-index",
        name="Demo programme index",
        url="https://demo.edu/programmes",
        channel="official_requirement",
        trust_level=SourceTrustLevel.official,
        allowed_fields=["official_program_url"],
        crawler_method="html",
        source_scope=SourceScope.institution_index,
        target_program_id="demo-data-science-2027",
    )
    second_plan = first_plan.model_copy(update={"target_program_id": "demo-accounting-2027"})
    first = _package(first_plan)
    second = ProgramDataPackage(
        program_id="demo-accounting-2027",
        institution="Demo University",
        program_name="MSc Accounting",
        cycle="2027-fall",
        official_url=second_plan.url,
        application_url=None,
        production_ready=False,
        freshness_warning="待核验",
        acquisition_plan=[second_plan],
    )
    html = (
        "<html><title>Demo University programmes</title><body>"
        "<a href='/msc-data-science'>MSc Data Science</a>"
        "<a href='/msc-accounting'>MSc Accounting</a>"
        "</body></html>"
    )
    calls = []
    def fake_snapshot(url, **kwargs):
        calls.append(str(url))
        if str(url).endswith("/msc-data-science"):
            return _snapshot(
                "<html><title>MSc Data Science</title><body><h1>MSc Data Science</h1></body></html>",
                url=str(url),
                page_title="MSc Data Science",
            )
        if str(url).endswith("/msc-accounting"):
            return _snapshot(
                "<html><title>MSc Accounting</title><body><h1>MSc Accounting</h1></body></html>",
                url=str(url),
                page_title="MSc Accounting",
            )
        return _snapshot(html, url=str(url))

    monkeypatch.setattr(data_acquisition, "snapshot_source", fake_snapshot)
    monkeypatch.setattr(data_acquisition, "record_fetch_attempt", lambda *args, **kwargs: None)

    records, _, stats, _ = data_acquisition._run_live_snapshot_pipeline_with_run(
        [first, second], datetime.now(UTC), "test_run"
    )

    assert calls.count("https://demo.edu/programmes") == 1
    assert len(calls) == 3
    assert stats["attempted"] == 3
    assert {record.program_id for record in records} == {"demo-data-science-2027", "demo-accounting-2027"}
    assert {record.field_name for record in records} == {"official_program_url"}


def test_confirmed_value_is_revalidated_before_publish() -> None:
    item = ReviewQueueItem(
        review_id="review-demo",
        program_id="demo",
        field_name="deadline",
        proposed_value="2027-03-20",
        cycle="2027-fall",
        source_url="https://demo.edu/programme",
        source_type="official_program_page",
    )
    assert _validate_confirmed_value(item, "2026-03-20") is not None
    assert _validate_confirmed_value(item, "2027-03-20") is None

    tuition = item.model_copy(
        update={
            "field_name": "tuition_hkd",
            "proposed_value": "HKD 200,000",
        }
    )
    assert _validate_confirmed_value(tuition, "SGD 60,000") is not None
    assert _validate_confirmed_value(tuition, "HKD 200,000") is None


def test_source_health_tracks_attempts_and_freshness(tmp_path) -> None:
    db_path = tmp_path / "information.sqlite3"
    source = SourcePolicy(
        source_id="demo-source",
        name="Demo official page",
        url="https://demo.edu/programmes",
        category=SourceCategory.official_program_index,
        region="GLOBAL",
        trust_level=SourceTrustLevel.official,
        refresh_cadence="daily",
        extraction_method="html",
    )
    checked = datetime(2027, 1, 2, tzinfo=UTC)
    run_id = "health-test-run"
    start_information_run(run_id, mode="live_fetch", selected_program_ids=["demo"], planned_source_count=1, db_path=db_path)
    record_fetch_attempt(
        run_id,
        program_id="demo",
        source_id=source.source_id,
        source_scope=SourceScope.institution_index,
        requested_url=str(source.url),
        snapshot=_snapshot("<html><title>Demo</title></html>"),
        db_path=db_path,
    )
    finish_information_run(
        run_id,
        status="COMPLETED",
        attempted_source_count=1,
        successful_source_count=1,
        failed_source_count=0,
        db_path=db_path,
    )

    # Use the persisted timestamp from the attempt as the reference window.
    summary: SourceHealthSummary = source_health_summary(
        [source],
        now=datetime.now(UTC) + timedelta(seconds=1),
        db_path=db_path,
    )
    assert summary.total_sources == 1
    assert summary.items[0].attempt_count == 1
    assert summary.items[0].success_count == 1
    assert summary.items[0].freshness_state == "fresh"
    assert summary.items[0].failure_rate == 0


def test_source_health_latest_failure_is_not_healthy_and_dynamic_details_are_visible(tmp_path) -> None:
    db_path = tmp_path / "information.sqlite3"
    source = SourcePolicy(
        source_id="demo-index",
        name="Demo index",
        url="https://demo.edu/programmes",
        category=SourceCategory.official_program_index,
        region="GLOBAL",
        trust_level=SourceTrustLevel.official,
        refresh_cadence="daily",
        extraction_method="html",
    )
    start_information_run(
        "health-failure-run",
        mode="live_fetch",
        selected_program_ids=["demo"],
        planned_source_count=2,
        db_path=db_path,
    )
    success = _snapshot("<html>index</html>")
    record_fetch_attempt(
        "health-failure-run",
        program_id=None,
        source_id=source.source_id,
        source_scope=SourceScope.institution_index,
        requested_url=str(source.url),
        snapshot=success,
        db_path=db_path,
    )
    failed = replace(
        success,
        ok=False,
        status="FETCH_FAILED",
        checked_at=success.checked_at + timedelta(seconds=2),
        http_status=None,
        error="timeout",
    )
    record_fetch_attempt(
        "health-failure-run",
        program_id=None,
        source_id=source.source_id,
        source_scope=SourceScope.institution_index,
        requested_url=str(source.url),
        snapshot=failed,
        db_path=db_path,
    )
    detail = replace(
        success,
        url="https://demo.edu/msc-data-science",
        final_url="https://demo.edu/msc-data-science",
        checked_at=success.checked_at + timedelta(seconds=3),
    )
    record_fetch_attempt(
        "health-failure-run",
        program_id="demo",
        source_id="program:demo:detail",
        source_scope=SourceScope.programme_detail,
        requested_url=detail.url,
        snapshot=detail,
        binding_status="matched",
        binding_score=90,
        db_path=db_path,
    )

    summary = source_health_summary(
        [source],
        now=success.checked_at + timedelta(seconds=4),
        db_path=db_path,
    )

    assert summary.total_sources == 2
    assert summary.healthy_sources == 1
    assert summary.failing_sources == 1
    assert summary.stale_sources == 1
    dynamic = next(item for item in summary.items if item.source_id == "program:demo:detail")
    assert dynamic.source_scope == SourceScope.programme_detail
    assert dynamic.last_status == "FETCH_OK"


def test_source_health_global_review_count_is_not_duplicated_by_category(tmp_path) -> None:
    db_path = tmp_path / "information.sqlite3"
    sources = [
        SourcePolicy(
            source_id=f"demo-source-{index}",
            name=f"Demo source {index}",
            url=f"https://demo.edu/programmes/{index}",
            category=SourceCategory.official_program_index,
            region="GLOBAL",
            trust_level=SourceTrustLevel.official,
            refresh_cadence="daily",
            extraction_method="html",
        )
        for index in (1, 2)
    ]
    upsert_field_evidence_records(
        [
            FieldEvidenceRecord(
                program_id="demo",
                field_name="official_program_url",
                value="https://demo.edu/programme/demo",
                cycle="2027-fall",
                source_url="https://demo.edu/programmes",
                source_type=SourceCategory.official_program_index.value,
                extracted_at=datetime.now(UTC),
                page_hash="sha256:pending-one",
                confidence="medium",
                source_priority=2,
                status=FieldVerificationStatus.model_inferred,
                review_required=True,
                execution_ref=None,
            )
        ],
        db_path=db_path,
    )

    summary = source_health_summary(sources, db_path=db_path)

    assert summary.pending_review_count == 1
