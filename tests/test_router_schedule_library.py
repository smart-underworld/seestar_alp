"""
Unit tests for the front_v2 server-side schedule library endpoints:
GET/POST /api/v1/schedules/library and GET/DELETE /api/v1/schedules/library/{filename}.

These are pure filesystem operations with no device/simulator dependency,
so they belong in the fast unit lane (pytest -m "not integration").
"""

import json
import os

import pytest

# Skip at collection time if v2 deps are not installed.
pytest.importorskip(
    "fastapi", reason="fastapi not installed; run: pip install -e '.[v2]'"
)

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from front_v2.api import router_schedule  # noqa: E402

SAMPLE_SCHEDULE = json.dumps(
    {
        "version": "1.0",
        "Event": "Scheduler",
        "state": "stopped",
        "list": [{"action": "scope_park", "params": {}, "schedule_item_id": "abc123"}],
    }
)


@pytest.fixture
def schedule_dir(tmp_path):
    """A schedule library directory that does not exist yet."""
    return tmp_path / "schedule"


@pytest.fixture
def client(schedule_dir, monkeypatch):
    monkeypatch.setattr(router_schedule, "_SCHEDULE_DIR", schedule_dir)
    app = FastAPI()
    app.include_router(router_schedule.router)
    return TestClient(app)


def test_list_empty_creates_dir(client, schedule_dir):
    assert not schedule_dir.exists()
    r = client.get("/api/v1/schedules/library")
    assert r.status_code == 200
    assert r.json() == {"files": []}
    assert schedule_dir.exists()


def test_save_and_list(client):
    r = client.post(
        "/api/v1/schedules/library?filename=nightly.json", content=SAMPLE_SCHEDULE
    )
    assert r.status_code == 200
    assert r.json() == {"filename": "nightly.json"}

    r = client.get("/api/v1/schedules/library")
    files = r.json()["files"]
    assert len(files) == 1
    assert files[0]["name"] == "nightly.json"
    assert files[0]["size"] == len(SAMPLE_SCHEDULE.encode("utf-8"))


def test_save_requires_json_extension(client):
    r = client.post(
        "/api/v1/schedules/library?filename=nightly", content=SAMPLE_SCHEDULE
    )
    assert r.status_code == 400


def test_save_rejects_invalid_json(client):
    r = client.post("/api/v1/schedules/library?filename=bad.json", content="not json")
    assert r.status_code == 400


def test_get_saved_schedule(client):
    client.post(
        "/api/v1/schedules/library?filename=nightly.json", content=SAMPLE_SCHEDULE
    )
    r = client.get("/api/v1/schedules/library/nightly.json")
    assert r.status_code == 200
    assert r.json() == json.loads(SAMPLE_SCHEDULE)


def test_get_missing_returns_404(client):
    r = client.get("/api/v1/schedules/library/missing.json")
    assert r.status_code == 404


def test_get_invalid_extension_returns_400(client):
    r = client.get("/api/v1/schedules/library/nightly.txt")
    assert r.status_code == 400


def test_delete_removes_file(client):
    client.post(
        "/api/v1/schedules/library?filename=nightly.json", content=SAMPLE_SCHEDULE
    )
    r = client.delete("/api/v1/schedules/library/nightly.json")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}

    r = client.get("/api/v1/schedules/library")
    assert r.json() == {"files": []}


def test_delete_nonexistent_is_idempotent(client):
    r = client.delete("/api/v1/schedules/library/missing.json")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_path_traversal_filename_is_sanitized(client, schedule_dir):
    r = client.post(
        "/api/v1/schedules/library?filename=../../etc/passwd.json",
        content=SAMPLE_SCHEDULE,
    )
    assert r.status_code == 200
    assert r.json() == {"filename": "passwd.json"}
    assert (schedule_dir / "passwd.json").exists()


def test_list_sorted_by_modified_desc(client, schedule_dir):
    schedule_dir.mkdir(parents=True, exist_ok=True)
    older = schedule_dir / "older.json"
    newer = schedule_dir / "newer.json"
    older.write_text("{}")
    newer.write_text("{}")
    os.utime(older, (1000, 1000))
    os.utime(newer, (2000, 2000))

    r = client.get("/api/v1/schedules/library")
    names = [f["name"] for f in r.json()["files"]]
    assert names == ["newer.json", "older.json"]
