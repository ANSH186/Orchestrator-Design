"""Deterministic segmentation of supplier negotiation threads."""

from __future__ import annotations

import re
from datetime import date

from procurement_desk.exceptions import ExtractionError
from procurement_desk.models import Message, MessageRole, ThreadRecord

SEGMENT_RE = re.compile(
    r"\[(?P<kind>Earlier|Latest)\s+message\s*[—–-]\s*(?P<header>[^\]]+?)\]",
    re.IGNORECASE,
)
DATE_SUFFIX_RE = re.compile(r",\s*(\d{4}-\d{2}-\d{2})\s*$")


def _parse_header(header: str) -> tuple[MessageRole, str | None, date | None]:
    header = header.strip()
    message_date: date | None = None
    date_match = DATE_SUFFIX_RE.search(header)
    if date_match:
        message_date = date.fromisoformat(date_match.group(1))
        header = header[: date_match.start()].strip()

    normalized = re.sub(r"\s+", " ", header).casefold()
    if normalized in {"acme procurement", "acme", "acme corp"} or normalized.startswith(
        "acme procurement"
    ):
        role = MessageRole.ACME
        supplier_name = None
    else:
        role = MessageRole.SUPPLIER
        supplier_name = header or None
    return role, supplier_name, message_date


def segment_thread(thread: ThreadRecord) -> list[Message]:
    """Return messages in order.  Marker-free threads become one supplier message."""

    raw = thread.supplier_message
    matches = list(SEGMENT_RE.finditer(raw))
    if not matches:
        return [
            Message(
                index=0,
                role=MessageRole.SUPPLIER,
                supplier_name=thread.supplier,
                message_date=thread.date,
                is_latest=True,
                text=raw.strip(),
            )
        ]

    messages: list[Message] = []
    preamble = raw[: matches[0].start()].strip()
    if preamble:
        # Preserve unexpected text rather than discard it; it is supplier-authored
        # context and must be visible to injection scanning.
        messages.append(
            Message(
                index=0,
                role=MessageRole.SUPPLIER,
                supplier_name=thread.supplier,
                message_date=None,
                is_latest=False,
                text=preamble,
            )
        )

    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(raw)
        text = raw[match.end() : end].strip()
        role, supplier_name, message_date = _parse_header(match.group("header"))
        messages.append(
            Message(
                index=len(messages),
                role=role,
                supplier_name=supplier_name,
                message_date=message_date,
                is_latest=match.group("kind").casefold() == "latest",
                text=text,
            )
        )
    return messages


def latest_supplier_message(thread: ThreadRecord, messages: list[Message]) -> Message:
    supplier_messages = [m for m in messages if m.role == MessageRole.SUPPLIER]
    if not supplier_messages:
        raise ExtractionError(f"{thread.thread_id}: no supplier message found")
    latest = supplier_messages[-1]
    return latest


def supplier_history(messages: list[Message]) -> list[Message]:
    """All supplier messages except the final/latest supplier message."""

    supplier_messages = [m for m in messages if m.role == MessageRole.SUPPLIER]
    return supplier_messages[:-1] if supplier_messages else []


def thread_text(messages: list[Message]) -> str:
    return "\n".join(m.text for m in messages)
