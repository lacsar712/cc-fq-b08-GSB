from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.auth import authenticate_user, create_access_token, get_current_user, require_bioops
from app.database import SessionLocal, get_db
from app.models import Job, JobStage, Sample
from app.pipeline.runner import create_job_stages, run_pipeline_sync
from app.schemas import (
    HealthOut,
    JobBatchCreate,
    JobBatchItem,
    JobBatchOut,
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
    job = _create_job_from_sample_or_text(db, body.sampleId, body.fastqText, user["username"])
    background.add_task(_run_job_background, job.id)
    return (
        db.query(Job)
        .options(joinedload(Job.stages))
        .filter(Job.id == job.id)
        .first()
    )


def _create_job_from_sample_or_text(
    db: Session, sample_id: int | None, fastq_text: str | None, username: str
) -> Job:
    """Create a job + stages from a sample id or raw FASTQ text. Raises HTTPException."""
    fastq_text = (fastq_text or "").strip() if fastq_text else ""
    sample_name = "自定义输入"
    sample = None

    if sample_id is not None:
        sample = db.query(Sample).filter(Sample.id == sample_id).first()
        if not sample:
            raise HTTPException(status_code=404, detail="样例不存在")
        fastq_text = sample.fastq_content
        sample_name = sample.name
    elif not fastq_text:
        raise HTTPException(status_code=400, detail="请提供 sampleId 或 fastqText")

    job = Job(
        sample_id=sample.id if sample else None,
        sample_name=sample_name,
        status="pending",
        created_by=username,
        fastq_snapshot=fastq_text,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    create_job_stages(db, job.id)
    return job


@router.post("/jobs/batch", response_model=JobBatchOut)
def create_jobs_batch(
    body: JobBatchCreate,
    background: BackgroundTasks,
    user: dict = Depends(require_bioops),
    db: Session = Depends(get_db),
):
    """逐条为勾选样例创建并入队;一条失败不中断后面,每行记录成功或原因。"""
    items: list[JobBatchItem] = []
    succeeded = 0

    # 去重但保留勾选顺序
    seen: set[int] = set()
    sample_ids = [sid for sid in body.sampleIds if not (sid in seen or seen.add(sid))]

    for sample_id in sample_ids:
        sample = db.query(Sample).filter(Sample.id == sample_id).first()
        item = JobBatchItem(sample_id=sample_id, sample_name=sample.name if sample else None)
        try:
            if not sample:
                raise HTTPException(status_code=404, detail="样例不存在")
            job = _create_job_from_sample_or_text(db, sample_id, None, user["username"])
            background.add_task(_run_job_background, job.id)
            item.success = True
            item.job_id = job.id
            succeeded += 1
        except HTTPException as exc:
            db.rollback()
            item.success = False
            item.reason = exc.detail if isinstance(exc.detail, str) else "创建失败"
        except Exception as exc:  # noqa: BLE001 - 单条失败隔离,继续处理后续行
            db.rollback()
            item.success = False
            item.reason = f"创建异常: {exc}"
        items.append(item)

    return JobBatchOut(
        total=len(items),
        succeeded=succeeded,
        failed=len(items) - succeeded,
        items=items,
    )


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
