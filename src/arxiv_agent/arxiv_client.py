from __future__ import annotations

import hashlib
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from collections.abc import Iterable

from .models import Paper

ATOM = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"
NS = {"a": ATOM, "arxiv": ARXIV_NS}
USER_AGENT = "domain-specific-daily-arxiv/0.3 (personal research digest agent)"
ATOM_HOST = "https://export.arxiv.org/api/query"
RSS_URL = "https://arxiv.org/rss/{category}"
LISTING_URL = "https://arxiv.org/list/{category}/{month}"
ABS_URL = "https://arxiv.org/abs/{arxiv_id}"


class ArxivError(RuntimeError):
    pass


def _node_text(parent: ET.Element, name: str, ns: str = ATOM) -> str:
    node = parent.find(f"{{{ns}}}{name}")
    return " ".join((node.text or "").split()) if node is not None and node.text else ""


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _http(url: str, timeout: int, accept: str = "*/*") -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise ArxivError(f"HTTP {exc.code}{' (Rate exceeded)' if exc.code == 429 else ''} for {url}") from exc
    except Exception as exc:
        raise ArxivError(f"request failed: {exc}") from exc


def parse_atom(xml_text: str) -> list[Paper]:
    root = ET.fromstring(xml_text)
    papers: list[Paper] = []
    for entry in root.findall("a:entry", NS):
        raw_id = _node_text(entry, "id")
        arxiv_id = re.sub(r"^https?://arxiv\.org/abs/", "", raw_id).split("v")[0]
        if not arxiv_id:
            continue
        links = {link.attrib.get("rel", "alternate"): link.attrib.get("href", "") for link in entry.findall("a:link", NS)}
        primary_node = entry.find("arxiv:primary_category", NS)
        primary = primary_node.attrib.get("term", "") if primary_node is not None else ""
        categories = [c.attrib.get("term", "") for c in entry.findall("a:category", NS)]
        papers.append(
            Paper(
                arxiv_id=arxiv_id,
                title=" ".join(_node_text(entry, "title").split()),
                abstract=" ".join(_node_text(entry, "summary").split()),
                authors=[_node_text(a, "name") for a in entry.findall("a:author", NS)],
                published=_dt(entry.findtext("a:published", "", NS)),
                updated=_dt(entry.findtext("a:updated", "", NS)) if entry.findtext("a:updated", "", NS) else None,
                primary_category=primary or (categories[0] if categories else ""),
                categories=categories,
                comment=_node_text(entry, "comment", ARXIV_NS),
                pdf_url=links.get("related", "") or f"https://arxiv.org/pdf/{arxiv_id}",
                abs_url=links.get("alternate", "") or ABS_URL.format(arxiv_id=arxiv_id),
                doi=_node_text(entry, "doi", ARXIV_NS),
            )
        )
    return papers


def parse_rss(xml_text: str, category: str) -> list[Paper]:
    """The RSS feed carries roughly today's announcements for one category."""
    root = ET.fromstring(xml_text)
    now = datetime.now(timezone.utc)
    papers: list[Paper] = []
    for item in root.iter("item"):
        match = re.search(r"abs/(\d+\.\d+)", (item.findtext("link") or ""))
        if not match:
            continue
        arxiv_id = match.group(1)
        published, uncertain = _rss_date(item)
        if published is None:
            # A feed item without a readable date must never be treated as
            # "just published": guess a conservative date from the arXiv id and
            # flag it for verification on the abstract page.
            guess = id_month_start(arxiv_id)
            published = guess or now
            uncertain = True
        description = html.unescape(item.findtext("description") or "")
        abstract = description.split("Abstract:", 1)[1] if "Abstract:" in description else description
        categories = [c.text.strip() for c in item.findall("category") if c.text]
        papers.append(
            Paper(
                arxiv_id=arxiv_id,
                title=" ".join((item.findtext("title") or "").split()),
                abstract=" ".join(abstract.split()),
                authors=[a.text.strip() for a in item.findall("{http://purl.org/dc/elements/1.1/}creator") if a.text],
                published=published,
                date_uncertain=uncertain,
                primary_category=categories[0] if categories else category,
                categories=categories or [category],
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
                abs_url=ABS_URL.format(arxiv_id=arxiv_id),
            )
        )
    return papers


LISTING_ENTRY_RE = re.compile(
    r"<dt>.*?\[\d+\]</a>.*?/abs/(?P<id>\d+\.\d+).*?<div class='list-title mathjax'>(?:<span class='descriptor'>Title:</span>)?(?P<title>.*?)</div>.*?"
    r"<div class='list-authors'>(?P<authors>.*?)</div>.*?<div class='list-subjects'>(?P<subjects>.*?)</div>",
    re.S,
)
LISTING_PAGE_SIZES = (100, 200, 250, 500, 1000, 2000)


def _snap_page_size(requested: int) -> int:
    for size in LISTING_PAGE_SIZES:
        if requested <= size:
            return size
    return LISTING_PAGE_SIZES[-1]


LISTING_TOTAL_RE = re.compile(r"Total of (\d+) entries")


def _rss_date(item: ET.Element) -> tuple[datetime | None, bool]:
    """Read a feed item's date. Returns ``(value, uncertain)``."""
    for name in ("pubDate", "{http://purl.org/dc/elements/1.1/}date"):
        raw = (item.findtext(name) or "").strip()
        if not raw:
            continue
        try:
            parsed = parsedate_to_datetime(raw)
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)), False
        except (TypeError, ValueError):
            try:
                return _parse_submitted(raw), True
            except ValueError:
                continue
    return None, True


def id_month_start(arxiv_id: str) -> datetime | None:
    """A hard lower bound: modern arXiv ids encode the submission YYMM.

    ``2609.12345`` cannot have been submitted before 2026-09-01, so any id whose
    month is earlier than the requested window is authoritatively out of range,
    whatever the feed claimed.
    """
    match = re.match(r"^(\d{2})(\d{2})\.", arxiv_id)
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not (1 <= month <= 12):
        return None
    return datetime(2000 + year, month, 1, tzinfo=timezone.utc)


def parse_listing(html_text: str, category: str) -> list[Paper]:
    """Fallback parser for https://arxiv.org/list/<cat>/<YYYY-MM>.

    Listing pages carry no abstract and no submission date, so these papers are
    enriched later (:meth:`ArxivClient.enrich_missing`) before they are judged.
    """
    now = datetime.now(timezone.utc)
    papers: list[Paper] = []
    for match in LISTING_ENTRY_RE.finditer(html_text):
        authors = [html.unescape(a) for a in re.findall(r">([^<>]+)</a>", match.group("authors"))]
        subjects = re.sub(r"<[^>]+>", " ", match.group("subjects"))
        primary = ""
        primary_match = re.search(r"primary-subject\">([^<(]*)\(([A-Za-z.\-]+)\)", subjects)
        if primary_match:
            primary = primary_match.group(2)
        papers.append(
            Paper(
                arxiv_id=match.group("id"),
                title=" ".join(html.unescape(re.sub(r"<[^>]+>", "", match.group("title"))).split()),
                abstract="",
                authors=authors,
                published=now,  # replaced by enrich_missing with the real date
                primary_category=primary or category,
                categories=[primary or category],
                pdf_url=f"https://arxiv.org/pdf/{match.group('id')}",
                abs_url=ABS_URL.format(arxiv_id=match.group("id")),
            )
        )
    return papers


ABS_DATE_RE = re.compile(r"Submitted on (\d{1,2} \w{3} \d{4})")
ABS_ABSTRACT_RE = re.compile(r'<blockquote class="abstract[^"]*">(.*?)</blockquote>', re.S)
ABS_META_ABSTRACT = re.compile(r'<meta name="citation_abstract" content="(.*?)"', re.S)
ABS_META_DATE = re.compile(r'<meta name="citation_date" content="([\d/]+)"', re.S)


class ArxivClient:
    """Harvest the latest window across the configured categories.

    Three transports, in order, because arXiv availability is not something we
    can control: the Atom API is the richest and cheapest when the IP is not
    being throttled; the RSS feed reliably carries today's entries; the monthly
    listing page always answers, but carries only ids, titles and authors, so
    those papers are enriched from their abstract page before being judged.
    """

    def __init__(self, categories: Iterable[str], timeout: int = 45, cache_dir: Path | None = None, delay: float = 3.0, retries: int = 3):
        self.categories = list(categories)
        self.timeout = timeout
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.delay = delay
        self.retries = retries
        self.last_request = 0.0
        self.log: list[str] = []
        self.transport = "atom"

    # ------------------------------------------------------------------ http --
    def _polite_get(self, url: str, accept: str = "*/*") -> str:
        wait = self.delay - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            body = _http(url, self.timeout, accept)
        finally:
            self.last_request = time.monotonic()
        return body

    def _cache_path(self, tag: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / f"{hashlib.sha1(tag.encode('utf-8')).hexdigest()[:16]}.xml"

    def _cached(self, tag: str, fetch) -> str | None:
        path = self._cache_path(tag)
        if path and path.exists():
            return path.read_text(encoding="utf-8")
        body = fetch()
        if body and path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        return body or None

    # -------------------------------------------------------------- search --
    def search(self, days: int = 3, max_results: int = 800, deadline: float | None = None) -> list[Paper]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        papers: dict[str, Paper] = {}
        via_atom: set[str] = set()

        for category in self.categories:
            if deadline and time.monotonic() > deadline:
                self.log.append("harvest stopped early: time budget reached")
                break
            found = self._atom_category(category, cutoff, deadline)
            if found:
                via_atom.add(category)
            else:
                found = self._rss_category(category, deadline)
                if found:
                    self.transport = "rss"
            for paper in found:
                papers.setdefault(paper.arxiv_id, paper)

        # RSS only carries roughly today's announcements, so a window longer than
        # a day would silently collapse to "today". Fill those categories from the
        # monthly listing pages, whose ids/abstracts are completed afterwards.
        thin = []
        for category in self.categories:
            if category in via_atom:
                continue
            ages = [(datetime.now(timezone.utc) - p.published.astimezone(timezone.utc)).days for p in papers.values() if category in p.categories or p.primary_category == category]
            spread = max(ages) if ages else 0
            if spread < max(1, days - 1):
                thin.append(category)
        if thin and not (deadline and time.monotonic() > deadline):
            for category in thin:
                added = 0
                for paper in self._listing_category(category, days):
                    if paper.arxiv_id not in papers:
                        papers[paper.arxiv_id] = paper
                        added += 1
                if added:
                    self.log.append(f"{category}: listing transport added {added} older candidates")

        recent = [p for p in papers.values() if p.published.astimezone(timezone.utc) >= cutoff]
        recent = [p for p in recent if keep_in_window(p, cutoff)]
        recent.sort(key=lambda p: p.published, reverse=True)
        if len(via_atom) == len(self.categories):
            self.transport = "atom"
        elif self.transport == "atom":
            self.transport = "mixed"
        self.log.append(f"harvested {len(recent)} candidates via {self.transport} over {days} day(s)")
        return recent[:max_results] if max_results else recent

    def _atom_category(self, category: str, cutoff: datetime, deadline: float | None = None) -> list[Paper]:
        day_key = datetime.now(timezone.utc).strftime("%Y%m%d")
        papers: list[Paper] = []
        throttled = False
        for offset in range(0, 400, 100):
            if throttled or (deadline and time.monotonic() > deadline):
                break
            url = urllib.parse.urljoin(
                ATOM_HOST,
                "?" + urllib.parse.urlencode({"search_query": f"cat:{category}", "start": str(offset), "max_results": "100", "sortBy": "submittedDate", "sortOrder": "descending"}),
            )
            tag = f"{day_key}:atom:{category}:{offset}"
            body = None
            for attempt in range(2 if offset == 0 else 1):
                try:
                    body = self._cached(tag, lambda url=url: self._polite_get(url))
                    break
                except ArxivError as exc:
                    if "429" in str(exc):
                        # Throttling is not fixed by hammering: stop this category
                        # immediately and let the other transports take over.
                        self.log.append(f"atom {category}@{offset} throttled by arXiv; switching transport")
                        throttled = True
                        break
                    if attempt == 0:
                        time.sleep(self.delay)
            if body is None:
                break
            try:
                batch = parse_atom(body)
            except (ET.ParseError, ValueError):
                # parse_atom also raises ValueError when a record has no readable
                # <published>; an unexpected body must degrade, not abort the run.
                break
            if not batch:
                break
            papers.extend(p for p in batch if p.published.astimezone(timezone.utc) >= cutoff)
            oldest = min(p.published for p in batch).astimezone(timezone.utc)
            if oldest < cutoff or len(batch) < 100:
                break
        return dedupe(papers)

    def _rss_category(self, category: str, deadline: float | None = None) -> list[Paper]:
        if deadline and time.monotonic() > deadline:
            return []
        url = RSS_URL.format(category=category)
        day_key = datetime.now(timezone.utc).strftime("%Y%m%d")
        try:
            body = self._cached(f"{day_key}:rss:{category}", lambda: self._polite_get(url, accept="application/rss+xml"))
        except ArxivError as exc:
            self.log.append(f"rss {category} failed: {exc}")
            return []
        if not body:
            return []
        try:
            return dedupe(parse_rss(body, category))
        except ET.ParseError:
            return []

    def _listing_category(self, category: str, days: int) -> list[Paper]:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        first_url = LISTING_URL.format(category=category, month=month) + "?skip=0&show=25"
        try:
            probe = self._cached(f"listing:{category}:{month}:probe", lambda: self._polite_get(first_url, accept="text/html"))
        except ArxivError as exc:
            self.log.append(f"listing {category} failed: {exc}")
            return []
        if not probe:
            return []
        total_match = LISTING_TOTAL_RE.search(probe)
        total = int(total_match.group(1)) if total_match else 0
        if not total:
            return []
        # arXiv only accepts a fixed set of page sizes; anything else is a 400.
        want = _snap_page_size(max(100, int(total / 30 * days * 1.6) + 60))
        want = min(want, total)
        skip = max(0, total - want)
        url = LISTING_URL.format(category=category, month=month) + f"?skip={skip}&show={want}"
        try:
            body = self._cached(f"listing:{category}:{month}:{skip}:{want}", lambda: self._polite_get(url, accept="text/html"))
        except ArxivError as exc:
            self.log.append(f"listing tail {category} failed: {exc}")
            return []
        if not body:
            return []
        self.transport = "listing"
        return dedupe(parse_listing(body, category))

    # ------------------------------------------------------------- enrichment --
    def verify_dates(self, papers: list[Paper], deadline: float | None = None) -> int:
        """Re-read the true submission date from each abstract page.

        Feed dates are the weak link in this pipeline: some RSS items carry no
        date at all and would otherwise silently become "today". This is the last
        gate before a paper is written into the digest.
        """
        verified = 0
        for paper in papers:
            if deadline is not None and time.monotonic() > deadline:
                self.log.append("date verification stopped: time budget reached")
                break
            try:
                body = self._cached(f"abs:{paper.arxiv_id}", lambda paper=paper: self._polite_get(ABS_URL.format(arxiv_id=paper.arxiv_id), accept="text/html"))
            except ArxivError as exc:
                # One flaky abstract page must never kill a 40-minute run: the
                # paper keeps its feed date and the caller decides what it is worth.
                self.log.append(f"abs page failed for {paper.arxiv_id}: {exc}")
                continue
            if not body:
                continue
            date_match = ABS_META_DATE.search(body) or ABS_DATE_RE.search(body)
            parsed = _parse_submitted(date_match.group(1)) if date_match else None
            if parsed:
                paper.published = parsed
                paper.date_uncertain = False
                verified += 1
        return verified

    def enrich_missing(self, papers: list[Paper], deadline_monotonic: float | None = None) -> int:
        """Complete partial records from each paper's abstract page.

        Handles two cases: papers harvested from the listing pages (no abstract)
        and feed items whose publication date could not be read, whose date is
        only a guess until it is verified here. Returns how many were filled.
        """
        filled = 0
        for paper in papers:
            if deadline_monotonic is not None and time.monotonic() > deadline_monotonic:
                self.log.append("enrichment stopped: time budget reached")
                break
            if paper.abstract and not paper.date_uncertain:
                continue
            try:
                body = self._cached(f"abs:{paper.arxiv_id}", lambda paper=paper: self._polite_get(ABS_URL.format(arxiv_id=paper.arxiv_id), accept="text/html"))
            except ArxivError as exc:
                # Same rule as verify_dates: a transient failure leaves the record
                # incomplete (and visibly so) instead of ending the whole digest.
                self.log.append(f"abs page failed for {paper.arxiv_id}: {exc}")
                continue
            if not body:
                continue
            abstract_match = ABS_META_ABSTRACT.search(body) or ABS_ABSTRACT_RE.search(body)
            if abstract_match:
                paper.abstract = " ".join(html.unescape(re.sub(r"<[^>]+>", "", abstract_match.group(1))).split())
            date_match = ABS_META_DATE.search(body) or ABS_DATE_RE.search(body)
            if date_match:
                parsed = _parse_submitted(date_match.group(1))
                if parsed:
                    paper.published = parsed
                    paper.date_uncertain = False
            paper.abs_url = ABS_URL.format(arxiv_id=paper.arxiv_id)
            filled += 1
        return filled


def _parse_submitted(value: str) -> datetime | None:
    value = value.strip()
    try:
        if "/" in value:  # 2026/07/11 from citation_date
            year, month, day = [int(x) for x in value.split("/")]
            return datetime(year, month, day, tzinfo=timezone.utc)
        return datetime.strptime(value, "%d %b %Y").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def keep_in_window(paper: Paper, cutoff: datetime) -> bool:
    """Drop anything whose arXiv id proves it predates the requested window."""
    bound = id_month_start(paper.arxiv_id)
    if bound is None:
        return True
    # An id from an earlier month is at least ~30 days old; only ids from the
    # current month (or undatable ones) can belong to a <=7 day window.
    return bound >= cutoff.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def dedupe(papers: Iterable[Paper]) -> list[Paper]:
    seen: dict[str, Paper] = {}
    for paper in papers:
        seen.setdefault(paper.arxiv_id, paper)
    return list(seen.values())
