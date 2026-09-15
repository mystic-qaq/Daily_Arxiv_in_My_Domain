from __future__ import annotations

import html
import re
import urllib.request
from io import BytesIO
from pathlib import Path

from .models import Paper

USER_AGENT = "domain-specific-daily-arxiv/0.3 (personal research digest agent)"

SECTION_HINTS = (
    "introduction", "related work", "method", "approach", "preliminary", "preliminaries",
    "architecture", "experiments", "results", "ablation", "discussion", "conclusion",
    "limitations", "implementation",
)
# Sections that add weight but no reading value for triage-level reasoning.
NOISE_SECTIONS = ("references", "bibliography", "acknowledgment", "acknowledgement", "appendix")


def _strip_tags(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|math|svg)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<!--.*?-->", " ", raw)
    # Headings become markdown-ish markers so section structure survives the
    # conversion; downstream prompts can then cite "the method section says".
    raw = re.sub(r"(?is)<h([1-6])[^>]*>(.*?)</h\1>", lambda m: f"\n\n{'#' * int(m.group(1))} {re.sub(r'<[^>]+>', '', m.group(2)).strip()}\n\n", raw)
    raw = re.sub(r"(?is)</(p|div|li|tr|table|section)>", "\n", raw)
    raw = re.sub(r"(?is)<br\s*/?>", "\n", raw)
    raw = re.sub(r"(?is)<li[^>]*>", "- ", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _cut_noise(text: str) -> str:
    """Drop the bibliography tail, which dominates raw HTML but carries no insight."""
    for marker in ("References\n", "REFERENCES", "Bibliography"):
        pos = text.rfind(marker)
        if pos > 0 and pos > len(text) * 0.5:
            text = text[:pos]
            break
    return text


def _prioritise(text: str, max_chars: int) -> str:
    """Keep the head (title abstract intro) plus the method/experiment bodies.

    Newly submitted papers often have very long related-work sections; when the
    budget bites we prefer keeping introduction + method + experiments and let
    later sections go, rather than truncating blind at the character limit.
    """
    if len(text) <= max_chars:
        return text
    paragraphs = [p for p in text.split("\n\n") if len(p.strip()) > 40]
    scored = []
    for i, para in enumerate(paragraphs):
        head = para[:160].lower()
        bonus = 0
        if any(h in head for h in ("method", "approach", "architecture", "we propose", "in this paper")):
            bonus = 3
        elif any(h in head for h in ("experiment", "result", "ablation", "evaluation")):
            bonus = 2
        elif any(h in head for h in ("introduction", "conclusion", "limitation")):
            bonus = 1
        elif any(h in head for h in NOISE_SECTIONS):
            bonus = -3
        position = -0.002 * i  # mild preference for earlier content
        scored.append((bonus + position, i, para))
    kept = [para for _, _, para in sorted(scored, key=lambda t: (-t[0], t[1]))]
    out, total = [], 0
    for para in kept:
        if total + len(para) > max_chars:
            break
        out.append(para)
        total += len(para)
    # Preserve reading order; ``i`` keeps the original ordering of the kept text.
    ordered = [p for p in paragraphs if p in set(out)]
    result = "\n\n".join(ordered)
    if not result:
        # Every candidate paragraph was larger than the budget on its own, so
        # fall back to the single most valuable section, truncated.
        best = max(scored, key=lambda t: (t[0], -t[1]))[2]
        result = best[:max_chars]
    return result or text[:max_chars]


def fetch_html(url: str, timeout: int = 30) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
        return body or None
    except Exception:
        return None


def fetch_pdf_text(url: str, timeout: int = 45) -> str | None:
    try:
        from pypdf import PdfReader  # optional dependency
    except ImportError:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
        text = " ".join((page.extract_text() or "") for page in PdfReader(BytesIO(raw)).pages)
        return re.sub(r"\s+", " ", text).strip() or None
    except Exception:
        return None


class FullTextFetcher:
    """Extract readable paper text: arXiv HTML -> ar5iv -> PDF -> abstract only."""

    def __init__(self, cache_dir: Path | None = None, timeout: int = 40):
        self.cache_dir = Path(cache_dir) / "fulltext" if cache_dir else None
        self.timeout = timeout

    def _cache(self, key: str) -> Path | None:
        if not self.cache_dir:
            return None
        safe = key.replace("/", "_")
        return self.cache_dir / f"{safe}.txt"

    def __call__(self, paper: Paper, max_chars: int = 42000) -> tuple[str | None, str, int]:
        cached = self._cache(paper.arxiv_id)
        if cached and cached.exists():
            text = cached.read_text(encoding="utf-8")
            return text, "cache", len(text)
        sources = (
            (f"https://arxiv.org/html/{paper.arxiv_id}", "arxiv-html"),
            (f"https://ar5iv.labs.arxiv.org/html/{paper.arxiv_id}", "ar5iv"),
        )
        text: str | None = None
        label = ""
        for url, name in sources:
            body = fetch_html(url, timeout=self.timeout)
            if body and "<body" in body.lower():
                cleaned = _cut_noise(_strip_tags(body))
                if len(cleaned) > 1500:
                    text, label = cleaned, name
                    break
        if text is None:
            pdf_text = fetch_pdf_text(paper.pdf_url, timeout=self.timeout + 15)
            if pdf_text and len(pdf_text) > 1500:
                text, label = pdf_text, "pdf"
        if text is None:
            return None, "", 0
        trimmed = _prioritise(text, max_chars)
        if cached:
            try:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(trimmed, encoding="utf-8")
            except OSError:
                pass
        return trimmed, label, len(trimmed)
