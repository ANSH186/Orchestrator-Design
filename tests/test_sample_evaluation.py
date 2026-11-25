from __future__ import annotations

from procurement_desk.evaluation.sample import evaluate_samples


def test_sample_evaluation_is_perfect(kb, sample_threads, sample_answers):
    evaluation = evaluate_samples(
        kb,
        sample_threads,
        sample_answers,
        llm_mode="none",
        run_id="pytest-sample",
    )
    assert evaluation.correct == 40
    assert evaluation.mismatches == []
    assert all(
        outcome.audit_passed for outcome in evaluation.outcomes.values()
    )
    assert all(outcome.status == "ok" for outcome in evaluation.outcomes.values())
