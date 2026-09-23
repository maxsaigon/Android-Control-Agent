import asyncio
import hashlib
import importlib
import json
from functools import wraps
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from app.models import Device, HelperUpdateJob, HelperUpdatePolicy
from app.services import helper_updates as updates
from app.services import helper_release
from app.services.device_manager import DeviceManager

queue_module = importlib.import_module("app.services.task_queue")


def run_async(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


@pytest.fixture
def lab(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'updates.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(updates, "engine", engine)
    monkeypatch.setattr(queue_module, "engine", engine)
    monkeypatch.setattr(queue_module, "task_queue", queue_module.TaskQueue())
    connections = {}
    monkeypatch.setattr(updates.device_hub, "get_connection", connections.get)
    with Session(engine) as session:
        session.add_all([Device(id=i, name=f"Phone {i}", ip_address="cloud", adb_port=0) for i in [1, 2]])
        session.commit()
    return engine, connections, updates.HelperUpdates()


def release():
    return {"version_code": 8, "artifact_name": "helper-v8.apk", "sha256": "abc", "file_size_bytes": 3}


def jobs(engine):
    with Session(engine) as session:
        return session.exec(select(HelperUpdateJob).order_by(HelperUpdateJob.id)).all()


class Phone:
    def __init__(self, version=7, capable=True, stream="idle"):
        self.metadata = {"version_code": version, "accessibility_ready": True,
                         "capabilities": ["helper_update"] if capable else []}
        self.commands = []
        self.stream = stream

    async def send_command(self, action, params=None):
        self.commands.append((action, params))
        return {"status": "ok", "result": {"state": self.stream}}


@run_async
async def test_canary_must_reconnect_healthy_before_second_phone(lab):
    engine, phones, manager = lab
    phones.update({1: Phone(), 2: Phone()})
    updates.create_rollout([1, 2], release())
    await manager.tick()
    first, second = jobs(engine)
    assert first.blocks_control and second.state == "queued"
    assert updates.blocking_reason(1)
    assert not phones[2].commands
    # Merely claiming installed isn't success: version + health are required.
    phones[1].metadata["update"] = {"state": "installed", "job_id": first.id}
    await manager.tick()
    assert jobs(engine)[0].state != "succeeded"
    phones[1].metadata["version_code"] = 8
    phones[1].metadata["accessibility_ready"] = False
    await manager.tick()
    assert jobs(engine)[0].state != "succeeded"
    phones[1].metadata["accessibility_ready"] = True
    await manager.tick()
    assert jobs(engine)[0].state == "succeeded"
    assert not updates.blocking_reason(1)
    await manager.tick()
    assert any(action == "helper_update" for action, _ in phones[2].commands)


@run_async
async def test_failed_canary_stops_fleet_and_releases_only_known_failed_install(lab):
    engine, phones, manager = lab
    phones.update({1: Phone(), 2: Phone()})
    updates.create_rollout([1, 2], release())
    await manager.tick()
    first = jobs(engine)[0]
    phones[1].metadata["update"] = {"state": "failed", "job_id": first.id, "error": "bad certificate"}
    await manager.tick()
    await manager.tick()
    assert jobs(engine)[0].state == "failed"
    assert not updates.blocking_reason(1)
    assert not phones[2].commands


@run_async
async def test_unknown_install_timeout_keeps_reservation_and_late_recovery_clears_it(lab):
    engine, phones, manager = lab
    phones[1] = Phone()
    updates.create_rollout([1], release())
    await manager.tick()
    job = jobs(engine)[0]
    updates.change(job.id, started_at=updates.now() - timedelta(minutes=16))
    phones.clear()
    await manager.tick()
    assert jobs(engine)[0].state == "failed"
    assert updates.blocking_reason(1)
    phones[1] = Phone(version=8)
    await manager.tick()
    assert jobs(engine)[0].state == "succeeded"
    assert not updates.blocking_reason(1)


@run_async
async def test_restart_does_not_resend_install(lab):
    engine, phones, manager = lab
    phones[1] = Phone()
    updates.create_rollout([1], release())
    await manager.tick()
    manager = updates.HelperUpdates()
    await manager.tick()
    assert [c[0] for c in phones[1].commands].count("helper_update") == 1


@run_async
async def test_update_waits_for_task_and_live_stream(lab):
    engine, phones, manager = lab
    phones[1] = Phone(stream="streaming")
    updates.create_rollout([1], release())
    async with queue_module.task_queue._get_device_lock(1):
        await manager.tick()
        assert not phones[1].commands
    await manager.tick()
    assert jobs(engine)[0].state == "waiting_idle"
    assert not any(c[0] == "helper_update" for c in phones[1].commands)


@run_async
async def test_reservation_blocks_manual_and_queues_workflow(lab):
    engine, phones, manager = lab
    phones[1] = Phone()
    updates.create_rollout([1], release())
    await manager.tick()
    with pytest.raises(RuntimeError, match="Helper update"):
        async with queue_module.task_queue.manual_control(1):
            pytest.fail("Control entered update")
    entered = asyncio.Event()
    async def workflow():
        async with queue_module.task_queue.device_execution(1):
            entered.set()
    pending = asyncio.create_task(workflow())
    await asyncio.sleep(0.01)
    assert not entered.is_set()
    updates.change(jobs(engine)[0].id, state="succeeded", blocks_control=False)
    await asyncio.wait_for(pending, 3)
    assert entered.is_set()


@run_async
async def test_old_helper_requires_first_install(lab):
    engine, phones, manager = lab
    phones[1] = Phone(capable=False)
    updates.create_rollout([1], release())
    await manager.tick()
    assert jobs(engine)[0].state == "needs_bootstrap"
    assert not updates.blocking_reason(1)


def test_overlapping_rollout_rejected(lab):
    updates.create_rollout([1], release())
    with pytest.raises(ValueError, match="existing rollout"):
        updates.create_rollout([2], release())


def test_release_validation_rejects_corrupt_apk_and_path_traversal(tmp_path, monkeypatch):
    (tmp_path / "helper.apk").write_bytes(b"apk")
    metadata = {"artifact_name": "helper.apk", "version_code": 8, "file_size_bytes": 3,
                "sha256": hashlib.sha256(b"apk").hexdigest()}
    monkeypatch.setattr(helper_release, "helper_downloads_dir", lambda: tmp_path)
    monkeypatch.setattr(helper_release, "load_helper_release_metadata", lambda: metadata)
    assert helper_release.validated_helper_release()["download_path"].endswith("helper.apk")
    (tmp_path / "helper.apk").write_bytes(b"bad")
    with pytest.raises(ValueError, match="checksum"):
        helper_release.validated_helper_release()
    metadata["artifact_name"] = "../helper.apk"
    with pytest.raises(ValueError, match="invalid"):
        helper_release.validated_helper_release()


@run_async
async def test_adb_install_verifies_version_and_preserves_other_accessibility(tmp_path, monkeypatch):
    content = b"apk"
    (tmp_path / "helper.apk").write_bytes(content)
    monkeypatch.setattr(helper_release, "helper_downloads_dir", lambda: tmp_path)
    manager = DeviceManager()
    manager.helper_version = AsyncMock(side_effect=[7, 8])
    commands = []
    async def adb(*args, **kwargs):
        commands.append(args)
        if "install" in args:
            return 0, "Success", ""
        if "get" in args:
            return 0, "other.app/.Service:" + manager.HELPER_SERVICE, ""
        if "dumpsys" in args:
            return 0, "Bound services: {" + manager.HELPER_SERVICE + "}", ""
        return 0, "", ""
    monkeypatch.setattr(manager, "_run_adb", adb)
    result = await manager.install_helper_release("127.0.0.1", 5555, {
        "artifact_name": "helper.apk", "version_code": 8, "file_size_bytes": 3,
        "sha256": hashlib.sha256(content).hexdigest(),
    })
    assert result["verified"]
    assert any("other.app/.Service:" + manager.HELPER_SERVICE == cmd[-1] for cmd in commands)


@run_async
async def test_automatic_release_creates_canary_first_rollout(lab, monkeypatch):
    engine, phones, manager = lab
    with Session(engine) as session:
        session.add(HelperUpdatePolicy(automatic=True, canary_device_id=2, last_version_code=7))
        session.commit()
    monkeypatch.setattr(updates, "validated_helper_release", release)
    await manager.tick()
    assert [job.device_id for job in jobs(engine)] == [2, 1]


def test_update_api_owner_policy_and_stopping_rollout(lab, monkeypatch):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from app.models import User
    from app.routers import helper_updates as routes
    engine, phones, manager = lab
    monkeypatch.setattr(routes, "engine", engine)
    monkeypatch.setattr(updates, "validated_helper_release", release)
    with Session(engine) as session:
        session.add_all([User(id=1, username="admin", password="unused"), User(id=2, username="operator", password="unused")])
        session.commit()
    app = FastAPI()
    @app.middleware("http")
    async def auth(request: Request, call_next):
        request.scope["session"] = {"user_id": int(request.headers.get("x-test-user", "2"))}
        return await call_next(request)
    app.include_router(routes.router)
    with TestClient(app) as client:
        assert client.get("/api/helper/updates").status_code == 403
        headers = {"x-test-user": "1"}
        assert client.put("/api/helper/updates/policy", headers=headers,
                          json={"automatic": True, "canary_device_id": 1}).status_code == 409
        rollout = client.post("/api/helper/updates/rollout", headers=headers, json={"device_ids": [1, 2]})
        assert rollout.status_code == 200
        first = jobs(engine)[0]
        updates.change(first.id, state="installing", blocks_control=True)
        assert client.post(f"/api/helper/updates/rollouts/{rollout.json()['rollout_id']}/stop", headers=headers).status_code == 200
        assert jobs(engine)[0].blocks_control
        assert jobs(engine)[1].state == "cancelled"
        data = client.get("/api/helper/updates", headers=headers).json()
        assert "release_json" not in data["jobs"][0]


def test_publish_uses_embedded_metadata_and_rejects_same_version_new_apk(tmp_path, monkeypatch):
    import importlib.util
    import zipfile
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("publish_helper", Path(__file__).parents[1] / "android-helper/publish_helper_release.py")
    publish = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publish)
    output = tmp_path / "build"
    downloads = tmp_path / "downloads"
    output.mkdir()
    monkeypatch.setattr(publish, "OUTPUT_DIR", output)
    monkeypatch.setattr(publish, "DOWNLOADS_DIR", downloads)
    build = {"version_code": 8, "version_name": "1.4.0", "build_sha": "compiled-sha",
             "build_time_utc": "20260923-123456", "package_name": "com.androidcontrol.helper", "protocol_version": 1, "min_sdk": 28}
    (output / "output-metadata.json").write_text(json.dumps({"elements": [{"outputFile": "helper.apk", "versionCode": 8, "versionName": "1.4.0"}]}))
    with zipfile.ZipFile(output / "helper.apk", "w") as apk:
        apk.writestr("assets/helper-build.json", json.dumps(build))
    assert publish.main() == 0
    metadata = json.loads((downloads / "helper-release.json").read_text())
    assert metadata["build_sha"] == "compiled-sha"
    assert metadata["build_time_utc"] == build["build_time_utc"]
    with zipfile.ZipFile(output / "helper.apk", "a") as apk:
        apk.writestr("changed", "new content")
    with pytest.raises(ValueError, match="new versionCode"):
        publish.main()
    assert json.loads((downloads / "helper-release.json").read_text()) == metadata
