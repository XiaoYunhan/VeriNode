from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.orm import Session

from verinode.acquirers.base import WebEvidenceAcquirer
from verinode.acquirers.tinyfish import TinyFishWebEvidenceAcquirer
from verinode.clients.tinyfish import TinyFishClient
from verinode.database import Database
from verinode.extractors.base import ClaimExtractor
from verinode.extractors.openai import OpenAIClaimExtractor
from verinode.models import CardType, ClaimCard, Document, Job, JobStatus, JobType
from verinode.sandboxes.base import SandboxExecutor
from verinode.sandboxes.openai import OpenAISandboxExecutor
from verinode.schemas import ClaimCardDetailRead, ClaimCardRead, DocumentRead, JobRead
from verinode.services.documents import create_document, delete_document, list_document_cards, list_documents
from verinode.services.job_runner import JobRunner
from verinode.services.jobs import (
    create_card_job,
    create_document_job,
    recover_interrupted_jobs,
    retry_job,
)
from verinode.settings import Settings
from verinode.verifiers.base import ReferenceVerifier
from verinode.verifiers.openai import OpenAIReferenceVerifier


def error_detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def create_app(
    settings: Settings | None = None,
    *,
    claim_extractor: ClaimExtractor | None = None,
    reference_verifier: ReferenceVerifier | None = None,
    web_evidence_acquirer: WebEvidenceAcquirer | None = None,
    sandbox_executor: SandboxExecutor | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    app_settings.app_data_dir.mkdir(parents=True, exist_ok=True)
    app_settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    app_settings.artifacts_dir.mkdir(parents=True, exist_ok=True)
    database = Database(app_settings.database_url)
    extractor = claim_extractor or OpenAIClaimExtractor(
        api_key=app_settings.openai_api_key,
        model=app_settings.openai_model_main,
    )
    verifier = reference_verifier or OpenAIReferenceVerifier(
        api_key=app_settings.openai_api_key,
        model=app_settings.openai_model_search,
    )
    acquirer = web_evidence_acquirer
    if app_settings.enable_tinyfish and acquirer is None:
        tinyfish_client = TinyFishClient(
            api_key=app_settings.tinyfish_api_key,
            base_url=app_settings.tinyfish_base_url,
        )
        acquirer = TinyFishWebEvidenceAcquirer(client=tinyfish_client)
    sandbox = sandbox_executor
    if app_settings.enable_code_sandbox and sandbox is None:
        sandbox = OpenAISandboxExecutor(
            api_key=app_settings.openai_api_key,
            model=app_settings.openai_model_sandbox,
        )
    job_runner = JobRunner(
        database=database,
        data_dir=app_settings.app_data_dir,
        max_concurrent_jobs=app_settings.max_concurrent_jobs,
        claim_extractor=extractor,
        reference_verifier=verifier,
        web_evidence_acquirer=acquirer,
        sandbox_executor=sandbox,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database.create_schema()
        recovery_session = database.session()
        try:
            recover_interrupted_jobs(recovery_session)
        finally:
            recovery_session.close()
        app.state.settings = app_settings
        app.state.db = database
        app.state.job_runner = job_runner
        yield
        job_runner.shutdown()

    app = FastAPI(title="VeriNode", lifespan=lifespan)
    if app_settings.app_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.app_cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.mount("/artifacts", StaticFiles(directory=str(app_settings.artifacts_dir)), name="artifacts")

    def get_session(request: Request) -> Iterator[Session]:
        session = request.app.state.db.session()
        try:
            yield session
        finally:
            session.close()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/documents", response_model=list[DocumentRead])
    def get_documents(session: Session = Depends(get_session)) -> list[Document]:
        return list_documents(session)

    @app.post(
        "/api/documents",
        response_model=DocumentRead,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_document(
        file: UploadFile = File(...),
        session: Session = Depends(get_session),
    ) -> Document:
        if not file.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_detail("missing_filename", "Uploaded files need a name."),
            )

        try:
            document = create_document(
                session,
                uploads_dir=app_settings.uploads_dir,
                filename=file.filename,
                contents=await file.read(),
            )
        except ValueError as exc:
            if str(exc) == "unsupported_file_type":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=error_detail(
                        "unsupported_file_type",
                        "Only PDF and Markdown uploads are supported.",
                    ),
                ) from exc
            raise

        return document

    @app.get("/api/documents/{document_id}", response_model=DocumentRead)
    def get_document(document_id: str, session: Session = Depends(get_session)) -> Document:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("document_not_found", "Document not found."),
            )
        return document

    @app.delete("/api/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_document(document_id: str, session: Session = Depends(get_session)) -> None:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("document_not_found", "Document not found."),
            )
        delete_document(session, data_dir=app_settings.app_data_dir, document=document)

    @app.get("/api/documents/{document_id}/cards", response_model=list[ClaimCardRead])
    def get_document_cards(
        document_id: str,
        session: Session = Depends(get_session),
    ) -> list[ClaimCard]:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("document_not_found", "Document not found."),
            )
        return list_document_cards(session, document_id)

    @app.post(
        "/api/documents/{document_id}/extract",
        response_model=JobRead,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def enqueue_extract_job(
        document_id: str,
        session: Session = Depends(get_session),
    ) -> Job:
        document = session.get(Document, document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("document_not_found", "Document not found."),
            )

        existing_job = session.scalar(
            select(Job).where(
                Job.document_id == document_id,
                Job.job_type == JobType.EXTRACT_CLAIMS,
                Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
        )
        if existing_job is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(
                    "extract_job_exists",
                    "An extraction job is already queued or running for this document.",
                ),
            )

        job = create_document_job(
            session,
            document=document,
            job_type=JobType.EXTRACT_CLAIMS,
        )
        job_runner.enqueue(job.id)
        return job

    @app.post(
        "/api/cards/{card_id}/verify",
        response_model=JobRead,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def enqueue_verify_job(
        card_id: str,
        session: Session = Depends(get_session),
    ) -> Job:
        card = session.get(ClaimCard, card_id)
        if card is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("card_not_found", "Card not found."),
            )
        if card.card_type in {CardType.CODE, CardType.MATH}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(
                    "code_math_requires_sandbox",
                    "Code and math claims should use sandbox simulation instead of reference verification.",
                ),
            )

        existing_job = session.scalar(
            select(Job).where(
                Job.claim_card_id == card_id,
                Job.job_type == JobType.VERIFY_CARD,
                Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
        )
        if existing_job is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(
                    "verify_job_exists",
                    "A verification job is already queued or running for this card.",
                ),
            )

        job = create_card_job(
            session,
            claim_card=card,
            job_type=JobType.VERIFY_CARD,
        )
        job_runner.enqueue(job.id)
        return job

    @app.post(
        "/api/cards/{card_id}/sandbox",
        response_model=JobRead,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def enqueue_sandbox_job(
        card_id: str,
        session: Session = Depends(get_session),
    ) -> Job:
        if not app_settings.enable_code_sandbox:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(
                    "code_sandbox_disabled",
                    "Sandbox simulation is disabled in the current environment.",
                ),
            )

        card = session.get(ClaimCard, card_id)
        if card is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("card_not_found", "Card not found."),
            )
        if card.card_type not in {CardType.CODE, CardType.MATH}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(
                    "card_not_sandboxable",
                    "Only code and math claims can use sandbox simulation.",
                ),
            )

        existing_job = session.scalar(
            select(Job).where(
                Job.claim_card_id == card_id,
                Job.job_type == JobType.SANDBOX,
                Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
        )
        if existing_job is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(
                    "sandbox_job_exists",
                    "A sandbox job is already queued or running for this claim.",
                ),
            )

        job = create_card_job(
            session,
            claim_card=card,
            job_type=JobType.SANDBOX,
        )
        job_runner.enqueue(job.id)
        return job

    @app.post(
        "/api/cards/{card_id}/web-evidence",
        response_model=JobRead,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def enqueue_web_evidence_job(
        card_id: str,
        session: Session = Depends(get_session),
    ) -> Job:
        if not app_settings.enable_tinyfish:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(
                    "tinyfish_disabled",
                    "TinyFish is disabled in the current environment.",
                ),
            )

        card = session.get(ClaimCard, card_id)
        if card is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("card_not_found", "Card not found."),
            )

        existing_job = session.scalar(
            select(Job).where(
                Job.claim_card_id == card_id,
                Job.job_type == JobType.WEB_EVIDENCE,
                Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
            )
        )
        if existing_job is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=error_detail(
                    "web_evidence_job_exists",
                    "A web evidence job is already queued or running for this card.",
                ),
            )

        job = create_card_job(
            session,
            claim_card=card,
            job_type=JobType.WEB_EVIDENCE,
        )
        job_runner.enqueue(job.id)
        return job

    @app.get("/api/cards/{card_id}", response_model=ClaimCardDetailRead)
    def get_card(card_id: str, session: Session = Depends(get_session)) -> ClaimCard:
        card = session.get(ClaimCard, card_id)
        if card is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("card_not_found", "Card not found."),
            )
        return card

    @app.get("/api/jobs/{job_id}", response_model=JobRead)
    def get_job(job_id: str, session: Session = Depends(get_session)) -> Job:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("job_not_found", "Job not found."),
            )
        return job

    @app.post(
        "/api/jobs/{job_id}/retry",
        response_model=JobRead,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def retry_failed_job(job_id: str, session: Session = Depends(get_session)) -> Job:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_detail("job_not_found", "Job not found."),
            )

        try:
            retried = retry_job(session, job)
            job_runner.enqueue(retried.id)
            return retried
        except ValueError as exc:
            if str(exc) == "job_not_failed":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=error_detail(
                        "job_not_failed",
                        "Only failed jobs can be retried.",
                    ),
                ) from exc
            raise

    return app


app = create_app()
