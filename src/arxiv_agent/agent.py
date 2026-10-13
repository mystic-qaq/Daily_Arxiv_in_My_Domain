"""Orchestration: one call in, one Markdown file out.

Constraints taken from the requirements and enforced here (not only in the CLI):
concurrency never exceeds 2, total wall clock stays under the time budget, and
the pipeline degrades predictably instead of failing halfway through a run.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .analyze import analyze_paper, daily_note, judge_projects
from .arxiv_client import ArxivClient, ArxivError, keep_in_window
from .config import MAX_CONCURRENCY, Settings
from .fulltext import FullTextFetcher
from .github_client import TRENDING_QUERIES, GitHubClient, to_trending_project
from .llm import CachingBackend, CodeBuddyBackend, LLMBackend, OfflineBackend, build_backend
from .models import Paper, TrendingProject
from .report import write_report
from .strategy import StrategyStore
from .triage import judge, screen, select_portfolio


class _CountingBackend:
    """Count model calls so the report can be honest about the resources spent."""

    def __init__(self, inner: LLMBackend):
        self.inner = inner
        self.calls = 0
        self.failures = 0
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self.inner.name

    def complete(self, system: str, user: str, options: Any = None) -> str:
        with self._lock:
            self.calls += 1
        return self.inner.complete(system, user, options)

    def complete_json(self, system: str, user: str, options: Any = None) -> Any:
        with self._lock:
            self.calls += 1
        try:
            return self.inner.complete_json(system, user, options)
        except Exception:
            with self._lock:
                self.failures += 1
            raise


class DailyArxivAgent:
    def __init__(self, settings: Settings, backend: LLMBackend | None = None):
        self.settings = settings
        self.settings.clamp()  # hardening even if constructed directly
        self.settings.max_concurrency = max(1, min(MAX_CONCURRENCY, self.settings.max_concurrency))
        self.strategy = StrategyStore(settings.strategy_file)
        self.arxiv = ArxivClient(settings.categories, cache_dir=settings.cache_dir, delay=settings.request_delay)
        self.fulltext = FullTextFetcher(settings.cache_dir)
        self.github = GitHubClient()
        backend = backend if backend is not None else build_backend(settings.model, settings.provider, offline=settings.offline)
        if not isinstance(backend, OfflineBackend):
            # Cached replies make same-day reruns and crash recoveries free.
            backend = CachingBackend(backend, Path(settings.cache_dir) / "llm")
        self.backend = _CountingBackend(backend)
        self.notes: list[str] = []
        self.started = time.monotonic()

    def _confirm_dates(self, selected: list[Paper], pool: list[Paper], notes: list[str]) -> list[Paper]:
        """Trust nothing about the date until the abstract page confirms it.

        Feeds are unreliable: some RSS items carry no date and would otherwise be
        treated as brand new, letting months-old papers into a 3-day digest. Every
        finalist is re-dated here, and dropped papers are replaced from the same
        ranked pool so the digest keeps its size.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.days)
        deadline = self.started + self.settings.time_budget_min * 60 * 0.4
        wanted = len(selected)
        self.arxiv.verify_dates(selected, deadline=deadline)
        in_window = lambda paper: (  # noqa: E731 - local readability
            paper.published.astimezone(timezone.utc) >= cutoff and keep_in_window(paper, cutoff)
        )
        kept = [p for p in selected if in_window(p)]
        dropped = [p for p in selected if p not in kept]
        if not dropped:
            return kept
        notes.append(f"按 abs 页核实提交日期后剔除 {len(dropped)} 篇窗口外论文（" + "、".join(p.arxiv_id for p in dropped[:5]) + "），已从候补补位。")
        chosen_ids = {p.arxiv_id for p in selected}
        backfill = sorted((p for p in pool if p.arxiv_id not in chosen_ids), key=lambda p: -p.relevance)
        for candidate in backfill:
            if len(kept) >= wanted:
                break
            self.arxiv.verify_dates([candidate], deadline=deadline)
            if in_window(candidate):
                kept.append(candidate)
        return kept

    # -------------------------------------------------------------- helpers --
    def elapsed_minutes(self) -> float:
        return (time.monotonic() - self.started) / 60.0

    def remaining_ratio(self) -> float:
        used = self.elapsed_minutes() / max(self.settings.time_budget_min, 1)
        return max(0.0, 1.0 - used)

    def budget_exhausted(self, threshold: float = 0.0) -> bool:
        return self.remaining_ratio() <= threshold

    # ----------------------------------------------------------------- work --
    def remaining_seconds(self) -> float:
        """Wall clock left inside the user's budget."""
        return max(0.0, self.settings.time_budget_min * 60 - (time.monotonic() - self.started))

    def _tune_model_timeout(self, attempts: int = 2) -> None:
        """Shrink each model call so the run can still end inside the budget.

        Deep analysis is the only stage that can take minutes, and a provider
        that stalls is exactly how a "45 minute" job becomes a 60+ minute one.
        The live timeout is re-derived from the remaining wall clock before every
        call, leaving room for the retry and the report itself.
        """
        inner: Any = self.backend
        while hasattr(inner, "inner") and not isinstance(inner, CodeBuddyBackend):
            inner = inner.inner
        if not isinstance(inner, CodeBuddyBackend):
            return
        per_attempt = (self.remaining_seconds() - 30) / max(1, attempts)
        inner.timeout = int(max(90, min(getattr(inner, "default_timeout", 600), per_attempt)))

    def work(self) -> str:
        notes = self.notes
        harvested: list[Paper] = []
        try:
            harvest_deadline = self.started + self.settings.time_budget_min * 60 * 0.25
            harvested = self.arxiv.search(self.settings.days, max_results=self.settings.max_candidates, deadline=harvest_deadline)
        except ArxivError as exc:
            notes.append(f"arXiv 抓取失败：{exc}")
            raise
        if not harvested:
            # The user would rather see an honest failure than a padded digest.
            raise RuntimeError(f"最近 {self.settings.days} 天内没有抓到任何候选论文（可尝试增大 --days 或检查网络）")

        # A daily digest that repeats yesterday's picks is worse than a shorter
        # one: anything already surfaced in the window is filtered out here.
        seen = _load_seen(self.settings.state_dir / "seen.json")
        fresh = [p for p in harvested if p.arxiv_id not in seen]
        repeated = len(harvested) - len(fresh)
        if repeated:
            notes.append(f"已在最近 {SEEN_TTL_DAYS} 天的日报中推荐过、本次跳过 {repeated} 篇（记录见 .arxiv-agent/seen.json）。")
        harvested = fresh or harvested

        pool = screen(harvested, self.settings)
        if not pool:
            pool = harvested[: self.settings.triage_pool]
        # Papers that came from the listing transport have no abstract yet; give
        # them one before the judge sees them, and drop anything that turns out
        # to sit outside the requested window.
        deadline = self.started + self.settings.time_budget_min * 60 * 0.45
        if any(not p.abstract or p.date_uncertain for p in pool):
            self.arxiv.enrich_missing(pool, deadline_monotonic=deadline)
        # Re-apply the window: papers whose real date turned out to be older are
        # dropped here, before the expensive model stages see them.
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.settings.days)
        anchored = [p for p in pool if p.published.astimezone(timezone.utc) >= cutoff and keep_in_window(p, cutoff)]
        dropped_out_of_window = len(pool) - len(anchored)
        if dropped_out_of_window:
            notes.append(f"按 abs 页上的实际提交日期过滤掉 {dropped_out_of_window} 篇窗口外论文（部分 RSS 条目没有日期，已从 abs 页核实）。")
        if anchored:
            pool = anchored

        batches = [pool[i: i + self.settings.triage_batch] for i in range(0, len(pool), self.settings.triage_batch)]
        workers = self.settings.max_concurrency
        judged_rounds = 0
        with ThreadPoolExecutor(max_workers=workers) as executor:
            # Explicit futures: executor.map queues every batch up front, so
            # breaking out of its iteration cannot actually stop the run.
            pending = [executor.submit(judge, batch, self.backend, self.strategy) for batch in batches]
            for future in pending:
                future.result()
                judged_rounds += 1
                if self.budget_exhausted(0.30):
                    notes.append("模型评审阶段耗时超出预期，未完成的批次已取消。")
                    for rest in pending:
                        rest.cancel()
                    break

        selected, selection_stats = select_portfolio(pool, self.settings, self.strategy)
        if not selected:
            raise RuntimeError("初筛后没有留下任何候选论文；请放宽画像或增大检索窗口")

        selected = self._confirm_dates(selected, pool, notes)
        if not selected:
            raise RuntimeError("按 abs 页核实后没有留下窗口内的论文；请放宽画像或增大 --days")

        fulltext_chars = self.settings.fulltext_chars
        skip_code = self.settings.skip_code
        if self.budget_exhausted(0.35):
            fulltext_chars = int(fulltext_chars * 0.6)
            notes.append("时间预算紧张：正文截取长度已下调。")
        if self.budget_exhausted(0.20) and not skip_code:
            skip_code = True
            notes.append("时间预算紧张：跳过代码抓取，报告中不写“代码与实践”。")

        # Two stages, not one fused loop: evidence fetching is network-bound and
        # deep reading is model-bound, so interleaving them inside a worker left
        # one resource idle whenever the other was busy. Fetch everything first
        # (attach_repo reads full_text, so the order inside a thread matters),
        # then spend the LLM workers on analysis only.
        def fetch_evidence(paper: Paper) -> None:
            remaining = self.remaining_seconds()
            if remaining > 240:
                text, source, size = self.fulltext(paper, max_chars=fulltext_chars)
                paper.full_text, paper.full_text_source, paper.full_text_chars = text, source, size
            if not skip_code and remaining > 200:
                self.github.attach_repo(paper)

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(fetch_evidence, selected))

        def analyze(paper: Paper) -> Paper:
            # Re-derive the call budget every time: with two workers sharing the
            # same wall clock, a fixed timeout cannot keep the run on schedule.
            if self.remaining_seconds() < 90:
                from .analyze import _degraded

                paper.analysis = _degraded(paper, "时间预算耗尽，未进行深度解析。")
                return paper
            self._tune_model_timeout(attempts=2)
            paper.analysis = analyze_paper(paper, self.backend, self.strategy, body_chars=fulltext_chars)
            return paper

        with ThreadPoolExecutor(max_workers=workers) as executor:
            list(executor.map(analyze, selected))
        # Only worth calling if most papers actually got analysed.
        daily_note_worth_it = sum(1 for p in selected if not p.analysis.get("confidence", "").startswith("低")) >= 2

        daily: dict[str, Any] = {"daily_note": "", "watchwords": []}
        if daily_note_worth_it and self.remaining_seconds() > 180:
            self._tune_model_timeout(attempts=1)
            daily = daily_note(selected, self.backend, self.strategy)

        _save_seen(self.settings.state_dir / "seen.json", selected)

        projects: list[TrendingProject] = []
        if not self.settings.skip_trending and self.remaining_seconds() > 150:
            raw_projects = self.github.trending(TRENDING_QUERIES, window_days=7)
            if raw_projects:
                picked = judge_projects(raw_projects, self.backend, limit=5)
                projects = [to_trending_project(p, p.get("why", "")) for p in picked]

        stats = {
            "harvested": len(harvested),
            "screened": len(pool),
            "judged": judged_rounds,
            "slots": selection_stats.get("slots", {}),
            "dropped_by_area": selection_stats.get("dropped_by_area", {}),
            "minutes": round(self.elapsed_minutes(), 1),
            "llm_calls": self.backend.calls,
            "llm_failures": self.backend.failures,
            "provider": self.backend.name,
            "transport": self.arxiv.transport,
            "notes": notes,
            "github_calls": self.github.calls,
        }
        if self.github.calls >= self.github.api_budget:
            notes.append(f"GitHub API 调用预算（{self.github.api_budget} 次）用尽，部分仓库可能未检索；设置 GITHUB_TOKEN 可放宽。")

        path = write_report(Path(self.settings.output_dir), date.today(), selected, self.settings, daily, projects, stats)
        return str(path)


SEEN_TTL_DAYS = 7


def _load_seen(path: Path) -> dict[str, str]:
    """Paper ids already surfaced recently, so a daily digest never repeats."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    horizon = (date.today() - timedelta(days=SEEN_TTL_DAYS)).isoformat()
    return {str(k): str(v) for k, v in data.items() if str(v) >= horizon}


def _save_seen(path: Path, papers: list[Paper]) -> None:
    today = date.today().isoformat()
    data = _load_seen(path)
    data.update({paper.arxiv_id: today for paper in papers})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
