from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers


def test_first_secret_is_identical_across_concurrent_workers(tmp_path, monkeypatch):
    from harbor_agent.services import profile_store
    monkeypatch.setattr(profile_store.get_settings(), "profile_store_secret", None)
    monkeypatch.delenv("HARBOR_AGENT_PROFILE_STORE_SECRET", raising=False)
    db = tmp_path / "profiles.sqlite"
    barrier = Barrier(16)
    def create():
        barrier.wait()
        return profile_store.profile_store_secret(db)
    with ThreadPoolExecutor(max_workers=16) as pool:
        keys = list(pool.map(lambda _: create(), range(16)))
    assert len(set(keys)) == 1
    assert keys[0] == profile_store.profile_store_secret(db)
    protected = profile_store._protect_json('{"test":"value"}', db)
    assert profile_store._unprotect_json(protected, db) == '{"test":"value"}'
    assert (tmp_path / ".harborpilot_profile_secret").stat().st_mode & 0o077 == 0


def test_local_proxy_never_grants_admin_or_other_owner_access(monkeypatch):
    import harbor_agent.app as api
    monkeypatch.setattr(api.settings, "admin_token", None)
    monkeypatch.setattr(api.settings, "allow_insecure_local_admin", True)
    monkeypatch.setattr("harbor_agent.services.agent_runtime.get_multi_agent_workflow", lambda _: {"owner_id": "other-owner"})
    request = SimpleNamespace(method="GET", headers=Headers({}), cookies={}, client=SimpleNamespace(host="127.0.0.1"))
    assert api._admin_request_allowed(request) is False
    with pytest.raises(HTTPException) as error:
        api._runtime_workflow_owner("workflow", request)
    assert error.value.status_code == 404


def test_resume_claim_is_cross_connection_exclusive_and_released():
    from harbor_agent.services.agent_runtime import claim_workflow_resume
    entered, release = Event(), Event()
    def first():
        with claim_workflow_resume("same-workflow"):
            entered.set()
            assert release.wait(5)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(first)
        assert entered.wait(5)
        try:
            with pytest.raises(ValueError, match="already in progress"):
                with claim_workflow_resume("same-workflow"):
                    pytest.fail("duplicate accepted")
        finally:
            release.set()
        future.result()
    with claim_workflow_resume("same-workflow"):
        pass
    with pytest.raises(RuntimeError):
        with claim_workflow_resume("same-workflow"):
            raise RuntimeError("invalid request")
    with claim_workflow_resume("same-workflow"):
        pass


def test_two_resume_requests_start_only_one_execution(monkeypatch):
    from harbor_agent.runtime import workflow as module
    from harbor_agent.runtime.state import AgentState, WorkflowGoal, WorkflowStatus
    state = AgentState(workflow_id="concurrent-resume", goal=next(iter(WorkflowGoal)), status=WorkflowStatus.WAITING_USER)
    started, release = Event(), Event()
    calls = []
    monkeypatch.setattr(module, "load_checkpoint", lambda _: state.model_copy(deep=True))
    monkeypatch.setattr(module, "get_multi_agent_workflow", lambda _: {"owner_id": "owner"})
    monkeypatch.setattr(module.MultiAgentRuntime, "_save_checkpoint", lambda *args, **kwargs: None)
    def run(self, resumed, tracer):
        calls.append(resumed)
        started.set()
        assert release.wait(5)
        return resumed
    monkeypatch.setattr(module.MultiAgentRuntime, "_run", run)
    tracer = SimpleNamespace(current=None, emit=lambda *args, **kwargs: None)
    def resume():
        runtime = object.__new__(module.MultiAgentRuntime)
        return runtime._resume(state.workflow_id, module.WorkflowResumeRequest(user_message="update"), tracer=tracer)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(resume)
        assert started.wait(5)
        try:
            with pytest.raises(ValueError, match="already in progress"):
                resume()
        finally:
            release.set()
        first.result()
    assert len(calls) == 1


def test_persistent_data_and_profile_secret_survive_new_process(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    environment = {**os.environ, "HARBOR_AGENT_DATA_DIR": str(tmp_path / "persistent"),
                   "HARBOR_AGENT_SEED_DIR": str(root / "data"), "PYTHONPATH": str(root / "src")}
    write = '''
from harbor_agent.models import ApplicantProfileInput
from harbor_agent.services.profile_store import save_profile
from harbor_agent.services.agent_runtime import create_multi_agent_workflow
save_profile(ApplicantProfileInput(education={"major":"test-major", "gpa":80}), profile_id="student")
create_multi_agent_workflow("persisted-workflow", "test", {"status":"WAITING_USER"}, owner_id="student")
'''
    read = '''
from harbor_agent.services.profile_store import load_profile
from harbor_agent.services.agent_runtime import get_multi_agent_workflow
from harbor_agent.services.program_store import PROGRAM_JSON
assert load_profile("student").education.major == "test-major"
assert get_multi_agent_workflow("persisted-workflow")["owner_id"] == "student"
assert PROGRAM_JSON.is_file()
'''
    subprocess.run([sys.executable, "-c", write], env=environment, check=True, timeout=15)
    subprocess.run([sys.executable, "-c", read], env=environment, check=True, timeout=15)
