"""Batch enqueue self-test: auditor 403, per-row results, history statuses differ."""
import os
import sys
import tempfile
from pathlib import Path

DB_FD, DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Sample  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"

Base.metadata.create_all(bind=engine)
db = SessionLocal()
db.add(Sample(name="demo-good-r1", description="合格样例", is_broken=False,
              fastq_content=(DATA / "good.fastq").read_text()))
db.add(Sample(name="demo-broken-malformed", description="损坏样例", is_broken=True,
              fastq_content=(DATA / "broken.fastq").read_text()))
db.commit()
db.close()

client = TestClient(app)


def login(username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


bioops_tok = login("bioops", "fastq123456")
auditor_tok = login("auditor", "audit123456")
H_BIO = {"Authorization": f"Bearer {bioops_tok}"}
H_AUD = {"Authorization": f"Bearer {auditor_tok}"}

# 1. 审计员不能调用批量接口
r = client.post("/api/jobs/batch", json={"sampleIds": [1]}, headers=H_AUD)
print("[auditor POST /jobs/batch]", r.status_code)
assert r.status_code == 403, r.text

# 2. 批量勾选:合格(1)、损坏(2)、不存在(999)
r = client.post("/api/jobs/batch", json={"sampleIds": [1, 2, 999]}, headers=H_BIO)
print("[bioops POST /jobs/batch]", r.status_code)
assert r.status_code == 200, r.text
batch = r.json()
print("batch result:", batch)
assert batch["total"] == 3 and batch["succeeded"] == 2 and batch["failed"] == 1
by_sample = {i["sample_id"]: i for i in batch["items"]}
assert by_sample[1]["success"] and by_sample[1]["job_id"]
assert by_sample[2]["success"] and by_sample[2]["job_id"]
assert not by_sample[999]["success"] and by_sample[999]["reason"]
good_job_id, broken_job_id = by_sample[1]["job_id"], by_sample[2]["job_id"]

# 3. 一条失败不影响其他行:两条作业都真实存在
r = client.get("/api/jobs", headers=H_BIO)
jobs = {j["id"]: j for j in r.json()}
assert good_job_id in jobs and broken_job_id in jobs

# 4. 历史两条状态不同:合格 success,损坏 failed
good_job = jobs[good_job_id]
broken_job = jobs[broken_job_id]
print(f"job #{good_job_id} ({good_job['sample_name']}) -> {good_job['status']}")
print(f"job #{broken_job_id} ({broken_job['sample_name']}) -> {broken_job['status']} "
      f"error={broken_job['error_message']!r}")
assert good_job["status"] == "success", good_job
assert broken_job["status"] == "failed", broken_job
assert good_job["status"] != broken_job["status"]

# 5. 空列表
r = client.post("/api/jobs/batch", json={"sampleIds": []}, headers=H_BIO)
assert r.status_code == 200 and r.json()["total"] == 0

# 6. 去重:重复 ID 只建一条
r = client.post("/api/jobs/batch", json={"sampleIds": [1, 1]}, headers=H_BIO)
body = r.json()
assert body["total"] == 1 and body["succeeded"] == 1, body

# 7. 审计员可读历史(作业可见)
r = client.get("/api/jobs", headers=H_AUD)
assert r.status_code == 200 and good_job_id in {j["id"] for j in r.json()}

print("\nALL SELF-TEST ASSERTIONS PASSED")
os.unlink(DB_PATH)
