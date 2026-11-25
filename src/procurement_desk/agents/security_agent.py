"""Security Agent: prompt injection (whole thread) and banned terms (latest only)."""

from __future__ import annotations

from procurement_desk.models import SecurityAnalysis, ThreadAnalysis, ThreadRecord
from procurement_desk.security.banned_terms import detect_banned_terms
from procurement_desk.security.injection import detect_injection


class SecurityAgent:
    def analyze(self, thread: ThreadRecord, analysis: ThreadAnalysis) -> SecurityAnalysis:
        messages = analysis.messages
        injection_findings = detect_injection(messages)
        banned_findings = detect_banned_terms(analysis.latest_supplier_message)

        warnings: list[str] = []
        if injection_findings:
            warnings.append(
                f"prompt-injection patterns found in {len(injection_findings)} clause(s)"
            )
        if banned_findings:
            warnings.append(
                f"banned contractual term(s) found: "
                f"{sorted({f.rule_id for f in banned_findings})}"
            )

        return SecurityAnalysis(
            prompt_injection_detected=bool(injection_findings),
            injection_findings=injection_findings,
            banned_term_detected=bool(banned_findings),
            banned_term_findings=banned_findings,
            scanned_thread=True,
            latest_message_only_for_banned_terms=True,
            method="deterministic-context-rules",
            warnings=warnings,
        )
