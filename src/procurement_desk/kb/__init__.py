"""Knowledge-base exports."""

from procurement_desk.kb.ingest import (
    load_label_file,
    load_threads,
    thread_coverage_summary,
    validate_threads_against_kb,
)
from procurement_desk.kb.playbook_parser import (
    CATEGORY_DISPLAY_TO_SLUG,
    KnowledgeBase,
    build_knowledge_base,
)

__all__ = [
    "CATEGORY_DISPLAY_TO_SLUG",
    "KnowledgeBase",
    "build_knowledge_base",
    "load_label_file",
    "load_threads",
    "thread_coverage_summary",
    "validate_threads_against_kb",
]
