"""Thread Analyst: interpret supplier messages into validated offer facts.

The deterministic extractor is the primary path.  It handles all offer grammars
observed in the supplied corpus and is deliberately conservative: if a price,
currency, billing period, or basis cannot be established, the fact remains
unknown and the thread is marked for MISSING_INFO instead of guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from procurement_desk.exceptions import ExtractionError
from procurement_desk.kb.playbook_parser import KnowledgeBase
from procurement_desk.models import (
    BillingPeriod,
    CategoryPolicy,
    ExtractionMethod,
    Message,
    MessageRole,
    OfferBasis,
    OfferFacts,
    ThreadAnalysis,
    ThreadRecord,
)
from procurement_desk.pricing.money import (
    KNOWN_UNSUPPORTED_CURRENCIES,
    SUPPORTED_CURRENCIES,
    clean_indian_number,
    words_to_int,
)
from procurement_desk.text.thread_segmentation import (
    latest_supplier_message,
    segment_thread,
    supplier_history,
)

SUPPORTED_PREFIXES = {
    "₹": "INR",
    "RS": "INR",
    "RS.": "INR",
    "INR": "INR",
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
}

_UNSUPPORTED_CODE_ALT = "|".join(sorted(KNOWN_UNSUPPORTED_CURRENCIES))
_NUMERIC_PRICE_RE = re.compile(
    rf"(?P<prefix>₹|Rs\.?|INR|US\$|USD|€|EUR|£|GBP|\$|\b(?:{_UNSUPPORTED_CODE_ALT})\b)"
    rf"\s*(?P<number>\d[\d,]*(?:\.\d+)?)\s*(?P<scale>k|K|lakh|lakhs|crore|Crore)?",
    re.IGNORECASE,
)
_NUMBER_WORD = (
    r"(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|lakh|lakhs|"
    r"crore|crores|and)"
)
_WORD_PRICE_RE = re.compile(
    rf"(?P<words>(?:[A-Za-z]+(?:[-\s]+|$)){{1,18}})rupees", re.IGNORECASE
)
_WORD_PRICE_STRICT_RE = re.compile(
    rf"(?P<words>(?:{_NUMBER_WORD})(?:[-\s]+(?:{_NUMBER_WORD})){{0,15}})\s*rupees",
    re.IGNORECASE,
)
_CORRECTION_RE = re.compile(r"\bCORRECTION\b", re.IGNORECASE)
_PREVIOUS_QUOTE_RE = re.compile(
    r"further\s+(\d+(?:\.\d+)?)\s*%\s+off\s+our\s+previous\s+quote",
    re.IGNORECASE,
)
_LIST_DISCOUNT_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*%\s+discount\s+on\s+our\s+list\s+price",
    re.IGNORECASE,
)
_VOLUME_RE = re.compile(
    r"with\s+a\s+further\s+(\d+(?:\.\d+)?)\s*%\s+off\s+for\s+orders\s+of\s+(\d+)",
    re.IGNORECASE,
)
_FREE_UNITS_RE = re.compile(
    r"plus\s+(\d+)\s+free\s+[A-Za-z]+\s+for\s+every\s+(\d+)\s+you\s+pay\s+for",
    re.IGNORECASE,
)
_TIER_UP_TO_RE = re.compile(r"for\s+orders\s+of\s+up\s+to\s+(\d+)", re.IGNORECASE)
_TIER_LARGER_RE = re.compile(r"for\s+larger\s+orders", re.IGNORECASE)
_RANGE_RE = re.compile(r"\bbetween\b.*\band\b", re.IGNORECASE)
_TOTAL_RE = re.compile(r"\bin\s+total\s+for\s+all\s+([\d,]+)", re.IGNORECASE)
_PACK_RE = re.compile(r"\bper\s+pack(?:\s+of\s+(\d+))?", re.IGNORECASE)
_DOZEN_RE = re.compile(r"\bper\s+dozen\b", re.IGNORECASE)
_PER_N_RE = re.compile(r"\bper\s+(\d+)\s+[A-Za-z]", re.IGNORECASE)
_PERIOD_RE = re.compile(
    r"\bper\s+(month|year)\b|\b(monthly|yearly|annual)\b", re.IGNORECASE
)
_GST_INCLUSIVE_RE = re.compile(
    r"\b(?:inclusive\s+of\s+GST|including\s+GST|incl\.?\s+GST|GST\s+included|"
    r"\(GST\s+included\))\b",
    re.IGNORECASE,
)
_MISSING_PRICE_RE = re.compile(
    r"pricing\s+will\s+depend|competitive\s+price|quote\s+attached|see\s+attached|"
    r"price\s+on\s+request|get\s+on\s+a\s+call|contact\s+us\s+for\s+(?:a\s+)?price",
    re.IGNORECASE,
)
_THIS_ORDER_RE = re.compile(r"\bfor\s+this\s+order\b", re.IGNORECASE)

# Context scoring for messages that contain more than one price.  The supplied
# corpus normally has a single offer sentence, but real supplier email can put a
# list price, order value, liability cap or budget next to the actual offer.
_OFFER_CONTEXT_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\bwe\s+can\s+(?:do|offer|quote)\b", re.I), 6),
    (re.compile(r"\bcan\s+offer\b", re.I), 5),
    (re.compile(r"\b(?:our\s+)?(?:final|revised)\s+(?:price|offer)\b", re.I), 6),
    (re.compile(r"\bbest\s+(?:we\s+can\s+offer|price|we\s+can\s+do)\b", re.I), 6),
    (re.compile(r"\bwe\s+are\s+pleased\s+to\s+quote\b", re.I), 6),
    (re.compile(r"\bour\s+quote\b|\bquote\s+is\b|\bwe\s+quote\b", re.I), 5),
    (re.compile(r"\bprice\s+is\b|\brate\s+is\b|\boffer\s+is\b", re.I), 4),
    (re.compile(r"\bwe\s+offer\b", re.I), 4),
    (re.compile(r"\btotal\s+price\s+is\b", re.I), 4),
    (re.compile(r"\bfor\s+this\s+order\b", re.I), 1),
    (re.compile(r"\byou\s+requested\b", re.I), 1),
)
_NON_OFFER_CONTEXT_PATTERNS: tuple[tuple[re.Pattern[str], int], ...] = (
    (re.compile(r"\blist\s+price\s+is\b", re.I), -7),
    (re.compile(r"\blist\s+price\s+of\b", re.I), -5),
    (re.compile(r"\border\s+value\s+is\b", re.I), -8),
    (re.compile(r"\btotal\s+budget\s+is\b|\bbudget\s+is\b", re.I), -8),
    (re.compile(r"\bliability\b", re.I), -7),
    (re.compile(r"\bcapped\s+at\b|\bmaximum\s+of\b|\bnot\s+to\s+exceed\b", re.I), -6),
    (re.compile(r"\bplatform\s+fee\b|\bservice\s+fee\b", re.I), -4),
)
_LIST_DISCOUNT_CONTEXT_RE = re.compile(
    r"\bdiscount\s+on\s+our\s+list\s+price\b", re.I
)
_CLAUSE_SPLIT_RE = re.compile(
    r"(?<=[.!?;])\s+|\n+|,\s*(?=(?:but|however|although|while|whereas|yet)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PriceMention:
    start: int
    end: int
    amount: Decimal
    currency: str
    text: str


def _currency_from_prefix(prefix: str) -> str:
    cleaned = prefix.strip().upper().replace(".", "")
    if cleaned in {"₹"}:
        return "INR"
    if cleaned in {"RS", "INR"}:
        return "INR"
    if cleaned in {"$", "US$", "USD"}:
        return "USD"
    if cleaned in {"€", "EUR"}:
        return "EUR"
    if cleaned in {"£", "GBP"}:
        return "GBP"
    return cleaned


def find_price_mentions(text: str) -> list[PriceMention]:
    """Find explicit currency amounts without inventing a currency."""

    mentions: list[PriceMention] = []
    for match in _NUMERIC_PRICE_RE.finditer(text):
        prefix = match.group("prefix")
        # The unsupported-code alternation is case-insensitive only to catch
        # sloppy casing.  Ordinary English words such as "all" must not be
        # mistaken for the ALL (Albanian lek) currency code.
        if (
            len(prefix) == 3
            and prefix.isalpha()
            and prefix.upper() in KNOWN_UNSUPPORTED_CURRENCIES
            and prefix != prefix.upper()
        ):
            continue
        number = match.group("number")
        scale = match.group("scale") or ""
        try:
            amount = Decimal(clean_indian_number(number + scale))
        except (ValueError, ArithmeticError):
            continue
        mentions.append(
            PriceMention(
                start=match.start(),
                end=match.end(),
                amount=amount,
                currency=_currency_from_prefix(match.group("prefix")),
                text=match.group(0).strip(),
            )
        )

    used_spans = [(m.start, m.end) for m in mentions]
    for match in _WORD_PRICE_STRICT_RE.finditer(text):
        if any(start < match.end() and match.start() < end for start, end in used_spans):
            continue
        value = words_to_int(match.group("words"))
        if value is None:
            continue
        mentions.append(
            PriceMention(
                start=match.start(),
                end=match.end(),
                amount=Decimal(value),
                currency="INR",
                text=match.group(0).strip(),
            )
        )
        used_spans.append((match.start(), match.end()))

    # A broad fallback for word sequences that include a leading non-number word.
    for match in _WORD_PRICE_RE.finditer(text):
        if any(start < match.end() and match.start() < end for start, end in used_spans):
            continue
        words = match.group("words").strip()
        tokens = re.split(r"[-\s]+", words)
        value: int | None = None
        for skip in range(len(tokens)):
            candidate = " ".join(tokens[skip:])
            parsed = words_to_int(candidate)
            if parsed is not None:
                value = parsed
                break
        if value is None:
            continue
        mentions.append(
            PriceMention(
                start=match.start(),
                end=match.end(),
                amount=Decimal(value),
                currency="INR",
                text=match.group(0).strip(),
            )
        )
        used_spans.append((match.start(), match.end()))
    return sorted(mentions, key=lambda m: (m.start, m.end))


def _clauses(text: str) -> list[str]:
    return [part.strip() for part in _CLAUSE_SPLIT_RE.split(text) if part.strip()]


def _score_clause(text: str) -> int:
    """Score whether a clause looks like an actual supplier offer.

    Positive phrases are offer language; negative phrases are list-price,
    order-value, budget, liability or fee context.  List-discount language is
    explicitly treated as offer language.
    """

    score = 0
    list_discount = bool(_LIST_DISCOUNT_CONTEXT_RE.search(text))
    for pattern, weight in _OFFER_CONTEXT_PATTERNS:
        if pattern.search(text):
            score += weight
    if list_discount:
        score += 10
    else:
        for pattern, weight in _NON_OFFER_CONTEXT_PATTERNS:
            if pattern.search(text):
                score += weight
    return score


def _best_clause_score(line: str) -> int:
    scores = [
        _score_clause(clause)
        for clause in _clauses(line)
        if find_price_mentions(clause)
    ]
    return max(scores, default=0)


def _select_offer_clause(
    line: str, mentions: list[PriceMention]
) -> tuple[str, PriceMention] | None:
    """Select the actual offer clause when a line contains multiple prices."""

    if len(mentions) == 1:
        return line, mentions[0]
    scored: list[tuple[int, str, list[PriceMention]]] = []
    for clause in _clauses(line):
        clause_mentions = find_price_mentions(clause)
        if not clause_mentions:
            continue
        scored.append((_score_clause(clause), clause, clause_mentions))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    top_score, top_clause, top_mentions = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else -10**6
    if len(top_mentions) != 1:
        return None
    if top_score <= 0 or top_score <= second_score:
        return None
    return top_clause, top_mentions[0]


def _period_from_text(text: str) -> BillingPeriod | None:
    match = _PERIOD_RE.search(text)
    if not match:
        return None
    token = (match.group(1) or match.group(2) or "").casefold()
    if token in {"month", "monthly"}:
        return BillingPeriod.MONTH
    if token in {"year", "yearly", "annual"}:
        return BillingPeriod.YEAR
    return None


def _sub_unit_from_text(text: str, category: CategoryPolicy) -> str | None:
    if category.sub_unit_name is None:
        return None
    singular = category.sub_unit_name.rstrip("s").casefold()
    if re.search(rf"\bper\s+{re.escape(singular)}s?\b", text, re.IGNORECASE):
        return singular
    return None


@dataclass
class _Context:
    basis: OfferBasis
    total_quantity: int | None = None
    pack_size: int | None = None
    per_n: int | None = None
    sub_unit_name: str | None = None
    billing_period: BillingPeriod | None = None


def _context_for_mention(
    line: str,
    mention: PriceMention,
    category: CategoryPolicy,
) -> _Context:
    tail = line[mention.end :]
    search = f"{tail} {line}"
    total_match = _TOTAL_RE.search(search)
    if total_match:
        return _Context(
            basis=OfferBasis.TOTAL,
            total_quantity=int(total_match.group(1).replace(",", "")),
        )

    pack_match = _PACK_RE.search(search)
    if pack_match:
        size = int(pack_match.group(1)) if pack_match.group(1) else category.pack_size
        return _Context(basis=OfferBasis.PER_PACK, pack_size=size)

    if _DOZEN_RE.search(search):
        return _Context(basis=OfferBasis.PER_DOZEN)

    sub_unit = _sub_unit_from_text(search, category)
    if sub_unit is not None:
        return _Context(basis=OfferBasis.PER_SUB_UNIT, sub_unit_name=sub_unit)

    per_n_match = _PER_N_RE.search(tail)
    if per_n_match:
        return _Context(
            basis=OfferBasis.PER_N,
            per_n=int(per_n_match.group(1)),
        )

    return _Context(basis=OfferBasis.PER_UNIT, billing_period=_period_from_text(search))


def _discount_facts(
    line: str,
) -> tuple[Decimal | None, Decimal | None, int | None, int | None, int | None, list[str]]:
    warnings: list[str] = []
    list_discount = None
    volume_discount = None
    volume_threshold = None
    free_units = None
    paid_units = None

    match = _LIST_DISCOUNT_RE.search(line)
    if match:
        list_discount = Decimal(match.group(1))
    match = _VOLUME_RE.search(line)
    if match:
        volume_discount = Decimal(match.group(1))
        volume_threshold = int(match.group(2))
    match = _FREE_UNITS_RE.search(line)
    if match:
        free_units = int(match.group(1))
        paid_units = int(match.group(2))
        if paid_units <= 0:
            warnings.append("free-unit paid quantity is non-positive; offer is ambiguous")
    return (
        list_discount,
        volume_discount,
        volume_threshold,
        free_units,
        paid_units,
        warnings,
    )


class ThreadAnalyst:
    """Extract structured facts and evidence; never decides the action."""

    def __init__(self, kb: KnowledgeBase, llm_provider=None) -> None:
        self.kb = kb
        self.llm_provider = llm_provider

    def analyze(self, thread: ThreadRecord) -> ThreadAnalysis:
        category = self.kb.resolve_category(thread.category)
        if category is None:
            raise ExtractionError(f"{thread.thread_id}: unknown category {thread.category!r}")
        messages = segment_thread(thread)
        latest = latest_supplier_message(thread, messages)
        earlier = supplier_history(messages)
        offer, contract_lines, warnings = self._extract_offer(
            thread=thread,
            category=category,
            latest=latest,
            earlier=earlier,
        )
        extraction_method = ExtractionMethod.DETERMINISTIC
        if self.llm_provider is not None and not offer.has_usable_price:
            offer, warnings, llm_used = self._try_llm(thread, latest, offer, warnings)
            extraction_method = (
                ExtractionMethod.LLM
                if llm_used
                else ExtractionMethod.DETERMINISTIC_AFTER_LLM_FAILURE
            )

        requires_period = category.normalized_period is not None
        missing = False
        missing_reason = offer.missing_reason
        if offer.unsupported_currency:
            missing = True
            missing_reason = "unsupported_currency"
        elif not offer.has_usable_price:
            missing = True
            missing_reason = missing_reason or "no_usable_price"
        elif requires_period and offer.billing_period is None:
            missing = True
            missing_reason = "subscription_period_missing"

        evidence = list(offer.evidence)
        if latest.text and latest.text.strip() not in evidence:
            evidence.append(latest.text.strip())

        return ThreadAnalysis(
            thread_id=thread.thread_id,
            supplier=thread.supplier,
            category=thread.category,
            messages=messages,
            latest_supplier_message=latest.text,
            offer=offer,
            contract_statements=contract_lines,
            requires_billing_period=requires_period,
            missing_information=missing,
            missing_reason=missing_reason if missing else None,
            extraction_method=extraction_method,
            warnings=warnings,
            evidence=evidence,
        )

    def _extract_offer(
        self,
        *,
        thread: ThreadRecord,
        category: CategoryPolicy,
        latest: Message,
        earlier: Iterable[Message],
    ) -> tuple[OfferFacts, list[str], list[str]]:
        warnings: list[str] = []
        text = latest.text
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        contract_lines = [
            line
            for line in lines
            if not _NUMERIC_PRICE_RE.search(line) and "rupees" not in line.casefold()
        ]

        correction_line = next(
            (line for line in lines if _CORRECTION_RE.search(line)), None
        )
        if correction_line is not None:
            return self._extract_correction(
                thread, category, latest, correction_line, lines, warnings
            )

        previous_line = next(
            (line for line in lines if _PREVIOUS_QUOTE_RE.search(line)), None
        )
        if previous_line is not None:
            return self._extract_previous_quote(
                thread, category, latest, previous_line, earlier, warnings
            )

        price_lines = [line for line in lines if find_price_mentions(line)]
        if price_lines:
            if len(price_lines) == 1:
                selected_line = price_lines[0]
            else:
                scored = [
                    (_best_clause_score(line), line)
                    for line in price_lines
                ]
                scored.sort(key=lambda item: item[0], reverse=True)
                top_score, selected_line = scored[0]
                second_score = scored[1][0] if len(scored) > 1 else -10**6
                if top_score <= 0 or top_score <= second_score:
                    return self._missing_offer(
                        price_lines[0],
                        "ambiguous_multiple_prices",
                        warnings,
                        lines,
                    )
            return self._extract_from_line(
                thread, category, latest, selected_line, warnings
            )

        unsupported_mentions = [
            (m, line)
            for line in lines
            for m in find_price_mentions(line)
            if m.currency not in SUPPORTED_CURRENCIES | {"INR"}
        ]
        if unsupported_mentions:
            mention, line = unsupported_mentions[0]
            return (
                OfferFacts(
                    has_usable_price=False,
                    currency=mention.currency,
                    quoted_amount=mention.amount,
                    unsupported_currency=True,
                    unsupported_currency_code=mention.currency,
                    missing_reason="unsupported_currency",
                    quoted_amount_text=mention.text,
                    offer_sentence=line,
                    evidence=[line],
                ),
                contract_lines,
                warnings,
            )

        missing_line = next((line for line in lines if _MISSING_PRICE_RE.search(line)), None)
        reason = "no_usable_price"
        offer_sentence = missing_line or (lines[0] if lines else text.strip())
        return (
            OfferFacts(
                has_usable_price=False,
                missing_reason=reason,
                offer_sentence=offer_sentence,
                evidence=[offer_sentence],
            ),
            contract_lines,
            warnings,
        )

    def _extract_correction(
        self,
        thread: ThreadRecord,
        category: CategoryPolicy,
        latest: Message,
        line: str,
        lines: list[str],
        warnings: list[str],
    ) -> tuple[OfferFacts, list[str], list[str]]:
        body = re.split(r"should\s+read", line, maxsplit=1, flags=re.IGNORECASE)
        if len(body) != 2:
            return self._missing_offer(
                line, "correction_without_replacement", warnings, lines
            )
        remainder = body[1]
        parts = re.split(r",\s*not\s+", remainder, maxsplit=1, flags=re.IGNORECASE)
        corrected_text = parts[0]
        old_text = parts[1] if len(parts) > 1 else ""
        mentions = find_price_mentions(corrected_text)
        if not mentions:
            return self._missing_offer(
                line, "correction_without_usable_price", warnings, lines
            )
        mention = mentions[0]
        old_mentions = find_price_mentions(old_text)
        replaced = old_mentions[0].amount if old_mentions else None
        offer = self._offer_from_mention(
            thread=thread,
            category=category,
            line=line,
            mention=mention,
            warnings=warnings,
            is_correction=True,
            correction_replaced_amount=replaced,
        )
        contract_lines = [
            l for l in lines if l != line and not find_price_mentions(l)
        ]
        return offer, contract_lines, warnings

    def _extract_previous_quote(
        self,
        thread: ThreadRecord,
        category: CategoryPolicy,
        latest: Message,
        line: str,
        earlier: Iterable[Message],
        warnings: list[str],
    ) -> tuple[OfferFacts, list[str], list[str]]:
        match = _PREVIOUS_QUOTE_RE.search(line)
        if not match:
            return self._missing_offer(line, "previous_quote_reference_unparsed", warnings, [line])
        percent = Decimal(match.group(1))
        prior = list(earlier)
        prior_offer: OfferFacts | None = None
        prior_message: Message | None = None
        for message in reversed(prior):
            prior_offer = self._parse_prior_quote(thread, category, message)
            if prior_offer is not None and prior_offer.has_usable_price:
                prior_message = message
                break
        if prior_offer is None or prior_message is None:
            return self._missing_offer(
                line, "previous_quote_missing", warnings, [line]
            )
        if prior_offer.currency is None or prior_offer.quoted_amount is None:
            return self._missing_offer(
                line, "previous_quote_missing", warnings, [line]
            )
        warnings.append(
            "previous-quote discount applied to the supplier's own earlier message, "
            "not to Acme's last counter"
        )
        offer = OfferFacts(
            has_usable_price=True,
            currency=prior_offer.currency,
            quoted_amount=prior_offer.quoted_amount,
            amount_basis=prior_offer.amount_basis,
            total_quantity=prior_offer.total_quantity,
            pack_size=prior_offer.pack_size,
            per_n=prior_offer.per_n,
            sub_unit_name=prior_offer.sub_unit_name,
            billing_period=prior_offer.billing_period,
            gst_inclusive=prior_offer.gst_inclusive,
            previous_quote_discount_percent=percent,
            previous_quote_amount=prior_offer.quoted_amount,
            previous_quote_currency=prior_offer.currency,
            previous_quote_gst_inclusive=prior_offer.gst_inclusive,
            previous_quote_billing_period=prior_offer.billing_period,
            previous_quote_source_index=prior_message.index,
            previous_quote_basis=prior_offer.amount_basis,
            previous_quote_total_quantity=prior_offer.total_quantity,
            previous_quote_pack_size=prior_offer.pack_size,
            previous_quote_per_n=prior_offer.per_n,
            offer_sentence=line,
            evidence=[prior_message.text.strip(), line],
        )
        return offer, [], warnings

    def _parse_prior_quote(
        self,
        thread: ThreadRecord,
        category: CategoryPolicy,
        message: Message,
    ) -> OfferFacts | None:
        for line in [l.strip() for l in message.text.splitlines() if l.strip()]:
            mentions = find_price_mentions(line)
            if not mentions:
                continue
            return self._offer_from_mention(
                thread=thread,
                category=category,
                line=line,
                mention=mentions[0],
                warnings=[],
            )
        return None

    def _extract_from_line(
        self,
        thread: ThreadRecord,
        category: CategoryPolicy,
        latest: Message,
        line: str,
        warnings: list[str],
    ) -> tuple[OfferFacts, list[str], list[str]]:
        mentions = find_price_mentions(line)
        if not mentions:
            return self._missing_offer(line, "no_usable_price", warnings, [latest.text])

        is_range = bool(_RANGE_RE.search(line) and len(mentions) >= 2)
        is_tier = bool(
            _TIER_UP_TO_RE.search(line)
            and _TIER_LARGER_RE.search(line)
            and len(mentions) >= 2
        )
        if is_tier:
            threshold = int(_TIER_UP_TO_RE.search(line).group(1))
            if thread.quantity <= threshold:
                mention = mentions[0]
                branch = "up_to"
            else:
                mention = mentions[1]
                branch = "larger"
            offer = self._offer_from_mention(
                thread=thread,
                category=category,
                line=line,
                mention=mention,
                warnings=warnings,
                tier_threshold=threshold,
                tier_branch=branch,
            )
        elif is_range:
            mention = max(mentions, key=lambda m: m.amount)
            offer = self._offer_from_mention(
                thread=thread,
                category=category,
                line=line,
                mention=mention,
                warnings=warnings,
                is_range=True,
                range_used_high=True,
            )
        else:
            if len(mentions) > 1:
                selected = _select_offer_clause(line, mentions)
                if selected is None:
                    return self._missing_offer(
                        line,
                        "ambiguous_multiple_prices",
                        warnings,
                        [latest.text],
                    )
                selected_line, mention = selected
                offer = self._offer_from_mention(
                    thread=thread,
                    category=category,
                    line=selected_line,
                    mention=mention,
                    warnings=warnings,
                )
            else:
                if _score_clause(line) < 0:
                    return self._missing_offer(
                        line,
                        "non_offer_price_context",
                        warnings,
                        [latest.text],
                    )
                offer = self._offer_from_mention(
                    thread=thread,
                    category=category,
                    line=line,
                    mention=mentions[0],
                    warnings=warnings,
                )
        contract_lines = [l for l in latest.text.splitlines() if l.strip() and l.strip() != line]
        return offer, contract_lines, warnings

    def _offer_from_mention(
        self,
        *,
        thread: ThreadRecord,
        category: CategoryPolicy,
        line: str,
        mention: PriceMention,
        warnings: list[str],
        is_correction: bool = False,
        correction_replaced_amount: Decimal | None = None,
        is_range: bool = False,
        range_used_high: bool = False,
        tier_threshold: int | None = None,
        tier_branch: str | None = None,
    ) -> OfferFacts:
        context = _context_for_mention(line, mention, category)
        (
            list_discount,
            volume_discount,
            volume_threshold,
            free_units,
            paid_units,
            discount_warnings,
        ) = _discount_facts(line)
        warnings.extend(discount_warnings)
        if _THIS_ORDER_RE.search(line):
            warnings.append(
                "offer says 'for this order' without a billing period; "
                "period will be treated as unknown"
            )
        unsupported = mention.currency not in SUPPORTED_CURRENCIES | {"INR"}
        if context.basis == OfferBasis.TOTAL and context.total_quantity is None:
            warnings.append("total quote without a unit quantity")
        if context.basis == OfferBasis.TOTAL and context.total_quantity != thread.quantity:
            warnings.append(
                f"total quantity {context.total_quantity} in message differs from "
                f"thread quantity {thread.quantity}"
            )
        if context.basis == OfferBasis.PER_PACK and context.pack_size is None:
            warnings.append("pack quote without a pack size; category pack size will be used")
        if context.basis == OfferBasis.PER_N and context.per_n is None:
            warnings.append("per-N quote without a positive N")

        amount_basis = context.basis
        period = (
            _period_from_text(line[mention.end :])
            or context.billing_period
        )
        return OfferFacts(
            has_usable_price=not unsupported,
            currency=mention.currency,
            quoted_amount=mention.amount,
            amount_basis=amount_basis,
            total_quantity=context.total_quantity,
            pack_size=context.pack_size,
            per_n=context.per_n,
            sub_unit_name=context.sub_unit_name,
            billing_period=period,
            gst_inclusive=bool(_GST_INCLUSIVE_RE.search(line)),
            list_discount_percent=list_discount,
            volume_discount_percent=volume_discount,
            volume_threshold=volume_threshold,
            tier_threshold=tier_threshold,
            tier_branch=tier_branch,
            free_units=free_units,
            paid_units=paid_units,
            is_correction=is_correction,
            correction_replaced_amount=correction_replaced_amount,
            is_range=is_range,
            range_used_high=range_used_high,
            unsupported_currency=unsupported,
            unsupported_currency_code=mention.currency if unsupported else None,
            missing_reason="unsupported_currency" if unsupported else None,
            quoted_amount_text=mention.text,
            quoted_unit_text=line[mention.end :].strip(),
            offer_sentence=line,
            evidence=[line],
        )

    def _missing_offer(
        self,
        line: str,
        reason: str,
        warnings: list[str],
        lines: list[str],
    ) -> tuple[OfferFacts, list[str], list[str]]:
        warnings.append(f"offer could not be priced: {reason}")
        return (
            OfferFacts(
                has_usable_price=False,
                missing_reason=reason,
                offer_sentence=line,
                evidence=[line],
            ),
            [l for l in lines if l != line],
            warnings,
        )

    def _try_llm(
        self,
        thread: ThreadRecord,
        latest: Message,
        deterministic: OfferFacts,
        warnings: list[str],
    ) -> tuple[OfferFacts, list[str], bool]:
        """Optional LLM second opinion; disabled unless a provider is injected."""

        if self.llm_provider is None:
            return deterministic, warnings, False
        from procurement_desk.llm.provider import validate_llm_offer

        try:
            llm_offer = self.llm_provider.extract_offer(
                thread=thread,
                latest_message=latest.text,
                category=self.kb.resolve_category(thread.category),
            )
            if llm_offer is None:
                warnings.append("LLM returned no extraction; deterministic result retained")
                return deterministic, warnings, False
            grounded, reason = validate_llm_offer(llm_offer, latest.text)
            if not grounded:
                warnings.append(f"LLM extraction rejected: {reason}")
                return deterministic, warnings, False
            warnings.append("LLM extraction accepted after deterministic uncertainty")
            return llm_offer, warnings, True
        except Exception as exc:  # noqa: BLE001 - provider failures must not invent facts
            warnings.append(f"LLM extraction failed safely: {exc}")
        return deterministic, warnings, False
