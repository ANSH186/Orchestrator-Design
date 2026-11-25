"""Faithful parser for the supplied procurement playbook."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from procurement_desk.exceptions import IngestionError, KnowledgeBaseError
from procurement_desk.models import (
    Amendment,
    AmendmentField,
    BillingPeriod,
    CategoryPolicy,
    PolicyDocument,
    Precedent,
    SupplierProfile,
    SupplierStatus,
)

# Controlled mappings.  These are explicit so that a new filename can never be
# silently mistaken for an existing category/supplier via substring matching.
CATEGORY_DISPLAY_TO_SLUG: dict[str, str] = {
    "Catering": "catering",
    "Cleaning services": "cleaning",
    "Cloud servers": "cloud-servers",
    "Courier services": "courier",
    "CRM licenses": "crm-licenses",
    "Design software": "design-software",
    "Headsets": "headsets",
    "Laptops": "laptops",
    "LED lighting": "led-lighting",
    "Mobile phones": "mobile-phones",
    "Monitors": "monitors",
    "Office chairs": "office-chairs",
    "Printer paper": "printer-paper",
    "Security guards": "security-guards",
    "Training workshops": "training",
}

SUPPLIER_STATUS_PREFIX: tuple[tuple[str, SupplierStatus], ...] = (
    ("BLACKLISTED", SupplierStatus.BLACKLISTED),
    ("PROBATION", SupplierStatus.PROBATION),
    ("APPROVED", SupplierStatus.APPROVED),
)

INR_AMOUNT_RE = r"₹\s*([\d,]+(?:\.\d+)?)"


def _read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise IngestionError(f"playbook file is not valid UTF-8: {path}") from exc


def _parse_inr(text: str, context: str) -> Decimal:
    match = re.search(INR_AMOUNT_RE, text)
    if not match:
        raise IngestionError(f"could not find INR amount in {context}: {text!r}")
    return Decimal(match.group(1).replace(",", ""))


def _parse_percent(text: str, context: str) -> Decimal:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if not match:
        raise IngestionError(f"could not find percentage in {context}: {text!r}")
    return Decimal(match.group(1)) / Decimal("100")


def _normalise_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _singular(word: str) -> str:
    lowered = word.casefold().strip()
    if lowered.endswith("ies") and len(lowered) > 3:
        return lowered[:-3] + "y"
    if lowered.endswith("es") and len(lowered) > 3:
        return lowered[:-2]
    if lowered.endswith("s") and len(lowered) > 3:
        return lowered[:-1]
    return lowered


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def parse_category_document(path: Path, *, source_root: Path) -> CategoryPolicy:
    text = _read_utf8(path)
    heading = re.search(r"^# Category:\s*(.+?)\s*$", text, re.MULTILINE)
    if not heading:
        raise IngestionError(f"missing category heading: {path}")
    display_name = heading.group(1).strip()
    slug = CATEGORY_DISPLAY_TO_SLUG.get(display_name)
    if slug is None:
        raise IngestionError(f"unmapped category name {display_name!r} in {path}")
    if path.stem != slug:
        raise IngestionError(
            f"category filename {path.stem!r} does not match controlled slug {slug!r}"
        )

    def require(pattern: str, label: str) -> re.Match[str]:
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            raise IngestionError(f"missing {label} in {path}")
        return match

    normalized_unit = require(
        r"\*\*Normalized unit:\*\*\s*(.+)", "normalized unit"
    ).group(1).strip()
    gst_rate = _parse_percent(
        require(r"\*\*GST rate:\*\*\s*([\d.]+%)", "GST rate").group(1),
        f"GST rate in {path}",
    )
    target_text = require(r"\*\*Target price:\*\*\s*(₹[^\n]+)", "target price").group(1)
    walkaway_text = require(
        r"\*\*Walk-away price:\*\*\s*(₹[^\n]+)", "walk-away price"
    ).group(1)
    rounds = int(
        require(r"\*\*Negotiation rounds \(R\):\*\*\s*(\d+)", "rounds").group(1)
    )
    beta = Decimal(
        require(r"\*\*Concession exponent \(β\):\*\*\s*([\d.]+)", "beta").group(1)
    )
    approval_text = require(
        r"\*\*Approval limit:\*\*\s*(₹[^\n]+)", "approval limit"
    ).group(1)

    target = _parse_inr(target_text, f"target price in {path}")
    walkaway = _parse_inr(walkaway_text, f"walk-away price in {path}")
    approval_limit = _parse_inr(approval_text, f"approval limit in {path}")

    if "per month" in normalized_unit:
        normalized_period = BillingPeriod.MONTH
    elif "per year" in normalized_unit:
        normalized_period = BillingPeriod.YEAR
    else:
        normalized_period = None

    pack_size: int | None = None
    sub_unit_name: str | None = None
    sub_unit_factor: Decimal | None = None

    pack_match = re.search(r"a pack holds\s+(\d+)\s+([A-Za-z]+)", text, re.IGNORECASE)
    if pack_match:
        pack_size = int(pack_match.group(1))
        if pack_size <= 1:
            raise IngestionError(f"invalid pack size in {path}: {pack_size}")
        if _singular(pack_match.group(2)) not in _singular(normalized_unit.split("per")[-1]):
            raise IngestionError(
                f"pack unit {pack_match.group(2)!r} not found in normalized unit "
                f"{normalized_unit!r} for {path}"
            )

    sub_unit_match = re.search(
        r"one\s+([A-Za-z]+)\s*=\s*(\d+)\s+([A-Za-z]+)", text, re.IGNORECASE
    )
    if sub_unit_match:
        container, factor_text, contained = sub_unit_match.groups()
        factor = Decimal(factor_text)
        if factor <= 1:
            raise IngestionError(f"invalid sub-unit factor in {path}: {factor}")
        if _singular(container) not in _singular(normalized_unit.split("per")[-1]):
            raise IngestionError(
                f"container {container!r} not found in normalized unit "
                f"{normalized_unit!r} for {path}"
            )
        sub_unit_name = contained.casefold()
        sub_unit_factor = factor

    return CategoryPolicy(
        slug=slug,
        name=display_name,
        normalized_unit=normalized_unit,
        normalized_period=normalized_period,
        gst_rate=gst_rate,
        target=target,
        walkaway=walkaway,
        rounds=rounds,
        beta=beta,
        approval_limit=approval_limit,
        pack_size=pack_size,
        sub_unit_name=sub_unit_name,
        sub_unit_factor=sub_unit_factor,
        source_path=_relative(path, source_root),
        raw_text=text,
    )


def parse_amendment_document(
    path: Path, *, category_slugs: set[str], source_root: Path
) -> Amendment:
    text = _read_utf8(path)
    heading = re.search(r"^# (AMD-\d+):\s*(.+?)\s*$", text, re.MULTILINE)
    if not heading:
        raise IngestionError(f"missing amendment heading: {path}")
    amendment_id = heading.group(1)
    category_name = heading.group(2).strip()
    category_slug = CATEGORY_DISPLAY_TO_SLUG.get(category_name)
    if category_slug is None:
        raise IngestionError(f"unmapped amendment category {category_name!r} in {path}")
    if category_slug not in category_slugs:
        raise IngestionError(f"amendment references unknown category slug {category_slug}")

    effective_match = re.search(
        r"\*\*Effective from:\*\*\s*(\d{4}-\d{2}-\d{2})", text
    )
    if not effective_match:
        raise IngestionError(f"missing effective date in {path}")
    effective_from = date.fromisoformat(effective_match.group(1))

    change_match = re.search(
        r"\*\*Change:\*\*\s*the\s+(target price|walk-away price|approval limit)"
        r"\s+for\s+.+?\s+is now\s+(₹[^\n]+)",
        text,
        re.IGNORECASE,
    )
    if not change_match:
        raise IngestionError(f"unparseable amendment change in {path}")
    field_text = change_match.group(1).casefold()
    field_map = {
        "target price": AmendmentField.TARGET,
        "walk-away price": AmendmentField.WALKAWAY,
        "approval limit": AmendmentField.APPROVAL_LIMIT,
    }
    amount = _parse_inr(change_match.group(2), f"amendment amount in {path}")
    return Amendment(
        amendment_id=amendment_id,
        category_slug=category_slug,
        category_name=category_name,
        effective_from=effective_from,
        field=field_map[field_text],
        amount=amount,
        source_path=_relative(path, source_root),
        raw_text=text,
    )


def parse_supplier_document(
    path: Path, *, category_slugs: set[str], source_root: Path
) -> SupplierProfile:
    text = _read_utf8(path)
    heading = re.search(r"^# Supplier:\s*(.+?)\s*$", text, re.MULTILINE)
    if not heading:
        raise IngestionError(f"missing supplier heading: {path}")
    display_name = heading.group(1).strip()

    status_match = re.search(r"\*\*Status:\*\*\s*([^\n]+)", text)
    if not status_match:
        raise IngestionError(f"missing supplier status in {path}")
    status_line = status_match.group(1).strip().upper()
    status: SupplierStatus | None = None
    for prefix, candidate in SUPPLIER_STATUS_PREFIX:
        if status_line.startswith(prefix):
            status = candidate
            break
    if status is None:
        raise IngestionError(f"unrecognised supplier status {status_line!r} in {path}")

    currency_rates: dict[str, Decimal] = {}
    for match in re.finditer(
        r"invoices in\s+([A-Z]{3})\s+are converted at\s+₹\s*([\d.,]+)\s+per\s+[A-Z]{3}",
        text,
    ):
        currency = match.group(1).upper()
        rate_text = match.group(2).replace(",", "")
        if Decimal(rate_text) <= 0:
            raise IngestionError(f"non-positive FX rate in {path}")
        currency_rates[currency] = Decimal(rate_text)

    category_caps: dict[str, Decimal] = {}
    cap_pattern = re.compile(
        r"price cap for\s+([A-Za-z0-9 &]+?)\s+of\s+₹\s*([\d,.]+)\s+per\s+[A-Za-z]+",
        re.IGNORECASE,
    )
    for match in cap_pattern.finditer(text):
        cap_category_name = match.group(1).strip()
        cap_slug = CATEGORY_DISPLAY_TO_SLUG.get(cap_category_name)
        if cap_slug is None:
            raise IngestionError(
                f"supplier cap references unmapped category {cap_category_name!r} in {path}"
            )
        if cap_slug not in category_slugs:
            raise IngestionError(
                f"supplier cap references unknown category slug {cap_slug} in {path}"
            )
        amount = Decimal(match.group(2).replace(",", ""))
        if amount <= 0:
            raise IngestionError(f"non-positive price cap in {path}")
        category_caps[cap_slug] = amount

    notes_match = re.search(r"\*\*Notes:\*\*\s*([^\n]+)", text)
    notes = notes_match.group(1).strip() if notes_match else None

    return SupplierProfile(
        key=path.stem,
        display_name=display_name,
        status=status,
        currency_rates=currency_rates,
        category_caps=category_caps,
        notes=notes,
        source_path=_relative(path, source_root),
        raw_text=text,
    )


def parse_precedent_document(path: Path, *, source_root: Path) -> Precedent:
    text = _read_utf8(path)
    heading = re.search(r"^# Precedent\s+(P-\d+)\s*[—-]\s*(.+?)\s*$", text, re.MULTILINE)
    if not heading:
        raise IngestionError(f"missing precedent heading: {path}")
    precedent_id, category_name = heading.groups()
    body = text[heading.end() :].strip()
    if not body:
        raise IngestionError(f"empty precedent body: {path}")
    return Precedent(
        precedent_id=precedent_id,
        category_name=category_name.strip(),
        title=heading.group(0).lstrip("# ").strip(),
        body=body,
        source_path=_relative(path, source_root),
    )


def parse_policy_document(path: Path, *, source_root: Path) -> PolicyDocument:
    text = _read_utf8(path)
    heading = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    if not heading:
        raise IngestionError(f"missing policy heading: {path}")
    return PolicyDocument(
        name=path.stem,
        title=heading.group(1).strip(),
        body=text,
        source_path=_relative(path, source_root),
    )


@dataclass
class KnowledgeBase:
    categories: dict[str, CategoryPolicy]
    suppliers: dict[str, SupplierProfile]
    amendments: list[Amendment]
    precedents: list[Precedent]
    policies: dict[str, PolicyDocument]
    readme: str
    source_root: Path
    documents: list[str] = field(default_factory=list)
    source_hash: str = ""

    def __post_init__(self) -> None:
        self._supplier_name_index: dict[str, str] = {}
        for key, supplier in self.suppliers.items():
            self._supplier_name_index[_normalise_key(supplier.display_name)] = key
            self._supplier_name_index[_normalise_key(key)] = key
        self._validate()

    def _validate(self) -> None:
        if len(self.categories) != 15:
            raise KnowledgeBaseError(
                f"expected 15 categories, found {len(self.categories)}"
            )
        if len(self.suppliers) != 40:
            raise KnowledgeBaseError(
                f"expected 40 suppliers, found {len(self.suppliers)}"
            )
        if len(self.amendments) != 9:
            raise KnowledgeBaseError(
                f"expected 9 amendments, found {len(self.amendments)}"
            )
        if len(self.precedents) != 8:
            raise KnowledgeBaseError(
                f"expected 8 precedents, found {len(self.precedents)}"
            )
        if len(self.policies) != 7:
            raise KnowledgeBaseError(
                f"expected 7 policy documents, found {len(self.policies)}"
            )
        amendment_ids = [a.amendment_id for a in self.amendments]
        if len(amendment_ids) != len(set(amendment_ids)):
            raise KnowledgeBaseError("duplicate amendment IDs")
        for amendment in self.amendments:
            if amendment.category_slug not in self.categories:
                raise KnowledgeBaseError(
                    f"amendment {amendment.amendment_id} points to unknown category"
                )
        for supplier in self.suppliers.values():
            for currency in supplier.currency_rates:
                if currency not in {"USD", "EUR", "GBP"}:
                    raise KnowledgeBaseError(
                        f"unsupported contract currency {currency} for {supplier.key}"
                    )
            for category in supplier.category_caps:
                if category not in self.categories:
                    raise KnowledgeBaseError(
                        f"supplier {supplier.key} cap points to unknown category"
                    )
        if len(self.documents) != 80:
            raise KnowledgeBaseError(
                f"expected 80 playbook documents, found {len(self.documents)}"
            )

    def resolve_category(self, category: str) -> CategoryPolicy | None:
        return self.categories.get(category.strip().casefold())

    def resolve_supplier(self, supplier_name: str) -> SupplierProfile | None:
        key = self._supplier_name_index.get(_normalise_key(supplier_name))
        return self.suppliers.get(key) if key else None

    def amendments_for(self, category_slug: str) -> list[Amendment]:
        matching = [a for a in self.amendments if a.category_slug == category_slug]
        return sorted(matching, key=lambda a: (a.effective_from, a.amendment_id))

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for supplier in self.suppliers.values():
            counts[supplier.status.value] = counts.get(supplier.status.value, 0) + 1
        return dict(sorted(counts.items()))

    def contract_override_counts(self) -> dict[str, int]:
        currency = sum(1 for s in self.suppliers.values() if s.currency_rates)
        caps = sum(1 for s in self.suppliers.values() if s.category_caps)
        return {"currency_rate_suppliers": currency, "price_cap_suppliers": caps}


def build_knowledge_base(playbook_dir: Path) -> KnowledgeBase:
    """Parse all 80 playbook documents and validate completeness."""

    if not playbook_dir.exists():
        raise KnowledgeBaseError(f"playbook directory does not exist: {playbook_dir}")
    source_root = playbook_dir.parent.parent if playbook_dir.name == "playbook" else playbook_dir

    category_paths = sorted((playbook_dir / "categories").glob("*.md"))
    supplier_paths = sorted((playbook_dir / "suppliers").glob("*.md"))
    amendment_paths = sorted((playbook_dir / "amendments").glob("*.md"))
    precedent_paths = sorted((playbook_dir / "precedents").glob("*.md"))
    policy_paths = sorted((playbook_dir / "policies").glob("*.md"))

    categories: dict[str, CategoryPolicy] = {}
    for path in category_paths:
        category = parse_category_document(path, source_root=source_root)
        if category.slug in categories:
            raise KnowledgeBaseError(f"duplicate category slug {category.slug}")
        categories[category.slug] = category

    category_slugs = set(categories)
    suppliers: dict[str, SupplierProfile] = {}
    for path in supplier_paths:
        supplier = parse_supplier_document(
            path, category_slugs=category_slugs, source_root=source_root
        )
        if supplier.key in suppliers:
            raise KnowledgeBaseError(f"duplicate supplier key {supplier.key}")
        suppliers[supplier.key] = supplier

    suppliers_by_display: dict[str, SupplierProfile] = {}
    for supplier in suppliers.values():
        normalized = _normalise_key(supplier.display_name)
        if normalized in suppliers_by_display:
            raise KnowledgeBaseError(
                f"duplicate normalized supplier name {supplier.display_name!r}"
            )
        suppliers_by_display[normalized] = supplier

    amendments = [
        parse_amendment_document(
            path, category_slugs=category_slugs, source_root=source_root
        )
        for path in amendment_paths
    ]
    precedents = [
        parse_precedent_document(path, source_root=source_root)
        for path in precedent_paths
    ]
    policies = {
        path.stem: parse_policy_document(path, source_root=source_root)
        for path in policy_paths
    }

    readme_path = playbook_dir / "README.md"
    readme = _read_utf8(readme_path) if readme_path.exists() else ""

    documents = [
        _relative(path, source_root)
        for path in (
            category_paths
            + supplier_paths
            + amendment_paths
            + precedent_paths
            + policy_paths
            + ([readme_path] if readme_path.exists() else [])
        )
    ]
    digest = hashlib.sha256()
    for document in sorted(documents):
        digest.update(document.encode("utf-8"))
        digest.update((source_root / document).read_bytes())
    return KnowledgeBase(
        categories=categories,
        suppliers=suppliers,
        amendments=amendments,
        precedents=precedents,
        policies=policies,
        readme=readme,
        source_root=source_root,
        documents=documents,
        source_hash=digest.hexdigest(),
    )
