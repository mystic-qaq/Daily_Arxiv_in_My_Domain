from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Paper:
    """A candidate harvested from arXiv and enriched as it moves down the pipeline."""

    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    published: datetime
    updated: datetime | None = None
    primary_category: str = ""
    categories: list[str] = field(default_factory=list)
    comment: str = ""
    pdf_url: str = ""
    abs_url: str = ""
    doi: str = ""

    # Downstream evidence (never invented; empty means "not obtained").
    full_text: str | None = None
    full_text_source: str = ""
    full_text_chars: int = 0
    repo: dict[str, Any] | None = None
    # True when the published date was guessed from the arXiv id rather than
    # read from the feed; such papers are re-dated from their abstract page.
    date_uncertain: bool = False

    # Deterministic screening signals.
    keyword_hits: list[str] = field(default_factory=list)
    lineage_hits: list[str] = field(default_factory=list)
    area_candidates: list[str] = field(default_factory=list)

    # LLM triage output.
    area: str = ""
    subarea: str = ""
    scores: dict[str, float] = field(default_factory=dict)
    relevance: float = 0.0
    triage_reason: str = ""
    keep: bool = True

    # Deep reading output (Chinese Markdown fragments).
    analysis: dict[str, str] = field(default_factory=dict)

    def prompt_view(self, abstract_chars: int = 1400) -> dict[str, Any]:
        """A compact, model-safe projection used by the triage prompt."""
        return {
            "id": self.arxiv_id,
            "title": self.title,
            "authors": self.authors[:6],
            "primary_category": self.primary_category,
            "categories": self.categories[:6],
            "comment": self.comment[:220],
            "abstract": self.abstract[:abstract_chars],
            "screening_hits": sorted(set(self.keyword_hits))[:12],
            "lineage_hits": sorted(set(self.lineage_hits))[:8],
        }


@dataclass
class TrendingProject:
    name: str
    url: str
    description: str
    stars: int
    age_days: float
    stars_per_day: float
    area: str = ""
    why: str = ""
    language: str = ""
    pushed_at: str = ""
