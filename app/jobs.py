from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from app.access import (
    DEFAULT_ACCESS_CONTEXT,
    AccessContext,
    DocumentVisibility,
)
from app.observability import TRACER, tenant_hash
from app.schemas import IngestionJobKind, IngestionJobRecord, SyncReport

JobHandler = Callable[
    [IngestionJobRecord, Callable[[int, str], None]],
    str | None,
]
LOGGER = logging.getLogger("atlas.jobs")


class JobStateError(ValueError):
    pass


class JobCancelled(RuntimeError):
    pass


class PermanentJobError(RuntimeError):
    pass


class IngestionJobStore:
    def __init__(self, database_path: Path, input_root: Path) -> None:
        self.database_path = database_path
        self.input_root = input_root
        database_path.parent.mkdir(parents=True, exist_ok=True)
        input_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    status TEXT NOT NULL,
                    progress INTEGER NOT NULL,
                    stage TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    collection_name TEXT NOT NULL,
                    source_uri TEXT NOT NULL,
                    mime_type TEXT NOT NULL,
                    input_path TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    cancel_requested INTEGER NOT NULL,
                    error_type TEXT,
                    error_message TEXT,
                    document_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    tenant_id TEXT NOT NULL DEFAULT 'demo',
                    owner_principal_id TEXT NOT NULL DEFAULT 'demo-user',
                    visibility TEXT NOT NULL DEFAULT 'tenant',
                    allowed_principals TEXT NOT NULL DEFAULT '[]',
                    allowed_groups TEXT NOT NULL DEFAULT '[]',
                    idempotency_scoped INTEGER NOT NULL DEFAULT 0,
                    kind TEXT NOT NULL DEFAULT 'upload',
                    connector_name TEXT NOT NULL DEFAULT '',
                    connector_instance TEXT NOT NULL DEFAULT '',
                    config_json TEXT,
                    result_json TEXT
                )
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(ingestion_jobs)"
                ).fetchall()
            }
            additions = {
                "tenant_id": "TEXT NOT NULL DEFAULT 'demo'",
                "owner_principal_id": "TEXT NOT NULL DEFAULT 'demo-user'",
                "visibility": "TEXT NOT NULL DEFAULT 'tenant'",
                "allowed_principals": "TEXT NOT NULL DEFAULT '[]'",
                "allowed_groups": "TEXT NOT NULL DEFAULT '[]'",
                "idempotency_scoped": "INTEGER NOT NULL DEFAULT 0",
                "kind": "TEXT NOT NULL DEFAULT 'upload'",
                "connector_name": "TEXT NOT NULL DEFAULT ''",
                "connector_instance": "TEXT NOT NULL DEFAULT ''",
                "config_json": "TEXT",
                "result_json": "TEXT",
            }
            for name, definition in additions.items():
                if name not in columns:
                    connection.execute(
                        f"ALTER TABLE ingestion_jobs ADD COLUMN {name} {definition}"
                    )
            connection.execute(
                """
                UPDATE ingestion_jobs
                SET idempotency_key = length(tenant_id) || ':' || tenant_id || ':'
                                      || length(owner_principal_id) || ':'
                                      || owner_principal_id || ':'
                                      || idempotency_key,
                    idempotency_scoped = 1
                WHERE idempotency_key IS NOT NULL AND idempotency_scoped = 0
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ingestion_jobs_queue
                ON ingestion_jobs (status, created_at)
                """
            )

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

    def healthcheck(self) -> bool:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return self.input_root.exists()

    def create(
        self,
        *,
        job_id: str,
        idempotency_key: str | None,
        filename: str,
        collection: str,
        source_uri: str,
        mime_type: str,
        input_path: Path | None,
        max_attempts: int,
        kind: IngestionJobKind = "upload",
        connector_name: str = "",
        connector_instance: str = "",
        config: dict[str, object] | None = None,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
        visibility: DocumentVisibility = "tenant",
        allowed_principals: tuple[str, ...] = (),
        allowed_groups: tuple[str, ...] = (),
    ) -> tuple[IngestionJobRecord, bool]:
        now = datetime.now(UTC).isoformat()
        scoped_idempotency_key = self._scoped_idempotency_key(
            access,
            idempotency_key,
        )
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO ingestion_jobs (
                        id, idempotency_key, status, progress, stage, filename,
                        collection_name, source_uri, mime_type, input_path,
                        attempts, max_attempts, cancel_requested, created_at,
                        updated_at, tenant_id, owner_principal_id, visibility,
                        allowed_principals, allowed_groups, idempotency_scoped,
                        kind, connector_name, connector_instance, config_json
                    ) VALUES (?, ?, 'queued', 0, 'queued', ?, ?, ?, ?, ?, 0, ?, 0,
                              ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        scoped_idempotency_key,
                        filename,
                        collection,
                        source_uri,
                        mime_type,
                        str(input_path) if input_path is not None else "",
                        max_attempts,
                        now,
                        now,
                        access.tenant_id,
                        access.principal_id,
                        visibility,
                        json.dumps(allowed_principals),
                        json.dumps(allowed_groups),
                        kind,
                        connector_name,
                        connector_instance,
                        json.dumps(config) if config is not None else None,
                    ),
                )
        except sqlite3.IntegrityError:
            if not idempotency_key:
                raise
            existing = self.get_by_idempotency_key(idempotency_key, access)
            if existing is None:
                raise
            return existing, False
        created = self.get(job_id)
        if created is None:
            raise RuntimeError("Created ingestion job could not be read back.")
        return created, True

    def get(self, job_id: str) -> IngestionJobRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return self._to_record(row) if row else None

    def get_by_idempotency_key(
        self,
        key: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> IngestionJobRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_jobs WHERE idempotency_key = ?",
                (self._scoped_idempotency_key(access, key),),
            ).fetchone()
        return self._to_record(row) if row else None

    def get_for_access(
        self,
        job_id: str,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> IngestionJobRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM ingestion_jobs
                WHERE id = ? AND tenant_id = ? AND owner_principal_id = ?
                """,
                (job_id, access.tenant_id, access.principal_id),
            ).fetchone()
        return self._to_record(row) if row else None

    def list(
        self,
        limit: int = 50,
        access: AccessContext = DEFAULT_ACCESS_CONTEXT,
    ) -> list[IngestionJobRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM ingestion_jobs
                WHERE tenant_id = ? AND owner_principal_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (access.tenant_id, access.principal_id, limit),
            ).fetchall()
        return [self._to_record(row) for row in rows]

    @staticmethod
    def _scoped_idempotency_key(
        access: AccessContext,
        key: str | None,
    ) -> str | None:
        if not key:
            return None
        return (
            f"{len(access.tenant_id)}:{access.tenant_id}:"
            f"{len(access.principal_id)}:{access.principal_id}:{key}"
        )

    def claim_next(self) -> IngestionJobRecord | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id FROM ingestion_jobs
                WHERE status = 'queued' AND cancel_requested = 0
                ORDER BY created_at, id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            now = datetime.now(UTC).isoformat()
            claimed = connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'running', stage = 'starting', attempts = attempts + 1,
                    progress = 5, started_at = ?, finished_at = NULL, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, row["id"]),
            )
            if claimed.rowcount != 1:
                return None
        return self.get(str(row["id"]))

    def update_progress(self, job_id: str, progress: int, stage: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE ingestion_jobs
                SET progress = ?, stage = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    max(0, min(progress, 99)),
                    stage,
                    datetime.now(UTC).isoformat(),
                    job_id,
                ),
            )

    def succeed(self, job_id: str, document_id: str | None) -> IngestionJobRecord:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            updated = connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'succeeded', progress = 100, stage = 'complete',
                    document_id = ?, error_type = NULL, error_message = NULL,
                    cancel_requested = 0, finished_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (document_id, now, now, job_id),
            )
            if updated.rowcount != 1:
                raise JobStateError("Only a running job can succeed.")
        return self._require(job_id)

    def fail(
        self,
        job_id: str,
        *,
        error_type: str,
        error_message: str,
        permanent: bool = False,
    ) -> IngestionJobRecord:
        current = self._require(job_id)
        terminal = permanent or current.attempts >= current.max_attempts
        status = "dead_letter" if terminal else "failed"
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = ?, stage = ?, error_type = ?, error_message = ?,
                    finished_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (
                    status,
                    status,
                    error_type[:120],
                    error_message[:1000],
                    now,
                    now,
                    job_id,
                ),
            )
        return self._require(job_id)

    def request_cancel(self, job_id: str) -> IngestionJobRecord:
        current = self._require(job_id)
        now = datetime.now(UTC).isoformat()
        if current.status in {"succeeded", "cancelled"}:
            raise JobStateError(f"A {current.status} job cannot be cancelled.")
        with self._connect() as connection:
            if current.status in {"queued", "failed", "dead_letter"}:
                connection.execute(
                    """
                    UPDATE ingestion_jobs
                    SET status = 'cancelled', stage = 'cancelled',
                        cancel_requested = 1, finished_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now, now, job_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE ingestion_jobs
                    SET cancel_requested = 1, stage = 'cancelling', updated_at = ?
                    WHERE id = ? AND status = 'running'
                    """,
                    (now, job_id),
                )
        return self._require(job_id)

    def mark_cancelled(self, job_id: str) -> IngestionJobRecord:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'cancelled', stage = 'cancelled',
                    cancel_requested = 1, finished_at = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (now, now, job_id),
            )
        return self._require(job_id)

    def retry(self, job_id: str) -> IngestionJobRecord:
        current = self._require(job_id)
        if current.status != "failed":
            raise JobStateError("Only a failed job can be retried.")
        if current.attempts >= current.max_attempts:
            raise JobStateError("The job exhausted its automatic retry budget.")
        return self._requeue(job_id, reset_attempts=False)

    def replay(self, job_id: str) -> IngestionJobRecord:
        current = self._require(job_id)
        if current.status != "dead_letter":
            raise JobStateError("Only a dead-letter job can be replayed.")
        return self._requeue(job_id, reset_attempts=True)

    def _requeue(
        self,
        job_id: str,
        *,
        reset_attempts: bool,
    ) -> IngestionJobRecord:
        attempts_sql = "attempts = 0," if reset_attempts else ""
        with self._connect() as connection:
            connection.execute(
                f"""
                UPDATE ingestion_jobs
                SET status = 'queued', stage = 'queued', progress = 0,
                    {attempts_sql}
                    cancel_requested = 0, error_type = NULL, error_message = NULL,
                    result_json = NULL,
                    started_at = NULL, finished_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (datetime.now(UTC).isoformat(), job_id),
            )
        return self._require(job_id)

    def recover_interrupted(self) -> int:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            cancelled_rows = connection.execute(
                """
                SELECT id FROM ingestion_jobs
                WHERE status = 'running' AND cancel_requested = 1
                """
            ).fetchall()
            cancelled = connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'cancelled', stage = 'cancelled',
                    error_type = NULL, error_message = NULL,
                    finished_at = ?, updated_at = ?
                WHERE status = 'running' AND cancel_requested = 1
                """,
                (now, now),
            ).rowcount
            dead_letters = connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'dead_letter', stage = 'dead_letter',
                    error_type = 'WorkerInterrupted',
                    error_message = 'Worker stopped after the retry budget was exhausted.',
                    finished_at = ?, updated_at = ?
                WHERE status = 'running' AND cancel_requested = 0
                    AND attempts >= max_attempts
                """,
                (now, now),
            ).rowcount
            recovered = connection.execute(
                """
                UPDATE ingestion_jobs
                SET status = 'queued', stage = 'recovered', progress = 0,
                    error_type = 'WorkerInterrupted',
                    error_message = 'Recovered after the previous worker stopped.',
                    started_at = NULL, finished_at = NULL, updated_at = ?
                WHERE status = 'running' AND cancel_requested = 0
                    AND attempts < max_attempts
                """,
                (now,),
            ).rowcount
        for row in cancelled_rows:
            job_id = str(row["id"])
            try:
                self.remove_input(job_id)
            except Exception as exc:
                self.record_cleanup_failure(job_id, str(exc))
        return cancelled + recovered + dead_letters

    def cancel_requested(self, job_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM ingestion_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        return bool(row["cancel_requested"]) if row else True

    def input_path(self, job_id: str) -> Path:
        raw = self._input_path_value(job_id)
        if not raw:
            raise JobStateError("This job has no retained input file.")
        return Path(raw)

    def _input_path_value(self, job_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT input_path FROM ingestion_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return str(row["input_path"] or "")

    def config(self, job_id: str) -> dict[str, object]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT config_json FROM ingestion_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return json.loads(row["config_json"]) if row["config_json"] else {}

    def set_result(self, job_id: str, report: SyncReport) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE ingestion_jobs SET result_json = ?, updated_at = ? WHERE id = ?",
                (
                    report.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                    job_id,
                ),
            )

    def remove_input(self, job_id: str) -> None:
        raw = self._input_path_value(job_id)
        if not raw:
            return
        job_directory = Path(raw).parent.resolve()
        input_root = self.input_root.resolve()
        if job_directory.parent == input_root and job_directory.exists():
            shutil.rmtree(job_directory)

    def record_cleanup_failure(
        self,
        job_id: str,
        message: str,
    ) -> IngestionJobRecord:
        current = self._require(job_id)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE ingestion_jobs
                SET stage = ?, error_type = 'InputCleanupError',
                    error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    f"{current.status}_cleanup_failed",
                    message[:1000],
                    datetime.now(UTC).isoformat(),
                    job_id,
                ),
            )
        return self._require(job_id)

    def _require(self, job_id: str) -> IngestionJobRecord:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    @staticmethod
    def _to_record(row: sqlite3.Row) -> IngestionJobRecord:
        keys = row.keys()
        return IngestionJobRecord(
            id=row["id"],
            kind=row["kind"] if "kind" in keys else "upload",
            status=row["status"],
            progress=row["progress"],
            stage=row["stage"],
            filename=row["filename"],
            collection=row["collection_name"],
            source_uri=row["source_uri"],
            mime_type=row["mime_type"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            cancel_requested=bool(row["cancel_requested"]),
            error_type=row["error_type"],
            error_message=row["error_message"],
            document_id=row["document_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            started_at=(
                datetime.fromisoformat(row["started_at"])
                if row["started_at"]
                else None
            ),
            finished_at=(
                datetime.fromisoformat(row["finished_at"])
                if row["finished_at"]
                else None
            ),
            tenant_id=row["tenant_id"],
            owner_principal_id=row["owner_principal_id"],
            visibility=row["visibility"],
            allowed_principals=tuple(json.loads(row["allowed_principals"])),
            allowed_groups=tuple(json.loads(row["allowed_groups"])),
            connector_name=row["connector_name"] if "connector_name" in keys else "",
            connector_instance=(
                row["connector_instance"] if "connector_instance" in keys else ""
            ),
            sync_report=(
                SyncReport.model_validate_json(row["result_json"])
                if "result_json" in keys and row["result_json"]
                else None
            ),
        )


class IngestionJobRunner:
    def __init__(
        self,
        store: IngestionJobStore,
        handler: JobHandler,
        poll_seconds: float,
    ) -> None:
        self.store = store
        self.handler = handler
        self.poll_seconds = poll_seconds
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.store.recover_interrupted()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="atlas-ingestion-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> bool:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)
            stopped = not self._thread.is_alive()
            if stopped:
                self._thread = None
            return stopped
        return True

    def notify(self) -> None:
        self._wake.set()

    def run_once(self) -> IngestionJobRecord | None:
        job = self.store.claim_next()
        if job is None:
            return None
        span_context = TRACER.start_as_current_span("atlas.ingestion.job")
        span = span_context.__enter__()
        span.set_attribute("atlas.job.id", job.id)
        span.set_attribute("atlas.tenant_hash", tenant_hash(job.tenant_id))
        span.set_attribute("atlas.job.attempt", job.attempts)

        def progress(value: int, stage: str) -> None:
            if self.store.cancel_requested(job.id):
                raise JobCancelled("Cancellation requested.")
            self.store.update_progress(job.id, value, stage)

        try:
            document_id = self.handler(job, progress)
            completed = self.store.succeed(job.id, document_id)
            span.set_attribute("atlas.job.outcome", "succeeded")
            return self._cleanup_input(completed)
        except JobCancelled:
            cancelled = self.store.mark_cancelled(job.id)
            span.set_attribute("atlas.job.outcome", "cancelled")
            return self._cleanup_input(cancelled)
        except Exception as exc:
            span.record_exception(exc)
            span.set_attribute("atlas.job.outcome", "failed")
            if self.store.cancel_requested(job.id):
                cancelled = self.store.mark_cancelled(job.id)
                span.set_attribute("atlas.job.outcome", "cancelled")
                return self._cleanup_input(cancelled)
            reported_error = (
                exc.__cause__
                if isinstance(exc, PermanentJobError) and exc.__cause__
                else exc
            )
            return self.store.fail(
                job.id,
                error_type=type(reported_error).__name__,
                error_message=str(reported_error) or type(reported_error).__name__,
                permanent=isinstance(exc, PermanentJobError),
            )
        finally:
            span_context.__exit__(None, None, None)

    def _cleanup_input(self, job: IngestionJobRecord) -> IngestionJobRecord:
        try:
            self.store.remove_input(job.id)
            return job
        except Exception as exc:
            LOGGER.exception("Could not remove retained input for job %s", job.id)
            return self.store.record_cleanup_failure(job.id, str(exc))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = self.run_once()
            except Exception:
                LOGGER.exception("Ingestion worker loop failed")
                processed = None
            if processed is None:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()
