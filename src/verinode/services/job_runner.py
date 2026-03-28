from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import BoundedSemaphore

from verinode.acquirers.base import WebEvidenceAcquirer
from verinode.database import Database
from verinode.extractors.base import ClaimExtractor
from verinode.models import Document, Job, JobStatus, JobType
from verinode.services.extraction import run_document_extraction
from verinode.services.verification import run_card_verification
from verinode.services.web_evidence import run_card_web_evidence
from verinode.verifiers.base import ReferenceVerifier
from verinode.services.jobs import mark_job_failed, mark_job_running, mark_job_succeeded


class JobRunner:
    def __init__(
        self,
        *,
        database: Database,
        data_dir: Path,
        max_concurrent_jobs: int,
        claim_extractor: ClaimExtractor,
        reference_verifier: ReferenceVerifier,
        web_evidence_acquirer: WebEvidenceAcquirer,
    ) -> None:
        self._database = database
        self._data_dir = data_dir
        self._claim_extractor = claim_extractor
        self._reference_verifier = reference_verifier
        self._web_evidence_acquirer = web_evidence_acquirer
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent_jobs)
        self._semaphore = BoundedSemaphore(max_concurrent_jobs)

    def enqueue(self, job_id: str) -> None:
        self._executor.submit(self._run_job, job_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    def _run_job(self, job_id: str) -> None:
        with self._semaphore:
            try:
                self._execute_job(job_id)
            except Exception as exc:
                self._fail_job(job_id, str(exc))

    def _execute_job(self, job_id: str) -> None:
        session = self._database.session()
        try:
            job = session.get(Job, job_id)
            if job is None or job.status is not JobStatus.QUEUED:
                return

            mark_job_running(session, job)

            if job.job_type is JobType.EXTRACT_CLAIMS:
                if job.document_id is None:
                    raise ValueError("job_missing_document")

                document = session.get(Document, job.document_id)
                if document is None:
                    raise ValueError("document_not_found")

                run_document_extraction(
                    session,
                    data_dir=self._data_dir,
                    document=document,
                    extractor=self._claim_extractor,
                )
            elif job.job_type is JobType.VERIFY_CARD:
                if job.claim_card is None:
                    raise ValueError("job_missing_claim_card")
                run_card_verification(
                    session,
                    card=job.claim_card,
                    verifier=self._reference_verifier,
                )
            elif job.job_type is JobType.WEB_EVIDENCE:
                if job.claim_card is None:
                    raise ValueError("job_missing_claim_card")
                run_card_web_evidence(
                    session,
                    data_dir=self._data_dir,
                    card=job.claim_card,
                    acquirer=self._web_evidence_acquirer,
                )
            else:
                raise ValueError(f"unsupported_job_type:{job.job_type}")

            mark_job_succeeded(session, job)
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _fail_job(self, job_id: str, message: str) -> None:
        session = self._database.session()
        try:
            job = session.get(Job, job_id)
            if job is None:
                return
            mark_job_failed(session, job, message=message)
        finally:
            session.close()
