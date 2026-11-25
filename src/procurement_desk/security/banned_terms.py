"""Context-aware banned-contract-term detection for the latest supplier message."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from procurement_desk.models import SecurityEvidence
from procurement_desk.security.normalization import normalise_untrusted_text

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+|\n+")

RENEWAL_ALLOWED_RE = re.compile(
    r"(?:\bno\b|\bnot\b|\bwithout\b)[^.]{0,40}\bautomatic\s+renewal\b|"
    r"\brenewal\s+only\s+(?:if|by|upon)\b|"
    r"\bonly\s+(?:if|by|upon)\s+(?:both|mutual)\b|"
    r"\bby\s+mutual\s+(?:agreement|consent)\b|"
    r"\bmutually\s+agreed\b|"
    r"\bno\s+automatic\s+renewal\b",
    re.IGNORECASE,
)
RENEWAL_BANNED_RE = re.compile(
    r"\bauto[-\s]?renews?\b|"
    r"\bautomatic(?:ally)?\s+renew(?:s|ed|al)?\b|"
    r"\brenews?\s+(?:automatically|on\s+its\s+own|by\s+itself)\b|"
    r"\bcontinues?\s+(?:from\s+)?year[-\s]to[-\s]year\b|"
    r"\bshall\s+renew\b|"
    r"\brenewed\s+automatically\b",
    re.IGNORECASE,
)

ADVANCE_RE = re.compile(
    r"\b(?:advance|upfront|up[-\s]front|deposit|prepay(?:ment)?|pre[-\s]?paid)\b",
    re.IGNORECASE,
)
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
FRACTION_WORDS: tuple[tuple[re.Pattern[str], Decimal], ...] = (
    (re.compile(r"\btwo[-\s]thirds?\b", re.IGNORECASE), Decimal("66.67")),
    (re.compile(r"\bone[-\s]third\b|\ba\s+third\b", re.IGNORECASE), Decimal("33.33")),
    (re.compile(r"\bhalf\b", re.IGNORECASE), Decimal("50")),
    (re.compile(r"\bthree[-\s]quarters?\b", re.IGNORECASE), Decimal("75")),
    (re.compile(r"\bquarter\b", re.IGNORECASE), Decimal("25")),
    (re.compile(r"\bfull\s+(?:amount|value|order)\b", re.IGNORECASE), Decimal("100")),
)

LIABILITY_ALLOWED_RE = re.compile(
    r"\b(?:no|not|without)\b[^.]{0,40}\bunlimited\s+liability\b|"
    r"\bliability\b[^.]{0,60}\bshall\s+not\s+be\s+unlimited\b",
    re.IGNORECASE,
)
LIABILITY_BANNED_RE = re.compile(
    r"\bunlimited\s+liability\b|"
    r"\bliability\b[^.]{0,120}\bunlimited\b|"
    r"\bliability\b[^.]{0,80}\b(?:shall|will)\s+be\s+unlimited\b",
    re.IGNORECASE,
)

EXCLUSIVITY_ALLOWED_RE = re.compile(
    r"\b(?:no|not|without)\b[^.]{0,30}\bexclusiv|"
    r"\bnot\s+asking\s+for\s+exclusivity\b|"
    r"\bno\s+exclusivity\b|"
    r"\bnon[-\s]?exclusive\b|"
    r"\bdoes\s+not\s+require\s+exclusivity\b",
    re.IGNORECASE,
)
EXCLUSIVITY_BANNED_RE = re.compile(
    r"\bexclusive\s+supplier\b|"
    r"\bsole\s+supplier\b|"
    r"\bonly\s+from\s+us\b|"
    r"\bbuy\b[^.]{0,80}\bonly\s+from\b|"
    r"\bexclusive\s+(?:supply|purchase|rights?)\b|"
    r"\bexclusivity\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BannedTermMatch:
    term_type: str
    matched_text: str
    detail: str


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]


def _advance_percent(sentence: str) -> Decimal | None:
    match = PERCENT_RE.search(sentence)
    if match:
        return Decimal(match.group(1))
    for pattern, value in FRACTION_WORDS:
        if pattern.search(sentence):
            return value
    return None


def detect_banned_terms_in_text(text: str) -> list[BannedTermMatch]:
    findings: list[BannedTermMatch] = []
    seen: set[tuple[str, str]] = set()
    text = normalise_untrusted_text(text)

    def add(term_type: str, sentence: str, detail: str) -> None:
        key = (term_type, sentence)
        if key not in seen:
            seen.add(key)
            findings.append(
                BannedTermMatch(
                    term_type=term_type,
                    matched_text=sentence,
                    detail=detail,
                )
            )

    for sentence in _sentences(text):
        if RENEWAL_BANNED_RE.search(sentence) and not RENEWAL_ALLOWED_RE.search(sentence):
            add(
                "automatic_renewal",
                sentence,
                "automatic renewal is a banned contractual term",
            )

        if ADVANCE_RE.search(sentence):
            percent = _advance_percent(sentence)
            if percent is not None and percent > Decimal("30"):
                add(
                    "advance_payment",
                    sentence,
                    f"advance/upfront payment {percent}% exceeds the allowed 30%",
                )

        if LIABILITY_BANNED_RE.search(sentence) and not LIABILITY_ALLOWED_RE.search(sentence):
            add(
                "unlimited_liability",
                sentence,
                "unlimited liability for Acme is a banned contractual term",
            )

        if EXCLUSIVITY_BANNED_RE.search(sentence) and not EXCLUSIVITY_ALLOWED_RE.search(sentence):
            add(
                "exclusivity",
                sentence,
                "supplier exclusivity is a banned contractual term",
            )
    return findings


def detect_banned_terms(latest_supplier_text: str) -> list[SecurityEvidence]:
    return [
        SecurityEvidence(
            rule_id=match.term_type,
            category="banned_term",
            matched_text=match.matched_text,
            message_role=None,
            detail=match.detail,
        )
        for match in detect_banned_terms_in_text(latest_supplier_text)
    ]
