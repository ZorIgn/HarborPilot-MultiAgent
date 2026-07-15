from __future__ import annotations

import sqlite3
from fastapi.testclient import TestClient

from harbor_agent import app as app_module
from harbor_agent.models import ApplicantProfileInput
from harbor_agent.services.profile_store import load_profile, load_workspace_state, save_profile, save_workspace_state


def _profile() -> ApplicantProfileInput:
    return ApplicantProfileInput.model_validate(
        {
            "target_regions": ["HK", "SG"],
            "target_cycle": "2027-fall",
            "target_degree": "taught_master",
            "discipline_interests": ["data_science"],
            "raw_interest_text": "database, machine learning",
            "education": {
                "school": "Demo University",
                "school_tier": "211",
                "major": "Information Systems",
                "gpa": 87,
                "gpa_scale": "100",
            },
            "language": {"test": "IELTS", "overall": 7, "writing": 6.5},
            "experiences": [],
            "budget_hkd": 320000,
            "career_goal": "analytics product role",
            "risk_flags": [],
        }
    )


def test_profile_store_roundtrip_uses_sqlite(tmp_path) -> None:
    db_path = tmp_path / "profiles.sqlite3"
    saved = save_profile(_profile(), db_path=db_path)

    loaded = load_profile(db_path=db_path)

    assert loaded is not None
    assert loaded.education.school == saved.education.school
    assert loaded.discipline_interests == ["data_science"]


def test_local_profile_api_contract(monkeypatch) -> None:
    stored = {"profile": _profile()}

    monkeypatch.setattr(app_module, "load_profile", lambda: stored["profile"])
    monkeypatch.setattr(app_module, "save_profile", lambda payload: stored.update(profile=payload) or payload)

    client = TestClient(app_module.app)
    response = client.get("/api/profile/local")
    assert response.status_code == 200
    assert response.json()["education"]["school"] == "Demo University"

    payload = response.json()
    payload["education"]["school"] = "Updated University"
    put_response = client.put("/api/profile/local", json=payload)
    assert put_response.status_code == 200
    assert stored["profile"].education.school == "Updated University"


def test_workspace_state_roundtrip_uses_sqlite(tmp_path) -> None:
    db_path = tmp_path / "workspace.sqlite3"
    saved = save_workspace_state(
        selected_program_ids=["hku-master-of-science-in-computer-science-2027", "hku-master-of-science-in-computer-science-2027"],
        questionnaire_values={"opening_motivation": "I want to connect analytics with product decisions."},
        result_snapshot={"workflow_id": "wf_test", "timeline": []},
        program_scheme={
            "band_overrides": {"hku-master-of-science-in-computer-science-2027": "target"},
            "removed_program_ids": ["removed-1", "removed-1"],
            "extra_candidate_ids": ["extra-1"],
        },
        writing_draft_history=[{
            "id": "draft-1",
            "createdAt": "2026-07-07T00:00:00Z",
            "title": "NUS PS draft",
            "documentType": "PS",
            "targetProgram": "NUS MSc",
            "factCount": 4,
            "gapCount": 1,
            "wordCount": 620,
        }],
        db_path=db_path,
    )
    loaded = load_workspace_state(db_path=db_path)

    assert saved["selected_program_ids"] == ["hku-master-of-science-in-computer-science-2027"]
    assert loaded["questionnaire_values"]["opening_motivation"].startswith("I want")
    assert loaded["result_snapshot"]["workflow_id"] == "wf_test"
    assert loaded["field_sensitivity"]["questionnaire_values"] == "sensitive_writing_material"
    assert loaded["program_scheme"]["band_overrides"]["hku-master-of-science-in-computer-science-2027"] == "target"
    assert loaded["program_scheme"]["removed_program_ids"] == ["removed-1"]
    assert loaded["program_scheme"]["extra_candidate_ids"] == ["extra-1"]
    assert loaded["writing_draft_history"][0]["title"] == "NUS PS draft"
    assert loaded["field_sensitivity"]["writing_draft_history"] == "derived_writing_work"



def test_profile_store_does_not_persist_sensitive_payload_as_plaintext(tmp_path) -> None:
    db_path = tmp_path / "profiles.sqlite3"
    save_profile(_profile(), profile_id="student_secure", db_path=db_path)
    save_workspace_state(
        selected_program_ids=["hku-master-of-science-in-computer-science-2027"],
        questionnaire_values={"career_plan": "private analytics goal"},
        result_snapshot={"workflow_id": "wf_private"},
        writing_draft_history=[{"id": "draft-private", "title": "private draft title"}],
        profile_id="student_secure",
        db_path=db_path,
    )

    with sqlite3.connect(db_path) as conn:
        profile_payload = conn.execute("SELECT payload_json FROM student_profiles WHERE profile_id = ?", ("student_secure",)).fetchone()[0]
        workspace_row = conn.execute(
            """
            SELECT questionnaire_values_json, result_snapshot_json, writing_draft_history_json
            FROM student_workspace_state
            WHERE profile_id = ?
            """,
            ("student_secure",),
        ).fetchone()

    assert profile_payload.startswith("hp1:")
    assert "Demo University" not in profile_payload
    assert workspace_row[0].startswith("hp1:")
    assert "private analytics goal" not in workspace_row[0]
    assert workspace_row[1].startswith("hp1:")
    assert "wf_private" not in workspace_row[1]
    assert workspace_row[2].startswith("hp1:")
    assert "private draft title" not in workspace_row[2]


def test_profile_store_rejects_tampered_protected_payload(tmp_path) -> None:
    db_path = tmp_path / "profiles.sqlite3"
    save_profile(_profile(), profile_id="student_secure", db_path=db_path)

    with sqlite3.connect(db_path) as conn:
        stored = conn.execute("SELECT payload_json FROM student_profiles WHERE profile_id = ?", ("student_secure",)).fetchone()[0]
        tampered = stored[:-2] + ("AA" if not stored.endswith("AA") else "BB")
        conn.execute("UPDATE student_profiles SET payload_json = ? WHERE profile_id = ?", (tampered, "student_secure"))
        conn.commit()

    try:
        load_profile(profile_id="student_secure", db_path=db_path)
    except ValueError as exc:
        assert "integrity" in str(exc)
    else:
        raise AssertionError("tampered profile payload should fail integrity check")
def test_profile_field_sensitivity_covers_profile_sections(tmp_path) -> None:
    db_path = tmp_path / "workspace.sqlite3"
    state = save_workspace_state(
        selected_program_ids=[],
        questionnaire_values={},
        result_snapshot=None,
        db_path=db_path,
    )

    sensitivity = state["field_sensitivity"]
    assert sensitivity["profile.personal_info"] == "sensitive_personal_context"
    assert sensitivity["profile.education"] == "academic_record"
    assert sensitivity["profile.language"] == "academic_record"
    assert sensitivity["profile.additional_background"] == "application_material"


def test_local_workspace_api_contract(monkeypatch) -> None:
    stored = {
        "selected_program_ids": ["hku-master-of-science-in-computer-science-2027"],
        "questionnaire_values": {"career_plan": "analytics"},
        "result_snapshot": {"workflow_id": "wf_initial"},
        "field_sensitivity": {"questionnaire_values": "sensitive_writing_material"},
        "writing_draft_history": [{"id": "draft-api", "title": "API draft"}],
        "program_scheme": {},
    }

    monkeypatch.setattr(app_module, "load_workspace_state", lambda: stored)
    monkeypatch.setattr(
        app_module,
        "save_workspace_state",
        lambda selected_program_ids, questionnaire_values, result_snapshot, program_scheme=None, writing_draft_history=None: stored.update(
            selected_program_ids=selected_program_ids,
            questionnaire_values=questionnaire_values,
            result_snapshot=result_snapshot,
            program_scheme=program_scheme or {},
            writing_draft_history=writing_draft_history or [],
        ) or stored,
    )

    client = TestClient(app_module.app)
    response = client.get("/api/workspace/local")
    assert response.status_code == 200
    assert response.json()["selected_program_ids"] == ["hku-master-of-science-in-computer-science-2027"]
    assert response.json()["writing_draft_history"][0]["title"] == "API draft"

    payload = response.json()
    payload["selected_program_ids"] = ["cuhk-msc-in-computer-science-2027"]
    payload["questionnaire_values"] = {"career_plan": "AI product"}
    payload["writing_draft_history"] = [{"id": "draft-api-2", "title": "Updated draft"}]
    put_response = client.put("/api/workspace/local", json=payload)
    assert put_response.status_code == 200
    assert stored["selected_program_ids"] == ["cuhk-msc-in-computer-science-2027"]
    assert stored["questionnaire_values"]["career_plan"] == "AI product"
    assert stored["writing_draft_history"][0]["title"] == "Updated draft"



def test_local_profile_api_uses_signed_cookie_and_ignores_profile_header(monkeypatch) -> None:
    seen_profile_ids: list[str] = []

    def fake_save(payload, profile_id: str):
        seen_profile_ids.append(profile_id)
        return payload

    monkeypatch.setattr(app_module, "save_profile", fake_save)

    client = TestClient(app_module.app)
    payload = _profile().model_dump(mode="json")
    first = client.put("/api/profile/local", json=payload, headers={"x-harbor-profile-id": "local_student"})
    assert first.status_code == 200
    assert seen_profile_ids[0].startswith("student_")
    assert seen_profile_ids[0] != "local_student"

    cookie_value = first.cookies.get("harbor_profile_id")
    assert cookie_value is not None
    assert cookie_value.startswith(seen_profile_ids[0] + ".")

    second = client.put("/api/profile/local", json=payload)
    assert second.status_code == 200
    assert seen_profile_ids[-1] == seen_profile_ids[0]

    forged_client = TestClient(app_module.app)
    forged_client.cookies.set("harbor_profile_id", "local_student.invalid")
    forged = forged_client.put("/api/profile/local", json=payload)
    assert forged.status_code == 200
    assert seen_profile_ids[-1] != "local_student"