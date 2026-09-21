"""API tests for the batch enqueue endpoint (POST /api/jobs/batch).

Runs against a sqlite file (see conftest.py); TestClient executes background
tasks synchronously, so pipeline results are visible right after each POST.
"""

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Sample

GOOD_FASTQ = """@SEQ1
ACGTACGT
+
IIIIHHHH
@SEQ2
NNNNACGT
+
IIIIIIII
"""

BROKEN_FASTQ = """@SEQ1
ACGT
NOTPLUS
IIII
"""


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Sample).count() == 0:
            db.add(
                Sample(
                    name="test-good",
                    description="合格样例",
                    is_broken=False,
                    fastq_content=GOOD_FASTQ,
                )
            )
            db.add(
                Sample(
                    name="test-broken",
                    description="损坏样例",
                    is_broken=True,
                    fastq_content=BROKEN_FASTQ,
                )
            )
            db.commit()
    finally:
        db.close()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def sample_ids(client):
    db = SessionLocal()
    try:
        samples = {s.name: s.id for s in db.query(Sample).all()}
        return {"good": samples["test-good"], "broken": samples["test-broken"]}
    finally:
        db.close()


def _token(client, username, password):
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_batch_create_continue_on_item_failure(client, sample_ids):
    """勾合格+损坏+不存在各一:逐条创建,不存在的那条记原因且不中断。"""
    headers = _token(client, "bioops", "fastq123456")
    resp = client.post(
        "/api/jobs/batch",
        json={"sampleIds": [sample_ids["good"], sample_ids["broken"], 99999]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    results = resp.json()["results"]
    assert len(results) == 3

    assert results[0]["ok"] is True and results[0]["job_id"]
    assert results[0]["sample_name"] == "test-good"
    assert results[1]["ok"] is True and results[1]["job_id"]
    assert results[1]["sample_name"] == "test-broken"
    assert results[2]["ok"] is False
    assert results[2]["job_id"] is None
    assert "不存在" in results[2]["reason"]
    assert results[0]["job_id"] != results[1]["job_id"]


def test_batch_jobs_visible_in_history_with_different_status(client, sample_ids):
    """批量入队后历史可见:合格样例 success,损坏样例 failed。"""
    headers = _token(client, "bioops", "fastq123456")
    resp = client.post(
        "/api/jobs/batch",
        json={"sampleIds": [sample_ids["good"], sample_ids["broken"]]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    job_ids = [r["job_id"] for r in resp.json()["results"]]

    history = client.get("/api/jobs", headers=headers)
    assert history.status_code == 200
    by_id = {j["id"]: j for j in history.json()}
    assert set(job_ids) <= set(by_id)

    good_job = by_id[job_ids[0]]
    broken_job = by_id[job_ids[1]]
    assert good_job["sample_name"] == "test-good"
    assert broken_job["sample_name"] == "test-broken"
    assert good_job["status"] == "success"
    assert broken_job["status"] == "failed"
    assert good_job["metrics"]["reads"] == 2
    assert broken_job["error_message"]


def test_batch_forbidden_for_auditor(client, sample_ids):
    """审计员调用批量接口:403。"""
    headers = _token(client, "auditor", "audit123456")
    resp = client.post(
        "/api/jobs/batch",
        json={"sampleIds": [sample_ids["good"]]},
        headers=headers,
    )
    assert resp.status_code == 403


def test_batch_requires_login(client, sample_ids):
    resp = client.post("/api/jobs/batch", json={"sampleIds": [sample_ids["good"]]})
    assert resp.status_code == 401


def test_batch_rejects_empty_selection(client):
    headers = _token(client, "bioops", "fastq123456")
    resp = client.post("/api/jobs/batch", json={"sampleIds": []}, headers=headers)
    assert resp.status_code == 422
