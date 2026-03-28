from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from verinode.models import (
    CardStage,
    ClaimCard,
    Document,
    DocumentStatus,
    Job,
    JobStatus,
    JobType,
)


def create_document_job(
    session: Session,
    *,
    document: Document,
    job_type: JobType,
) -> Job:
    job = Job(
        id=uuid4().hex,
        job_type=job_type,
        document_id=document.id,
        status=JobStatus.QUEUED,
    )
    if job_type is JobType.EXTRACT_CLAIMS:
        document.status = DocumentStatus.EXTRACTING

    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def recover_interrupted_jobs(session: Session) -> list[Job]:
    jobs = list(
        session.scalars(
            select(Job).where(
                Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING])
            )
        )
    )
    if not jobs:
        return []

    for job in jobs:
        _apply_failed_job_state(
            job,
            message="Job was interrupted during a previous backend run. Retry or rerun to continue.",
        )
    session.commit()
    for job in jobs:
        session.refresh(job)
    return jobs


def retry_job(session: Session, job: Job) -> Job:
    if job.status is not JobStatus.FAILED:
        raise ValueError("job_not_failed")

    job.status = JobStatus.QUEUED
    job.error_message = None
    if job.document is not None and job.job_type is JobType.EXTRACT_CLAIMS:
        job.document.status = DocumentStatus.EXTRACTING
    if job.claim_card is not None and job.job_type in {JobType.VERIFY_CARD, JobType.SANDBOX}:
        job.claim_card.stage = CardStage.EXTRACTED
    if job.claim_card is not None and job.job_type is JobType.WEB_EVIDENCE:
        job.claim_card.stage = (
            CardStage.VERIFIED
            if job.claim_card.verification_results
            else CardStage.EXTRACTED
        )
    session.commit()
    session.refresh(job)
    return job


def mark_job_running(session: Session, job: Job) -> Job:
    if job.status is not JobStatus.QUEUED:
        raise ValueError("job_not_queued")

    job.status = JobStatus.RUNNING
    session.commit()
    session.refresh(job)
    return job


def mark_job_succeeded(session: Session, job: Job) -> Job:
    job.status = JobStatus.SUCCEEDED
    job.error_message = None
    session.commit()
    session.refresh(job)
    return job


def mark_job_failed(session: Session, job: Job, *, message: str) -> Job:
    _apply_failed_job_state(job, message=message)
    session.commit()
    session.refresh(job)
    return job


def create_card_job(
    session: Session,
    *,
    claim_card: ClaimCard,
    job_type: JobType,
) -> Job:
    job = Job(
        id=uuid4().hex,
        job_type=job_type,
        document_id=claim_card.document_id,
        claim_card_id=claim_card.id,
        status=JobStatus.QUEUED,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _apply_failed_job_state(job: Job, *, message: str) -> None:
    job.status = JobStatus.FAILED
    job.error_message = message
    if job.document is not None and job.job_type is JobType.EXTRACT_CLAIMS:
        job.document.status = DocumentStatus.FAILED
    if job.claim_card is not None and job.job_type in {
        JobType.VERIFY_CARD,
        JobType.WEB_EVIDENCE,
        JobType.SANDBOX,
    }:
        job.claim_card.stage = CardStage.FAILED
