"""Extraction cache and batch runner with checkpoint/resume support."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from procurement_desk.agents.thread_analyst import ThreadAnalyst
from procurement_desk.config import Settings
from procurement_desk.kb.playbook_parser import KnowledgeBase
from procurement_desk.models import (
    Action,
    AuditResult,
    Decision,
    ExecutionMetadata,
    ReasonCode,
    ThreadAnalysis,
    ThreadDiagnostics,
    ThreadOutcome,
    ThreadRecord,
)
from procurement_desk.orchestrator.graph import (
    EXTRACTOR_VERSION,
    GRAPH_VERSION,
    POLICY_VERSION,
    SAFE_FALLBACK_LABEL,
    ProcurementGraph,
)
from procurement_desk.output.submission import label_is_valid

RUN_FORMAT_VERSION = "1.0"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    last_error: OSError | None = None
    for attempt in range(6):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            # Windows antivirus/indexers can briefly lock a just-written file.
            last_error = exc
            time.sleep(0.02 * (attempt + 1))
    raise last_error  # type: ignore[misc]


def atomic_write_json(path: Path, payload: dict) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))


class CachedThreadAnalyst:
    """Cache validated ThreadAnalysis results by content and policy version."""

    def __init__(
        self,
        base: ThreadAnalyst,
        *,
        cache_dir: Path,
        kb_hash: str,
        llm_mode: str,
        enabled: bool = True,
    ) -> None:
        self.base = base
        self.cache_dir = cache_dir
        self.kb_hash = kb_hash
        self.llm_mode = llm_mode
        self.enabled = enabled

    def _key(self, thread: ThreadRecord) -> str:
        payload = {
            "thread_id": thread.thread_id,
            "date": thread.date.isoformat(),
            "supplier": thread.supplier,
            "category": thread.category,
            "quantity": thread.quantity,
            "round": thread.round,
            "message": thread.supplier_message,
            "kb_hash": self.kb_hash,
            "extractor_version": EXTRACTOR_VERSION,
            "llm_mode": self.llm_mode,
        }
        return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))

    def _path(self, key: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}.json"

    def analyze(self, thread: ThreadRecord) -> ThreadAnalysis:
        if not self.enabled:
            return self.base.analyze(thread)
        key = self._key(thread)
        path = self._path(key)
        if path.exists():
            try:
                analysis = ThreadAnalysis.model_validate_json(path.read_text(encoding="utf-8"))
                if analysis.thread_id == thread.thread_id:
                    return analysis
            except Exception:
                # Corrupt cache entries are ignored, never used as facts.
                pass
        analysis = self.base.analyze(thread)
        try:
            atomic_write_text(path, analysis.model_dump_json(indent=2))
        except OSError:
            pass
        return analysis


@dataclass
class BatchRunResult:
    run_id: str
    run_dir: Path
    input_threads: list[ThreadRecord]
    outcomes: list[ThreadOutcome]
    diagnostics_paths: list[Path]
    stats: dict


class BatchRunner:
    def __init__(
        self,
        kb: KnowledgeBase,
        settings: Settings,
        *,
        llm_provider=None,
        cache_enabled: bool | None = None,
    ) -> None:
        self.kb = kb
        self.settings = settings
        self.llm_provider = llm_provider
        self.cache_enabled = (
            settings.cache_enabled if cache_enabled is None else cache_enabled
        )
        self.llm_mode = settings.llm_provider
        self._progress_lock = threading.Lock()

    def run(
        self,
        threads: Iterable[ThreadRecord],
        *,
        run_id: str,
        resume: bool = True,
        fresh: bool = False,
        max_workers: int | None = None,
        limit: int | None = None,
    ) -> BatchRunResult:
        thread_list = list(threads)
        if limit is not None:
            thread_list = thread_list[:limit]
        if not thread_list:
            raise ValueError("no threads to process")
        run_dir = self.settings.artifacts_dir / "runs" / run_id
        thread_dir = run_dir / "threads"
        cache_dir = self.settings.artifacts_dir / "cache" / "extractions"
        thread_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)

        input_hash = sha256_text(
            "\n".join(t.model_dump_json() for t in thread_list)
        )
        metadata_path = run_dir / "run_metadata.json"
        metadata: dict = {
            "run_id": run_id,
            "run_format_version": RUN_FORMAT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input_hash": input_hash,
            "kb_hash": self.kb.source_hash,
            "input_rows": len(thread_list),
            "llm_mode": self.llm_mode,
            "extractor_version": EXTRACTOR_VERSION,
            "policy_version": POLICY_VERSION,
            "graph_version": GRAPH_VERSION,
            "cache_enabled": self.cache_enabled,
            "max_workers": max_workers or self.settings.max_workers,
        }

        existing_keys = set()
        if not fresh and resume and metadata_path.exists():
            previous = json.loads(metadata_path.read_text(encoding="utf-8"))
            if previous.get("input_hash") != input_hash:
                raise ValueError(
                    "cannot resume: input rows/hash differ from the existing run. "
                    "Use a new run id or set fresh=True."
                )
            if previous.get("kb_hash") != self.kb.source_hash:
                raise ValueError(
                    "cannot resume: playbook hash differs from the existing run"
                )
            for path in thread_dir.glob("*.json"):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    outcome = ThreadOutcome.model_validate(payload["outcome"])
                    if (
                        outcome.thread_id == path.stem
                        and outcome.status in {"ok", "recovered"}
                        and label_is_valid(outcome.label)
                    ):
                        existing_keys.add(path.stem)
                except Exception:
                    # An incomplete/corrupt checkpoint is retried, not trusted.
                    continue
        elif not fresh and not resume and metadata_path.exists():
            raise ValueError(
                "run id already exists; use resume=True, fresh=True, or a new run id"
            )
        elif fresh:
            # Remove only this run's checkpoint files, never supplied data.
            for path in thread_dir.glob("*.json"):
                path.unlink()
        atomic_write_json(metadata_path, metadata)

        analyst = CachedThreadAnalyst(
            ThreadAnalyst(self.kb, llm_provider=self.llm_provider),
            cache_dir=cache_dir,
            kb_hash=self.kb.source_hash,
            llm_mode=self.llm_mode,
            enabled=self.cache_enabled,
        )
        graph = ProcurementGraph(
            self.kb,
            llm_provider=self.llm_provider,
            thread_analyst=analyst,
            run_id=run_id,
            llm_mode=self.llm_mode,
        )

        pending = [t for t in thread_list if t.thread_id not in existing_keys]
        completed = 0
        skipped = len(thread_list) - len(pending)
        failures: list[dict] = []
        decision_counts: dict[str, int] = {}
        start = time.perf_counter()
        progress_path = run_dir / "progress.json"

        def record_progress() -> None:
            with self._progress_lock:
                try:
                    atomic_write_json(
                        progress_path,
                        {
                            "completed": completed,
                            "skipped_existing": skipped,
                            "total": len(thread_list),
                            "pending_at_last_update": len(pending) - completed,
                            "failures": failures[-50:],
                            "decision_counts": decision_counts,
                        },
                    )
                except OSError:
                    # Progress metadata is diagnostic; it must never abort a batch.
                    pass

        record_progress()

        def execute(thread: ThreadRecord) -> tuple[str, ThreadOutcome, Path, dict]:
            try:
                state = graph.run(thread)
                outcome, diagnostics = self._build_records(thread, state, run_id)
                path = thread_dir / f"{thread.thread_id}.json"
                atomic_write_json(
                    path,
                    {
                        "outcome": outcome.model_dump(mode="json"),
                        "diagnostics": diagnostics.model_dump(mode="json"),
                    },
                )
                return thread.thread_id, outcome, path, {"status": outcome.status}
            except Exception as exc:  # noqa: BLE001 - every row must receive a label
                outcome, diagnostics = self._error_records(thread, exc, run_id)
                path = thread_dir / f"{thread.thread_id}.json"
                atomic_write_json(
                    path,
                    {
                        "outcome": outcome.model_dump(mode="json"),
                        "diagnostics": diagnostics.model_dump(mode="json"),
                    },
                )
                return thread.thread_id, outcome, path, {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }

        workers = min(max_workers or self.settings.max_workers, max(1, len(pending)))
        if pending:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(execute, thread): thread for thread in pending}
                for future in as_completed(futures):
                    thread = futures[future]
                    try:
                        _, outcome, _, info = future.result()
                    except Exception as exc:  # defensive; execute already catches
                        outcome = self._fallback_outcome(thread, f"{type(exc).__name__}: {exc}", run_id)
                        info = {"status": "error", "error": str(exc)}
                    completed += 1
                    key = f"{outcome.action.value}:{outcome.reason.value}"
                    decision_counts[key] = decision_counts.get(key, 0) + 1
                    if info.get("status") == "error":
                        failures.append({"thread_id": thread.thread_id, "error": info.get("error")})
                    record_progress()

        # Assemble in input order; load checkpoints.  Any missing/corrupt row gets
        # an explicit error fallback rather than being silently dropped.
        outcomes: list[ThreadOutcome] = []
        diagnostics_paths: list[Path] = []
        counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        error_count = 0
        for thread in thread_list:
            path = thread_dir / f"{thread.thread_id}.json"
            outcome: ThreadOutcome | None = None
            if path.exists():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    outcome = ThreadOutcome.model_validate(payload["outcome"])
                except Exception as exc:
                    outcome = self._fallback_outcome(
                        thread, f"corrupt checkpoint: {type(exc).__name__}: {exc}", run_id
                    )
            else:
                outcome = self._fallback_outcome(thread, "missing checkpoint", run_id)
            outcomes.append(outcome)
            diagnostics_paths.append(path)
            key = f"{outcome.action.value}:{outcome.reason.value}"
            counts[key] = counts.get(key, 0) + 1
            status_counts[outcome.status] = status_counts.get(outcome.status, 0) + 1
            if outcome.status in {"error", "fallback", "audit_failed"}:
                error_count += 1

        duration = time.perf_counter() - start
        metadata.update(
            {
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": round(duration, 3),
                "completed_rows": len(outcomes),
                "processed_now": completed,
                "existing_checkpoints_used": skipped + sum(
                    1 for o in outcomes if o.status == "ok" and o.execution.duration_ms == 0
                ),
                "decision_counts": dict(sorted(counts.items())),
                "status_counts": dict(sorted(status_counts.items())),
                "error_rows": error_count,
                "failures": failures[-100:],
                "input_order_preserved": True,
            }
        )
        try:
            atomic_write_json(metadata_path, metadata)
            atomic_write_json(progress_path, {
                "completed": len(outcomes),
                "total": len(thread_list),
                "failures": failures[-50:],
                "decision_counts": counts,
            })
        except OSError as exc:
            metadata["metadata_write_error"] = f"{type(exc).__name__}: {exc}"
        return BatchRunResult(
            run_id=run_id,
            run_dir=run_dir,
            input_threads=thread_list,
            outcomes=outcomes,
            diagnostics_paths=diagnostics_paths,
            stats=metadata,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _build_records(
        thread: ThreadRecord, state: dict, run_id: str
    ) -> tuple[ThreadOutcome, ThreadDiagnostics]:
        decision: Decision | None = state.get("decision")
        if decision is None:
            decision = BatchRunner._fallback_decision("workflow produced no decision")
        execution = state.get("execution") or ExecutionMetadata(
            run_id=run_id, started_at=datetime.now(timezone.utc)
        )
        errors = list(state.get("errors", []))
        if decision.error:
            errors.append(decision.error)
        status = state.get("outcome_status") or "ok"
        if state.get("fallback_used") and status not in {"recovered", "ok"}:
            status = "fallback"
        audit = state.get("audit")
        outcome = ThreadOutcome(
            thread_id=thread.thread_id,
            label=decision.label,
            action=decision.action,
            reason=decision.reason,
            counter_price=decision.counter_price,
            status=status,
            error="; ".join(errors) if errors else None,
            audit_passed=bool(audit and audit.passed),
            execution=execution,
        )
        warnings: list[str] = []
        for key in ("analysis", "policy", "supplier", "security", "pricing"):
            value = state.get(key)
            if value is not None and hasattr(value, "warnings"):
                warnings.extend(value.warnings)
        diagnostics = ThreadDiagnostics(
            thread=thread,
            analysis=state.get("analysis"),
            policy=state.get("policy"),
            supplier=state.get("supplier"),
            security=state.get("security"),
            pricing=state.get("pricing"),
            decision=decision,
            audit=audit,
            errors=errors,
            warnings=warnings,
        )
        return outcome, diagnostics

    @staticmethod
    def _error_records(
        thread: ThreadRecord, exc: Exception, run_id: str
    ) -> tuple[ThreadOutcome, ThreadDiagnostics]:
        message = f"{type(exc).__name__}: {exc}"
        outcome = BatchRunner._fallback_outcome(thread, message, run_id, status="error")
        diagnostics = ThreadDiagnostics(thread=thread, errors=[message])
        return outcome, diagnostics

    @staticmethod
    def _fallback_outcome(
        thread: ThreadRecord,
        error: str,
        run_id: str,
        *,
        status: str = "fallback",
    ) -> ThreadOutcome:
        decision = BatchRunner._fallback_decision(error)
        execution = ExecutionMetadata(
            run_id=run_id,
            started_at=datetime.now(timezone.utc),
            fallback_used=True,
        )
        return ThreadOutcome(
            thread_id=thread.thread_id,
            label=decision.label,
            action=decision.action,
            reason=decision.reason,
            counter_price=None,
            status=status,  # type: ignore[arg-type]
            error=error,
            audit_passed=False,
            execution=execution,
        )

    @staticmethod
    def _fallback_decision(error: str) -> Decision:
        return Decision(
            action=Action.ESCALATE,
            reason=ReasonCode.MISSING_INFO,
            label=SAFE_FALLBACK_LABEL,
            error=error,
            precedence_trace=["batch fallback: safe missing-information escalation"],
            values={"fallback": "true"},
        )


def load_thread_outcomes(diagnostics_paths: list[Path]) -> list[ThreadOutcome]:
    outcomes: list[ThreadOutcome] = []
    for path in diagnostics_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        outcomes.append(ThreadOutcome.model_validate(payload["outcome"]))
    return outcomes
