"""Command-line entry point for ingestion, evaluation, runs, and validation."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from procurement_desk.config import Settings, load_settings
from procurement_desk.evaluation.sample import evaluate_samples, write_sample_report
from procurement_desk.kb import (
    build_knowledge_base,
    load_label_file,
    load_threads,
    thread_coverage_summary,
    validate_threads_against_kb,
)
from procurement_desk.llm.provider import create_llm_provider
from procurement_desk.logging_utils import configure_logging, get_logger
from procurement_desk.orchestrator.graph import (
    EXTRACTOR_VERSION,
    GRAPH_VERSION,
    POLICY_VERSION,
)
from procurement_desk.orchestrator.runner import BatchRunner
from procurement_desk.output import (
    validate_submission,
    write_internal_decisions_jsonl,
    write_submission,
)

LOGGER = get_logger("procurement_desk.cli")


def _settings(args: argparse.Namespace) -> Settings:
    overrides: dict[str, object] = {}
    if getattr(args, "workers", None) is not None:
        overrides["max_workers"] = args.workers
    if getattr(args, "no_cache", False):
        overrides["cache_enabled"] = False
    settings = load_settings(**overrides)
    settings.ensure_directories()
    configure_logging(
        settings.log_level,
        json_output=settings.log_json,
        log_file=settings.artifacts_dir / "logs" / "procurement_desk.log",
    )
    return settings


def _load_kb(settings: Settings):
    return build_knowledge_base(settings.playbook_dir)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_ingest(args: argparse.Namespace) -> int:
    settings = _settings(args)
    settings.validate_paths()
    kb = _load_kb(settings)
    threads = load_threads(settings.data_dir / "threads.csv")
    errors = validate_threads_against_kb(threads, kb)
    coverage = thread_coverage_summary(threads, kb)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "playbook_dir": str(settings.playbook_dir),
        "playbook_hash": kb.source_hash,
        "counts": {
            "categories": len(kb.categories),
            "suppliers": len(kb.suppliers),
            "amendments": len(kb.amendments),
            "precedents": len(kb.precedents),
            "policies": len(kb.policies),
            "documents": len(kb.documents),
        },
        "supplier_status_counts": kb.status_counts(),
        "contract_override_counts": kb.contract_override_counts(),
        "threads": coverage,
        "validation_errors": errors,
        "documents": kb.documents,
        "categories": {
            key: value.model_dump(mode="json") for key, value in sorted(kb.categories.items())
        },
        "amendments": [a.model_dump(mode="json") for a in kb.amendments],
        "suppliers": {
            key: {
                "display_name": supplier.display_name,
                "status": supplier.status.value,
                "currency_rates": {
                    currency: str(rate)
                    for currency, rate in supplier.currency_rates.items()
                },
                "category_caps": {
                    category: str(cap)
                    for category, cap in supplier.category_caps.items()
                },
                "source_path": supplier.source_path,
            }
            for key, supplier in sorted(kb.suppliers.items())
        },
    }
    _write_json(settings.reports_dir / "playbook_completeness.json", payload)
    _write_json(
        settings.reports_dir / "data_validation.json",
        {
            "generated_at": payload["generated_at"],
            "threads": coverage,
            "validation_errors": errors,
            "sample_answers": "40 labelled rows available",
        },
    )
    _write_playbook_markdown(settings.reports_dir / "playbook_completeness.md", kb, coverage)
    print(json.dumps({"ok": not errors, "counts": payload["counts"], "threads": coverage}, indent=2))
    return 0 if not errors else 1


def _write_playbook_markdown(path: Path, kb, coverage: dict) -> None:
    lines = [
        "# Playbook Completeness Report",
        "",
        f"Playbook SHA-256: `{kb.source_hash}`",
        "",
        "| Section | Count |",
        "|---|---:|",
        f"| Categories | {len(kb.categories)} |",
        f"| Suppliers | {len(kb.suppliers)} |",
        f"| Amendments | {len(kb.amendments)} |",
        f"| Precedents | {len(kb.precedents)} |",
        f"| Policies | {len(kb.policies)} |",
        f"| Total documents | {len(kb.documents)} |",
        "",
        "## Thread coverage",
        "",
        f"- Rows: {coverage['rows']}",
        f"- Unique IDs: {coverage['unique_ids']}",
        f"- Categories used: {coverage['categories_used']}",
        f"- Suppliers used: {coverage['suppliers_used']}",
        f"- Date range: {coverage['date_min']} to {coverage['date_max']}",
        "",
        "## Categories",
        "",
        "| Slug | Normalized unit | GST | Target | Walk-away | R | beta | Approval |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for category in sorted(kb.categories.values(), key=lambda c: c.slug):
        lines.append(
            f"| {category.slug} | {category.normalized_unit} | {category.gst_rate} | "
            f"{category.target} | {category.walkaway} | {category.rounds} | "
            f"{category.beta} | {category.approval_limit} |"
        )
    lines += [
        "",
        "## Amendments",
        "",
        "| ID | Category | Effective from | Field | Amount |",
        "|---|---|---|---|---:|",
    ]
    for amendment in kb.amendments:
        lines.append(
            f"| {amendment.amendment_id} | {amendment.category_slug} | "
            f"{amendment.effective_from} | {amendment.field.value} | {amendment.amount} |"
        )
    lines += [
        "",
        "## Suppliers",
        "",
        "| Key | Display name | Status | Currency overrides | Category caps |",
        "|---|---|---|---|---|",
    ]
    for supplier in sorted(kb.suppliers.values(), key=lambda s: s.key):
        lines.append(
            f"| {supplier.key} | {supplier.display_name} | {supplier.status.value} | "
            f"{supplier.currency_rates} | {supplier.category_caps} |"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def cmd_show_thread(args: argparse.Namespace) -> int:
    settings = _settings(args)
    settings.validate_paths()
    kb = _load_kb(settings)
    threads = load_threads(settings.data_dir / "threads.csv")
    thread = next((t for t in threads if t.thread_id == args.thread_id), None)
    if thread is None:
        print(f"unknown thread id: {args.thread_id}", file=sys.stderr)
        return 2
    provider = create_llm_provider(settings)
    from procurement_desk.orchestrator.graph import ProcurementGraph

    graph = ProcurementGraph(
        kb,
        llm_provider=provider,
        run_id="show-thread",
        llm_mode=settings.llm_provider,
    )
    state = graph.run(thread)
    payload = {
        "thread": thread.model_dump(mode="json"),
        "analysis": state.get("analysis").model_dump(mode="json") if state.get("analysis") else None,
        "policy": state.get("policy").model_dump(mode="json") if state.get("policy") else None,
        "supplier": state.get("supplier").model_dump(mode="json") if state.get("supplier") else None,
        "security": state.get("security").model_dump(mode="json") if state.get("security") else None,
        "pricing": state.get("pricing").model_dump(mode="json") if state.get("pricing") else None,
        "decision": state.get("decision").model_dump(mode="json") if state.get("decision") else None,
        "audit": state.get("audit").model_dump(mode="json") if state.get("audit") else None,
        "final_label": state.get("final_label"),
        "outcome_status": state.get("outcome_status"),
        "errors": state.get("errors", []),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_evaluate_sample(args: argparse.Namespace) -> int:
    settings = _settings(args)
    settings.validate_paths()
    kb = _load_kb(settings)
    threads = load_threads(settings.data_dir / "sample_threads.csv")
    answers = load_label_file(settings.data_dir / "sample_answers.csv")
    provider = create_llm_provider(settings)
    evaluation = evaluate_samples(
        kb,
        threads,
        answers,
        llm_provider=provider,
        llm_mode=settings.llm_provider,
    )
    write_sample_report(
        evaluation,
        settings.reports_dir / "sample_evaluation.md",
        kb_hash=kb.source_hash,
        llm_mode=settings.llm_provider,
    )
    print(
        json.dumps(
            {
                "threads": len(threads),
                "correct": evaluation.correct,
                "incorrect": len(evaluation.mismatches),
                "accuracy": evaluation.accuracy,
                "mismatches": evaluation.mismatches,
                "report": str(settings.reports_dir / "sample_evaluation.md"),
            },
            indent=2,
        )
    )
    return 0 if not evaluation.mismatches else 1


def cmd_run(args: argparse.Namespace) -> int:
    settings = _settings(args)
    settings.validate_paths()
    kb = _load_kb(settings)
    threads = load_threads(settings.data_dir / "threads.csv")
    errors = validate_threads_against_kb(threads, kb)
    if errors:
        print(json.dumps({"error": "input validation failed", "details": errors[:20]}, indent=2))
        return 2
    provider = create_llm_provider(settings)
    run_id = args.run_id or "run-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    runner = BatchRunner(kb, settings, llm_provider=provider)
    try:
        result = runner.run(
            threads,
            run_id=run_id,
            resume=args.resume,
            fresh=args.fresh,
            max_workers=args.workers,
            limit=args.limit,
        )
    except ValueError as exc:
        print(f"run refused: {exc}", file=sys.stderr)
        return 2

    submission_path = args.output or (settings.output_dir / "submission.csv")
    submission_path = Path(submission_path)
    write_submission(submission_path, result.input_threads, result.outcomes)
    write_internal_decisions_jsonl(
        settings.output_dir / "internal_decisions.jsonl", result.diagnostics_paths
    )
    validation = validate_submission(
        submission_path, result.input_threads, expected_rows=len(result.input_threads)
    )
    diagnostics = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "run_dir": str(result.run_dir),
        "submission_path": str(submission_path),
        "internal_decisions_path": str(settings.output_dir / "internal_decisions.jsonl"),
        "llm_mode": settings.llm_provider,
        "kb_hash": kb.source_hash,
        "extractor_version": EXTRACTOR_VERSION,
        "policy_version": POLICY_VERSION,
        "graph_version": GRAPH_VERSION,
        "stats": result.stats,
        "validation": validation.to_dict(),
    }
    _write_json(settings.output_dir / "run_diagnostics.json", diagnostics)
    _write_full_run_report(
        settings.reports_dir / "full_run_summary.md",
        result=result,
        validation=validation,
        kb_hash=kb.source_hash,
        llm_mode=settings.llm_provider,
        submission_path=submission_path,
    )
    print(json.dumps(diagnostics, indent=2))
    return 0 if validation.passed else 1


def _write_full_run_report(
    path: Path,
    *,
    result,
    validation,
    kb_hash: str,
    llm_mode: str,
    submission_path: Path,
) -> None:
    lines = [
        "# Full Competition Run Summary",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Run id: `{result.run_id}`",
        f"- Run directory: `{result.run_dir}`",
        f"- Playbook hash: `{kb_hash}`",
        f"- LLM mode: `{llm_mode}`",
        f"- Threads: {len(result.outcomes)}",
        f"- Submission: `{submission_path}`",
        f"- Validation passed: **{validation.passed}**",
        "",
        "## Decision counts",
        "",
        "| ACTION:REASON | Count |",
        "|---|---:|",
    ]
    for key, count in sorted(result.stats.get("decision_counts", {}).items()):
        lines.append(f"| {key} | {count} |")
    lines += [
        "",
        "## Outcome status",
        "",
        "| Status | Count |",
        "|---|---:|",
    ]
    for key, count in sorted(result.stats.get("status_counts", {}).items()):
        lines.append(f"| {key} | {count} |")
    lines += [
        "",
        "## Validation checks",
        "",
    ]
    for check in validation.checks:
        lines.append(f"- PASS: {check}")
    for error in validation.errors:
        lines.append(f"- FAIL: {error}")
    lines += [
        "",
        "## Error rows",
        "",
    ]
    failures = result.stats.get("failures", [])
    if not failures:
        lines.append("- None.")
    else:
        for failure in failures:
            lines.append(
                f"- {failure.get('thread_id')}: {failure.get('error')}"
            )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def cmd_validate_submission(args: argparse.Namespace) -> int:
    settings = _settings(args)
    settings.validate_paths()
    threads = load_threads(settings.data_dir / "threads.csv")
    path = Path(args.submission or (settings.output_dir / "submission.csv"))
    result = validate_submission(path, threads)
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="procurement-desk",
        description="Multi-agent procurement negotiation decision engine",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--workers", type=int, default=None)
        p.add_argument("--no-cache", action="store_true")

    p_ingest = sub.add_parser("ingest", help="Parse/validate the playbook and CSVs")
    p_ingest.set_defaults(func=cmd_ingest)

    p_show = sub.add_parser("show-thread", help="Run and print one thread")
    p_show.add_argument("thread_id")
    add_common(p_show)
    p_show.set_defaults(func=cmd_show_thread)

    p_sample = sub.add_parser("evaluate-sample", help="Evaluate the 40 sample threads")
    add_common(p_sample)
    p_sample.set_defaults(func=cmd_evaluate_sample)

    p_run = sub.add_parser("run", help="Process the full dataset and write submission.csv")
    add_common(p_run)
    p_run.add_argument("--run-id", default=None)
    p_run.add_argument("--output", default=None)
    p_run.add_argument("--limit", type=int, default=None)
    p_run.add_argument("--resume", dest="resume", action="store_true", default=True)
    p_run.add_argument("--no-resume", dest="resume", action="store_false")
    p_run.add_argument("--fresh", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_validate = sub.add_parser("validate-submission", help="Validate the final CSV")
    p_validate.add_argument("--submission", default=None)
    p_validate.set_defaults(func=cmd_validate_submission)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:  # noqa: BLE001 - CLI must fail clearly
        LOGGER.exception("command failed")
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
