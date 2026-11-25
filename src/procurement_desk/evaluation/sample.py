"""Evaluate the labelled 40-thread sample set and write an evidence report."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from procurement_desk.kb.playbook_parser import KnowledgeBase
from procurement_desk.models import ThreadOutcome, ThreadRecord
from procurement_desk.orchestrator.graph import ProcurementGraph


@dataclass
class SampleEvaluation:
    threads: list[ThreadRecord]
    answers: dict[str, str]
    outcomes: dict[str, ThreadOutcome]
    states: dict[str, dict]
    correct: int
    mismatches: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / len(self.threads) if self.threads else 0.0


def evaluate_samples(
    kb: KnowledgeBase,
    threads: list[ThreadRecord],
    answers: dict[str, str],
    *,
    llm_provider=None,
    llm_mode: str = "none",
    run_id: str = "sample-evaluation",
) -> SampleEvaluation:
    graph = ProcurementGraph(
        kb,
        llm_provider=llm_provider,
        run_id=run_id,
        llm_mode=llm_mode,
    )
    outcomes: dict[str, ThreadOutcome] = {}
    states: dict[str, dict] = {}
    mismatches: list[tuple[str, str, str]] = []
    correct = 0
    for thread in threads:
        state = graph.run(thread)
        decision = state["decision"]
        outcome = ThreadOutcome(
            thread_id=thread.thread_id,
            label=decision.label,
            action=decision.action,
            reason=decision.reason,
            counter_price=decision.counter_price,
            status=state.get("outcome_status", "ok"),
            error="; ".join(state.get("errors", [])) or None,
            audit_passed=bool(state.get("audit") and state["audit"].passed),
            execution=state["execution"],
        )
        outcomes[thread.thread_id] = outcome
        states[thread.thread_id] = state
        expected = answers[thread.thread_id]
        if outcome.label == expected:
            correct += 1
        else:
            mismatches.append((thread.thread_id, expected, outcome.label))
    return SampleEvaluation(
        threads=threads,
        answers=answers,
        outcomes=outcomes,
        states=states,
        correct=correct,
        mismatches=mismatches,
    )


def _confusion(rows: list[tuple[str, str]], level: int) -> list[list[int]]:
    labels = sorted({row[0].split(":")[level] for row in rows} | {row[1].split(":")[level] for row in rows})
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0 for _ in labels] for _ in labels]
    for expected, predicted in rows:
        matrix[index[expected.split(":")[level]]][index[predicted.split(":")[level]]] += 1
    return [labels, matrix]  # type: ignore[list-item]


def write_sample_report(
    evaluation: SampleEvaluation,
    path: Path,
    *,
    kb_hash: str,
    llm_mode: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        (evaluation.answers[t.thread_id], evaluation.outcomes[t.thread_id].label)
        for t in evaluation.threads
    ]
    action_labels, action_matrix = _confusion(rows, 0)
    reason_labels, reason_matrix = _confusion(rows, 1)
    lines: list[str] = []
    lines.append("# Sample Evaluation — The Procurement Desk")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"Playbook hash: `{kb_hash}`")
    lines.append(f"LLM mode: `{llm_mode}`")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- Threads evaluated: **{len(evaluation.threads)}**")
    lines.append(f"- Exact-match correct: **{evaluation.correct}**")
    lines.append(f"- Exact-match incorrect: **{len(evaluation.threads) - evaluation.correct}**")
    lines.append(f"- Exact-match accuracy: **{evaluation.accuracy:.2%}**")
    lines.append(
        "- Comparison key: `thread_id` from `sample_answers.csv` (not row position)."
    )
    lines.append("")
    lines.append("## Confusion by action")
    lines.append("")
    lines.append("| expected \\ predicted | " + " | ".join(action_labels) + " |")
    lines.append("|---|" + "---|" * len(action_labels))
    for label, row in zip(action_labels, action_matrix):
        lines.append(f"| **{label}** | " + " | ".join(str(v) for v in row) + " |")
    lines.append("")
    lines.append("## Confusion by full reason")
    lines.append("")
    lines.append("| expected \\ predicted | " + " | ".join(reason_labels) + " |")
    lines.append("|---|" + "---|" * len(reason_labels))
    for label, row in zip(reason_labels, reason_matrix):
        lines.append(f"| **{label}** | " + " | ".join(str(v) for v in row) + " |")
    lines.append("")
    lines.append("## Per-thread results")
    lines.append("")
    lines.append("| thread_id | category | supplier | round | qty | expected | predicted | status | audit |")
    lines.append("|---|---|---|---:|---:|---|---|---|---|")
    for thread in evaluation.threads:
        outcome = evaluation.outcomes[thread.thread_id]
        expected = evaluation.answers[thread.thread_id]
        status = "PASS" if outcome.label == expected else "FAIL"
        audit = "pass" if outcome.audit_passed else "fail"
        lines.append(
            f"| {thread.thread_id} | {thread.category} | {thread.supplier} | "
            f"{thread.round} | {thread.quantity} | `{expected}` | `{outcome.label}` | "
            f"{status} | {audit} |"
        )
    lines.append("")
    lines.append("## Mismatch investigation")
    lines.append("")
    if not evaluation.mismatches:
        lines.append(
            "No mismatches. Every sample label matched exactly and passed the independent audit."
        )
    else:
        lines.append(
            "Each mismatch below includes the source message, extracted facts, resolved policy, "
            "pricing trace, security findings, decision trace, and audit result."
        )
        lines.append("")
        for thread_id, expected, predicted in evaluation.mismatches:
            thread = next(t for t in evaluation.threads if t.thread_id == thread_id)
            state = evaluation.states[thread_id]
            lines.append(f"### {thread_id} — expected `{expected}`, predicted `{predicted}`")
            lines.append("")
            lines.append("**Supplier message**")
            lines.append("")
            lines.append("```text")
            lines.append(thread.supplier_message)
            lines.append("```")
            lines.append("")
            lines.append("**Resolved policy**")
            lines.append("")
            lines.append("```json")
            lines.append(
                state["policy"].model_dump_json(indent=2) if state.get("policy") else "null"
            )
            lines.append("```")
            lines.append("")
            lines.append("**Thread analysis / offer facts**")
            lines.append("")
            lines.append("```json")
            lines.append(
                state["analysis"].model_dump_json(indent=2) if state.get("analysis") else "null"
            )
            lines.append("```")
            lines.append("")
            lines.append("**Security findings**")
            lines.append("")
            lines.append("```json")
            lines.append(
                state["security"].model_dump_json(indent=2) if state.get("security") else "null"
            )
            lines.append("```")
            lines.append("")
            lines.append("**Pricing trace**")
            lines.append("")
            lines.append("```json")
            lines.append(
                state["pricing"].model_dump_json(indent=2) if state.get("pricing") else "null"
            )
            lines.append("```")
            lines.append("")
            lines.append("**Decision trace**")
            lines.append("")
            lines.append("```json")
            lines.append(
                state["decision"].model_dump_json(indent=2) if state.get("decision") else "null"
            )
            lines.append("```")
            lines.append("")
            lines.append("**Audit**")
            lines.append("")
            lines.append("```json")
            lines.append(
                state["audit"].model_dump_json(indent=2) if state.get("audit") else "null"
            )
            lines.append("```")
            lines.append("")
    lines.append("## Error categories")
    lines.append("")
    if not evaluation.mismatches:
        lines.append("- None.")
    else:
        counts = Counter()
        for thread_id, expected, predicted in evaluation.mismatches:
            state = evaluation.states[thread_id]
            analysis = state.get("analysis")
            pricing = state.get("pricing")
            if analysis is not None and analysis.missing_information:
                counts["missing-information extraction"] += 1
            elif any(
                security_attr
                for security_attr in (
                    state.get("security") and state["security"].prompt_injection_detected,
                    state.get("security") and state["security"].banned_term_detected,
                )
            ):
                counts["security classification"] += 1
            elif pricing is None or pricing.normalized_price is None:
                counts["pricing/normalization"] += 1
            else:
                counts["decision/precedence/threshold"] += 1
        for key, value in counts.most_common():
            lines.append(f"- {key}: {value}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
