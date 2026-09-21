from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.auth import authenticate_user, create_access_token, get_current_user, require_bioops
from app.database import SessionLocal, get_db
from app.models import Job, JobStage, Sample
from app.pipeline.runner import create_job_stages, run_pipeline_sync
from app.schemas import (
    BatchItemOut,
    HealthOut,
    JobBatchCreate,
    JobBatchResult,
    JobCreate,
    JobListItem,
    JobOut,
    LoginRequest,
    SampleOut,
    StageOut,
    TokenResponse,
)


router = APIRouter(prefix="/api")


def _run_job_background(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if job:
            run_pipeline_sync(db, job)
    finally:
        db.close()


def _insert_job(db: Session, background: BackgroundTasks, sample: Sample, username: str) -> Job:
    """Persist a pending job for a sample, create its stages and enqueue the run."""
    job = Job(
        sample_id=sample.id,
        sample_name=sample.name,
        status="pending",
        created_by=username,
        fastq_snapshot=sample.fastq_content,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    create_job_stages(db, job.id)
    background.add_task(_run_job_background, job.id)
    return job


@router.get("/health", response_model=HealthOut)
def health():
    return HealthOut(status="ok", service="fastq-qc-pipeline")


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    user = authenticate_user(body.username.strip(), body.password)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = create_access_token(user["username"], user["role"])
    return TokenResponse(
        access_token=token,
        username=user["username"],
        role=user["role"],
    )


@router.get("/samples", response_model=list[SampleOut])
def list_samples(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Sample).order_by(Sample.id).all()


@router.post("/jobs", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def create_job(
    body: JobCreate,
    background: BackgroundTasks,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    sample_id = body.sampleId
    fastq_text = (body.fastqText or "").strip() if body.fastqText else ""

    if sample_id is not None:
        sample = db.query(Sample).filter(Sample.id == sample_id).first()
        if not sample:
            raise HTTPException(status_code=404, detail="样例不存在")
        job = _insert_job(db, background, sample, user["username"])
    else:
        if not fastq_text:
            raise HTTPException(status_code=400, detail="请提供 sampleId 或 fastqText")
        job = Job(
            sample_id=None,
            sample_name="自定义输入",
            status="pending",
            created_by=user["username"],
            fastq_snapshot=fastq_text,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        create_job_stages(db, job.id)
        background.add_task(_run_job_background, job.id)

    job = (
        db.query(Job)
        .options(joinedload(Job.stages))
        .filter(Job.id == job.id)
        .first()
    )
    return job


@router.post("/jobs/batch", response_model=JobBatchResult, status_code=status.HTTP_201_CREATED)
def create_jobs_batch(
    body: JobBatchCreate,
    background: BackgroundTasks,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    """批量入队:按勾选顺序逐条创建,每条独立提交,一条失败不中断后续。"""
    results: list[BatchItemOut] = []
    for sample_id in body.sampleIds:
        try:
            sample = db.query(Sample).filter(Sample.id == sample_id).first()
            if not sample:
                results.append(
                    BatchItemOut(
                        sample_id=sample_id,
                        sample_name=f"#{sample_id}",
                        ok=False,
                        reason="样例不存在",
                    )
                )
                continue
            job = _insert_job(db, background, sample, user["username"])
            results.append(
                BatchItemOut(sample_id=sample_id, sample_name=sample.name, ok=True, job_id=job.id)
            )
        except Exception as exc:  # noqa: BLE001 - 单条失败须记录原因并继续
            db.rollback()
            results.append(
                BatchItemOut(
                    sample_id=sample_id,
                    sample_name=f"#{sample_id}",
                    ok=False,
                    reason=f"创建失败:{exc}"[:200],
                )
            )
    return JobBatchResult(results=results)


@router.get("/jobs", response_model=list[JobListItem])
def list_jobs(_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Job).order_by(Job.id.desc()).all()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: int, _user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    job = (
        db.query(Job)
        .options(joinedload(Job.stages))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    return job


@router.get("/jobs/{job_id}/stages", response_model=list[StageOut])
def get_job_stages(
    job_id: int, _user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="作业不存在")
    return (
        db.query(JobStage)
        .filter(JobStage.job_id == job_id)
        .order_by(JobStage.stage_order)
        .all()
    )
