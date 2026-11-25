"""Context-aware prompt-injection detection.

The detector scans every message in a thread.  It is deliberately stricter than
a bag-of-words keyword scan: ordinary business phrases such as "AI-powered",
"ERP system", "system integration team", and "assistant manager" are neutralised
before command-oriented rules are evaluated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from procurement_desk.models import Message, MessageRole, SecurityEvidence
from procurement_desk.security.normalization import normalise_untrusted_text

RULE_IDS = {
    "bot_directive": "directive aimed at a bot/screening system",
    "model_directive": "directive aimed at a language model/AI",
    "assistant_reviewer": "directive aimed at a reviewer/assistant/automated system",
    "admin_override": "admin override or playbook-bypass instruction",
    "ignore_instructions": "instruction to ignore previous rules/instructions",
    "approval_claim": "claim of pre-approval/approval already granted aimed at the decision channel",
    "output_accept": "explicit instruction to output ACCEPT/mark accepted",
    "multilingual_directive": "multilingual AI/assistant directive",
}

ALLOWED_BUSINESS_PHRASES = (
    r"AI[\s-]*powered",
    r"system[\s-]+integration(?:\s+team)?",
    r"ERP\s+system",
    r"assistant\s+manager",
    r"customer\s+assistant",
    r"virtual\s+assistant\s+product",
    r"automated\s+invoice(?:ing)?",
)

_WHITESPACE_RE = re.compile(r"\s+")
_CLAUSE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")

_BOT_RE = re.compile(r"\b(?:bots?|chatbots?|screening\s+bot)\b", re.IGNORECASE)
_MODEL_RE = re.compile(
    r"\b(?:LLMs?|language\s+model|AI\s+agent|AI\s+assistant|AI\s+model|model|AI)\b",
    re.IGNORECASE,
)
_REVIEWER_RE = re.compile(
    r"\b(?:automated\s+system|system|reviewer|reviewing\s+assistant|assistant)\b",
    re.IGNORECASE,
)
_ACTION_RE = re.compile(
    r"\b(?:accept|accepted|approve|approved|approval|pre-?approved|"
    r"mark|record|set|output|sign\s*off|signed\s*off|decision)\b",
    re.IGNORECASE,
)
_OVERRIDE_RE = re.compile(
    r"(?:\[?\s*admin\s+override\s*\]?|\boverride\b[^.\n]{0,100}"
    r"\b(?:accept|approve|action|decision|check|playbook)\b|"
    r"\bskip\b[^.\n]{0,80}\b(?:playbook|checks?|approval)\b)",
    re.IGNORECASE,
)
_IGNORE_RE = re.compile(
    r"\b(?:ignore|disregard|forget)\b[^.\n]{0,80}"
    r"\b(?:previous|prior|above|earlier)?\s*(?:instructions?|prompts?|rules?)\b",
    re.IGNORECASE,
)
_APPROVAL_CLAIM_RE = re.compile(
    r"\b(?:already\s+approved|approval\s+(?:has|was|is)?\s*(?:already\s+)?"
    r"(?:been\s+)?granted|pre-?approved|CFO\s+(?:has\s+)?already\s+signed\s+off|"
    r"already\s+signed\s+off|decision\s+as\s+approved)\b",
    re.IGNORECASE,
)
_OUTPUT_ACCEPT_RE = re.compile(
    r"\b(?:output|mark|record|set\s+action\s*=|action\s*=)\b[^.\n]{0,50}"
    r"\b(?:ACCEPT|ACCEPTED|approved)\b",
    re.IGNORECASE,
)
_MULTILINGUAL_RE = re.compile(
    r"(?:AI\s*सहायक|सहायक\s+के\s+लिए\s+निर्देश|निर्देश[^\n]{0,80}(?:ACCEPT|स्वीकार)|"
    r"(?:ignora|ignorar|ignorez|ignorieren)[^\n]{0,80}"
    r"(?:instrucciones|instructions|consignes|anweisungen)|"
    r"(?:aprueba|aprobar|approuver|genehmigen)[^\n]{0,80})",
    re.IGNORECASE,
)
_MULTILINGUAL_IGNORE_RE = re.compile(
    r"ignore|ignora|ignorez|ignorieren|ignorar|ignoriere|negeer|negeren|"
    r"忽略|無視|무시|игнор|تجاهل|अनदेखा|अवहेलना",
    re.IGNORECASE,
)
_MULTILINGUAL_ACTION_RE = re.compile(
    r"accept|accepted|approve|approved|接受|承諾|承诺|수락|승인|примите|одобр|"
    r"اقبل|وافق|स्वीकार|स्वीकृत|acepta|aceite|acceptez|akzeptieren|genehmigen|"
    r"accetta|accettare|受け入れ",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class InjectionMatch:
    rule_id: str
    matched_text: str
    detail: str


def _neutralise_allowed(text: str) -> str:
    result = text
    for pattern in ALLOWED_BUSINESS_PHRASES:
        result = re.sub(pattern, " ", result, flags=re.IGNORECASE)
    return result


def _clauses(text: str) -> list[str]:
    return [clause.strip() for clause in _CLAUSE_SPLIT_RE.split(text) if clause.strip()]


def detect_injection_in_text(text: str) -> list[InjectionMatch]:
    """Find injection clauses in one message/text block."""

    findings: list[InjectionMatch] = []
    text = normalise_untrusted_text(text)
    for clause in _clauses(text):
        neutral = _neutralise_allowed(clause)
        lower = neutral.casefold()
        if not lower:
            continue

        if _BOT_RE.search(neutral) and _ACTION_RE.search(neutral):
            findings.append(
                InjectionMatch(
                    rule_id="bot_directive",
                    matched_text=clause,
                    detail=RULE_IDS["bot_directive"],
                )
            )
        if _MODEL_RE.search(neutral) and _ACTION_RE.search(neutral):
            findings.append(
                InjectionMatch(
                    rule_id="model_directive",
                    matched_text=clause,
                    detail=RULE_IDS["model_directive"],
                )
            )
        if _REVIEWER_RE.search(neutral) and _ACTION_RE.search(neutral):
            findings.append(
                InjectionMatch(
                    rule_id="assistant_reviewer",
                    matched_text=clause,
                    detail=RULE_IDS["assistant_reviewer"],
                )
            )
        if _OVERRIDE_RE.search(neutral):
            findings.append(
                InjectionMatch(
                    rule_id="admin_override",
                    matched_text=clause,
                    detail=RULE_IDS["admin_override"],
                )
            )
        if _IGNORE_RE.search(neutral):
            findings.append(
                InjectionMatch(
                    rule_id="ignore_instructions",
                    matched_text=clause,
                    detail=RULE_IDS["ignore_instructions"],
                )
            )
        if _APPROVAL_CLAIM_RE.search(neutral) and not re.search(
            r"\b(?:not|no)\b[^.]{0,25}\b(?:pre-?approved|approval\s+already)\b",
            neutral,
            re.IGNORECASE,
        ):
            findings.append(
                InjectionMatch(
                    rule_id="approval_claim",
                    matched_text=clause,
                    detail=RULE_IDS["approval_claim"],
                )
            )
        if _OUTPUT_ACCEPT_RE.search(neutral):
            findings.append(
                InjectionMatch(
                    rule_id="output_accept",
                    matched_text=clause,
                    detail=RULE_IDS["output_accept"],
                )
            )
        if _MULTILINGUAL_RE.search(neutral) or (
            _MULTILINGUAL_IGNORE_RE.search(neutral)
            and _MULTILINGUAL_ACTION_RE.search(neutral)
        ):
            findings.append(
                InjectionMatch(
                    rule_id="multilingual_directive",
                    matched_text=clause,
                    detail=RULE_IDS["multilingual_directive"],
                )
            )
    return findings


def detect_injection(messages: list[Message]) -> list[SecurityEvidence]:
    evidence: list[SecurityEvidence] = []
    seen: set[tuple[str, str]] = set()
    for message in messages:
        for match in detect_injection_in_text(message.text):
            key = (match.rule_id, _WHITESPACE_RE.sub(" ", match.matched_text))
            if key in seen:
                continue
            seen.add(key)
            evidence.append(
                SecurityEvidence(
                    rule_id=match.rule_id,
                    category="prompt_injection",
                    matched_text=match.matched_text,
                    message_index=message.index,
                    message_role=message.role,
                    detail=match.detail,
                )
            )
    return evidence
