from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from datetime import UTC, datetime
from pathlib import Path

from harbor_agent.agents import catalog_auto_update, data_acquisition
from harbor_agent.services import data_loader, program_store
from harbor_agent.agents.catalog_auto_update import CatalogAutoUpdateAgent
from harbor_agent.agents.data_acquisition import ProgramDataAcquisitionAgent
from harbor_agent.models import CatalogAutoUpdateRequest, DataAcquisitionRequest, FieldEvidenceRecord, FieldVerificationStatus
from harbor_agent.services.program_store import init_program_store, load_field_evidence_records, load_programs_from_store, upsert_field_evidence_records
from harbor_agent.services.program_urls import has_application_entry, has_program_detail_page, is_generic_program_url


def test_program_store_schema_contains_product_fields(tmp_path) -> None:
    db_path = tmp_path / "harborpilot.sqlite3"
    init_program_store(db_path)

    with sqlite3.connect(db_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(program_catalog)").fetchall()
        }

    assert {
        "institution",
        "school",
        "program_name",
        "degree_type",
        "region",
        "direction_json",
        "duration_months",
        "tuition_hkd",
        "application_url",
        "official_program_url",
        "language_requirement_json",
        "prerequisites_json",
        "materials_json",
        "rounds_json",
        "open_date",
        "deadline",
        "essay_prompts_json",
        "source_evidence_json",
    } <= columns



    with sqlite3.connect(db_path) as conn:
        evidence_columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(program_field_evidence)").fetchall()
        }

    assert {
        "program_id",
        "field_name",
        "value",
        "cycle",
        "source_url",
        "source_type",
        "evidence_snippet",
        "agent_chain_json",
    } <= evidence_columns
def test_program_store_seeds_from_json_and_returns_programs(tmp_path) -> None:
    db_path = tmp_path / "harborpilot.sqlite3"

    programs = load_programs_from_store(
        db_path=db_path,
        seed_json_path=Path("data/programs_2027_fall.json"),
    )

    assert len(programs) >= 100
    assert programs[0].official_program_url
    assert programs[0].requirements.language

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM program_catalog").fetchone()[0]
    assert count == len(programs)


def test_application_portals_and_program_detail_pages_stay_separate(tmp_path) -> None:
    db_path = tmp_path / "harborpilot.sqlite3"
    programs = load_programs_from_store(
        db_path=db_path,
        seed_json_path=Path("data/programs_2027_fall.json"),
    )
    hku = next(program for program in programs if program.id == "hku-master-of-science-in-computer-science-2027")
    accounting = next(program for program in programs if program.id == "hku-master-of-accounting-2027")
    engineering = next(program for program in programs if program.id == "hku-master-of-science-in-engineering-2027")
    cuhk = next(program for program in programs if program.id == "cuhk-msc-in-computer-science-2027")
    cuhk_ai = next(program for program in programs if program.id == "cuhk-msc-in-artificial-intelligence-2027")
    cityu_cs = next(program for program in programs if program.id == "cityu-msc-computer-science-2027")
    cityu_bis = next(program for program in programs if program.id == "cityu-msc-business-information-systems-2027")
    nus_ba = next(program for program in programs if program.id == "nus-msc-business-analytics-2027")
    polyu_it = next(program for program in programs if program.id == "polyu-msc-information-technology-2027")
    smu_accounting = next(program for program in programs if program.id == "smu-msc-accounting-2027")
    ntu_accountancy = next(program for program in programs if program.id == "ntu-msc-accountancy-2027")
    hkust_policy = next(program for program in programs if program.id == "hkust-master-of-public-policy-2027")
    nus_public_health = next(program for program in programs if program.id == "nus-master-of-public-health-2027")
    nus_public_policy = next(program for program in programs if program.id == "nus-master-in-public-policy-2027")
    cuhk_public_policy = next(program for program in programs if program.id == "cuhk-master-of-social-science-in-public-policy-2027")
    hkust_accounting = next(program for program in programs if program.id == "hkust-msc-in-accounting-2027")
    smu_accounting_for_app = next(program for program in programs if program.id == "smu-msc-accounting-2027")
    eduhk_tesol = next(program for program in programs if program.id == "eduhk-ma-teaching-english-to-speakers-of-other-languages-2027")
    sutd_security = next(program for program in programs if program.id == "sutd-msc-security-by-design-2027")
    eduhk_stem = next(program for program in programs if program.id == "eduhk-ma-stem-education-2027")
    sutd_urban = next(program for program in programs if program.id == "sutd-msc-urban-science-policy-and-planning-2027")

    assert has_program_detail_page(hku) is True
    assert has_application_entry(hku) is True
    assert str(hku.official_program_url) != str(hku.application_url)
    assert "portal.hku.hk" in str(hku.application_url)

    assert has_program_detail_page(accounting) is True
    assert has_application_entry(accounting) is True
    assert "programme-details?programme=master-of-accounting-hkubs" in str(accounting.official_program_url)
    assert "portal.hku.hk" in str(accounting.application_url)
    assert str(accounting.official_program_url) != str(accounting.application_url)

    assert has_program_detail_page(engineering) is True
    assert has_application_entry(engineering) is True
    assert "programme-details?programme=master-of-science-in-engineering-engg" in str(engineering.official_program_url)

    assert has_application_entry(cuhk) is True
    assert "OnlineApp" in str(cuhk.application_url)

    assert has_program_detail_page(cityu_cs) is True
    assert has_program_detail_page(cityu_bis) is True
    assert "cityu.edu.hk/pg/programme/p05a" in str(cityu_bis.official_program_url)
    assert has_program_detail_page(nus_ba) is True
    assert has_program_detail_page(polyu_it) is True
    polyu_ba = next(program for program in programs if program.id == "polyu-msc-business-analytics-2027")
    polyu_ai = next(program for program in programs if program.id == "polyu-msc-artificial-intelligence-and-big-data-computing-2027")
    polyu_design = next(program for program in programs if program.id == "polyu-master-of-design-2027")
    assert has_program_detail_page(polyu_ba) is True
    assert "study/pg/tpg/2027/23090-maf-map" in str(polyu_ba.official_program_url)
    assert has_program_detail_page(polyu_ai) is True
    assert "study/pg/tpg/2027/62037-fai-pai" in str(polyu_ai.official_program_url)
    assert has_program_detail_page(polyu_design) is True
    assert "study/pg/tpg/2027/73035" in str(polyu_design.official_program_url)
    assert has_program_detail_page(smu_accounting) is True
    assert "masters.smu.edu.sg/programmes/msc-accounting" in str(smu_accounting.official_program_url)
    assert has_program_detail_page(ntu_accountancy) is True
    assert "admissions/graduate-studies/msc-accountancy" in str(ntu_accountancy.official_program_url)
    assert has_program_detail_page(hkust_policy) is True
    assert "pgprog/2026-27/mpp" in str(hkust_policy.official_program_url)
    assert has_program_detail_page(nus_public_health) is True
    assert "sph.nus.edu.sg/education/graduate-programmes/master-of-public-health" in str(nus_public_health.official_program_url)
    assert has_program_detail_page(nus_public_policy) is True
    assert "lkyspp.nus.edu.sg/graduate-programmes/master-in-public-policy-mpp" in str(nus_public_policy.official_program_url)
    assert has_program_detail_page(cuhk_public_policy) is True
    assert "gs.cuhk.edu.hk/programmes/social-science/msSc-public-policy" in str(cuhk_public_policy.official_program_url)
    assert has_application_entry(hkust_accounting) is True
    assert "w5.ab.ust.hk" in str(hkust_accounting.application_url)
    assert has_application_entry(smu_accounting_for_app) is True
    assert "admissions.smu.edu.sg/apply/graduate" in str(smu_accounting_for_app.application_url)
    assert has_application_entry(eduhk_tesol) is True
    assert "eduhk.hk/acadprog/online" in str(eduhk_tesol.application_url)
    assert has_application_entry(sutd_security) is True
    assert "admission.sutd.edu.sg" in str(sutd_security.application_url)
    assert has_program_detail_page(eduhk_stem) is True
    assert "mastem.eduhk.hk" in str(eduhk_stem.official_program_url)
    assert has_program_detail_page(sutd_urban) is True
    assert "programme-listing/muspp" in str(sutd_urban.official_program_url)


def test_verified_program_detail_page_coverage_does_not_regress(tmp_path) -> None:
    db_path = tmp_path / "harborpilot.sqlite3"
    programs = load_programs_from_store(
        db_path=db_path,
        seed_json_path=Path("data/programs_2027_fall.json"),
    )

    assert sum(has_program_detail_page(program) for program in programs) >= 127
    assert sum(has_application_entry(program) for program in programs) >= 142
    engineering = next(program for program in programs if program.id == "hku-master-of-science-in-engineering-2027")
    architecture = next(program for program in programs if program.id == "hku-master-of-architecture-2027")
    urban_planning = next(program for program in programs if program.id == "hku-master-of-urban-planning-2027")
    public_policy = next(program for program in programs if program.id == "hku-master-of-public-policy-2027")
    ntu_project_management = next(program for program in programs if program.id == "ntu-msc-project-management-2027")
    hkbu_education = next(program for program in programs if program.id == "hkbu-master-of-education-2027")
    hkbu_itm = next(program for program in programs if program.id == "hkbu-msc-information-technology-management-2027")
    hkbu_daai = next(program for program in programs if program.id == "hkbu-msc-data-analytics-and-artificial-intelligence-2027")
    hkbu_aaf = next(program for program in programs if program.id == "hkbu-msc-applied-accounting-and-finance-2027")
    hkbu_bm = next(program for program in programs if program.id == "hkbu-msc-business-management-2027")
    hkbu_cgc = next(program for program in programs if program.id == "hkbu-msc-corporate-governance-and-compliance-2027")
    cuhk_applied_english = next(program for program in programs if program.id == "cuhk-ma-in-applied-english-linguistics-2027")
    lingnan_aiba = next(program for program in programs if program.id == "lingnan-msc-artificial-intelligence-and-business-analytics-2027")
    lingnan_finance = next(program for program in programs if program.id == "lingnan-msc-finance-2027")
    lingnan_hrom = next(program for program in programs if program.id == "lingnan-msc-human-resource-management-and-organisational-behaviour-2027")
    lingnan_mib = next(program for program in programs if program.id == "lingnan-msc-marketing-and-international-business-2027")
    lingnan_ebusiness = next(program for program in programs if program.id == "lingnan-msc-ebusiness-and-supply-chain-management-2027")
    lingnan_data_science = next(program for program in programs if program.id == "lingnan-msc-data-science-2027")
    lingnan_creative_media = next(program for program in programs if program.id == "lingnan-ma-creative-and-media-industries-2027")
    lingnan_translation = next(program for program in programs if program.id == "lingnan-ma-translation-studies-2027")
    lingnan_international_affairs = next(program for program in programs if program.id == "lingnan-ma-international-affairs-2027")
    nus_marketing = next(program for program in programs if program.id == "nus-msc-marketing-analytics-and-insights-2027")
    sutd_technology_design = next(program for program in programs if program.id == "sutd-msc-technology-and-design-2027")
    assert has_program_detail_page(engineering) is True
    assert has_program_detail_page(architecture) is True
    assert has_program_detail_page(urban_planning) is True
    assert has_program_detail_page(public_policy) is True
    assert has_program_detail_page(ntu_project_management) is True
    assert "master-of-science-in-project-management" in str(ntu_project_management.official_program_url).lower()
    assert has_program_detail_page(hkbu_education) is True
    assert "educ.hkbu.edu.hk/?page_id=20282" in str(hkbu_education.official_program_url)
    assert has_program_detail_page(hkbu_itm) is True
    assert "page=msc_itm" in str(hkbu_itm.official_program_url)
    assert has_program_detail_page(hkbu_daai) is True
    assert "page=msc_daai" in str(hkbu_daai.official_program_url)
    assert has_program_detail_page(cuhk_applied_english) is True
    assert "ma-english-applied-english-linguistics" in str(cuhk_applied_english.official_program_url)
    assert has_program_detail_page(lingnan_aiba) is True
    assert "sds/dai/mscaiba" in str(lingnan_aiba.official_program_url)
    assert has_program_detail_page(lingnan_finance) is True
    assert "academic-programmes/mfin" in str(lingnan_finance.official_program_url)
    assert has_program_detail_page(lingnan_hrom) is True
    assert "academic-programmes/mschrom" in str(lingnan_hrom.official_program_url)
    assert has_program_detail_page(lingnan_mib) is True
    assert "academic-programmes/mscmib" in str(lingnan_mib.official_program_url)
    assert has_program_detail_page(lingnan_ebusiness) is True
    assert "academic-programmes/mscebscm" in str(lingnan_ebusiness.official_program_url)
    assert has_program_detail_page(lingnan_data_science) is True
    assert "sds/dai/mscds" in str(lingnan_data_science.official_program_url)
    assert has_program_detail_page(lingnan_creative_media) is True
    assert "daci/macmi" in str(lingnan_creative_media.official_program_url)
    assert has_program_detail_page(lingnan_translation) is True
    assert "tran/programmes/mats" in str(lingnan_translation.official_program_url)
    assert has_program_detail_page(lingnan_international_affairs) is True
    assert "gia/maia" in str(lingnan_international_affairs.official_program_url)
    assert has_program_detail_page(nus_marketing) is True
    assert "mscmarketing.nus.edu.sg" in str(nus_marketing.official_program_url)
    assert has_program_detail_page(sutd_technology_design) is True
    assert "master-of-science-in-technology-and-design" in str(sutd_technology_design.official_program_url)

def test_program_store_persists_field_level_evidence(tmp_path) -> None:
    db_path = tmp_path / "harborpilot.sqlite3"
    record = FieldEvidenceRecord(
        program_id="hku-test-program",
        field_name="deadline",
        value="2026-12-01",
        cycle="2027-fall",
        source_url="https://example.edu/program",
        source_type="official_program_page",
        extracted_at=datetime.now(UTC),
        page_hash="sha256:test",
        confidence="medium",
        source_priority=2,
        status=FieldVerificationStatus.official_previous_cycle,
        review_required=True,
        evidence_snippet="Application deadline: 1 Dec 2026",
        snapshot_url="https://example.edu/program",
        agent_chain=["SourceDiscoveryAgent", "FieldExtractionAgent", "HumanReviewGateAgent"],
    )

    assert upsert_field_evidence_records([record], db_path=db_path) == 1
    loaded = load_field_evidence_records(["hku-test-program"], db_path=db_path)

    assert len(loaded) == 1
    assert loaded[0].program_id == record.program_id
    assert loaded[0].field_name == "deadline"
    assert loaded[0].status == FieldVerificationStatus.official_previous_cycle
    assert loaded[0].review_required is True
    assert loaded[0].agent_chain[-1] == "HumanReviewGateAgent"


def test_program_store_writes_clear_data_loader_cache(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "harborpilot.sqlite3"
    calls: list[str] = []

    monkeypatch.setattr(program_store, "_clear_data_loader_caches_after_write", lambda: calls.append("cleared"))

    programs = load_programs_from_store(
        db_path=db_path,
        seed_json_path=Path("data/programs_2027_fall.json"),
    )[:1]
    calls.clear()

    assert program_store.seed_program_store(programs, db_path=db_path, replace=True) == 1

    record = FieldEvidenceRecord(
        program_id=programs[0].id,
        field_name="deadline",
        value="2026-12-01",
        cycle="2027-fall",
        source_url="https://example.edu/program",
        source_type="official_program_page",
        extracted_at=datetime.now(UTC),
        page_hash="sha256:test-cache",
        confidence="high",
        source_priority=1,
        status=FieldVerificationStatus.official_verified_current,
        review_required=False,
        evidence_snippet="Application deadline: 1 Dec 2026",
        snapshot_url="https://example.edu/program",
        agent_chain=["DataAcquisitionAgent", "HumanReviewGateAgent"],
    )
    assert program_store.upsert_field_evidence_records([record], db_path=db_path) == 1
    assert calls == ["cleared", "cleared"]


def test_load_programs_cache_invalidates_when_store_file_changes_without_explicit_clear(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "harborpilot.sqlite3"
    seed = load_programs_from_store(seed_json_path=Path("data/programs_2027_fall.json"))[:2]

    program_store.seed_program_store(seed[:1], db_path=db_path, replace=True)
    monkeypatch.setattr(data_loader, "PROGRAM_DB_PATH", db_path)
    monkeypatch.setattr(data_loader, "PROGRAM_JSON", Path("data/programs_2027_fall.json"))
    monkeypatch.setattr(data_loader, "PROGRAM_URL_OVERRIDES", Path("data/program_url_overrides.json"))
    data_loader.clear_data_loader_caches()

    first = data_loader.load_programs()
    assert [program.id for program in first] == [seed[0].id]

    monkeypatch.setattr(program_store, "_clear_data_loader_caches_after_write", lambda: None)
    program_store.seed_program_store(seed, db_path=db_path, replace=True)

    second = data_loader.load_programs()
    assert [program.id for program in second] == [program.id for program in seed]


def test_catalog_replace_preserves_review_evidence(tmp_path) -> None:
    db_path = tmp_path / "harborpilot.sqlite3"
    seed = load_programs_from_store(seed_json_path=Path("data/programs_2027_fall.json"))[:2]
    program_store.seed_program_store(seed[:1], db_path=db_path, replace=True)
    record = FieldEvidenceRecord(
        program_id=seed[0].id,
        field_name="deadline",
        value="2027-01-15",
        cycle="2027-fall",
        source_url="https://example.edu/programme",
        source_type="official_program_page",
        extracted_at=datetime.now(UTC),
        page_hash="sha256:preserve-review",
        confidence="high",
        source_priority=1,
        status=FieldVerificationStatus.official_verified_current,
        review_required=False,
        reviewer_id="reviewer-test",
        agent_chain=["HumanReviewGateAgent"],
    )
    upsert_field_evidence_records([record], db_path=db_path)

    program_store.seed_program_store(seed, db_path=db_path, replace=True)

    loaded = load_field_evidence_records([seed[0].id], db_path=db_path)
    assert len(loaded) == 1
    assert loaded[0].reviewer_id == "reviewer-test"
def test_data_acquisition_live_mode_persists_field_candidates(monkeypatch) -> None:
    captured: list[FieldEvidenceRecord] = []

    def fake_upsert(records):
        captured.extend(records)
        return len(records)

    monkeypatch.setattr(data_acquisition, "upsert_field_evidence_records", fake_upsert)
    report = ProgramDataAcquisitionAgent().run(
        DataAcquisitionRequest(
            selected_program_ids=["hku-master-of-science-in-computer-science-2027"],
            dry_run=False,
            include_community=False,
        )
    )

    assert report.mode == "live_fetch"
    assert captured
    assert any(record.field_name == "deadline" for record in captured)
    assert "SQLite" in report.summary
    assert "HumanReviewGateAgent" in report.agent_chain

def test_catalog_auto_update_live_mode_persists_url_candidates_for_review(monkeypatch) -> None:
    captured: list[FieldEvidenceRecord] = []

    def fake_upsert(records):
        captured.extend(records)
        return len(records)

    monkeypatch.setattr(catalog_auto_update, "upsert_field_evidence_records", fake_upsert)
    monkeypatch.setattr(catalog_auto_update, "build_review_queue", lambda limit=1: SimpleNamespace(pending_count=len(captured)))

    report = CatalogAutoUpdateAgent().run(
        CatalogAutoUpdateRequest(
            selected_program_ids=["cityu-msc-electronic-information-engineering-2027"],
            dry_run=False,
            max_programs=1,
        )
    )

    assert report.mode == "live_fetch"
    assert report.candidate_count == 1
    assert report.persisted_candidate_count == 1
    assert captured
    record = captured[0]
    assert record.program_id == "cityu-msc-electronic-information-engineering-2027"
    assert record.field_name == "official_program_url"
    assert str(record.value) == "https://www.cityu.edu.hk/pg/programme/p59"
    assert record.status == FieldVerificationStatus.conflicted
    assert record.review_required is True
    assert "HumanReviewGateAgent" in record.agent_chain
    assert "program_url_overrides" not in report.summary
