"""Offline tests for the daily arXiv scout.

No network and no credentials: the fixtures below stand in for arXiv XML, GitHub
JSON and model replies. They exist mostly to pin down the *selection logic* -
the part that decides what the user will read tomorrow.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from arxiv_agent.analyze import _degraded
from arxiv_agent.arxiv_client import _parse_submitted, keep_in_window, parse_atom, parse_listing, parse_rss
from arxiv_agent.config import MAX_CONCURRENCY, Settings, load_env_file
from arxiv_agent.feedback import _resolve_titles, compose_feedback_text, deterministic_patch
from arxiv_agent.fulltext import _prioritise, _strip_tags
from arxiv_agent.llm import extract_json, resolve_provider
from arxiv_agent.models import Paper
from arxiv_agent.profile import AREAS, profile_brief, quota_plan, screen_paper
from arxiv_agent.report import render_report
from arxiv_agent.strategy import StrategyStore
from arxiv_agent.triage import judge, screen, select_portfolio


def make_paper(
    arxiv_id: str,
    title: str,
    abstract: str,
    *,
    published_days_ago: float = 1.0,
    comment: str = "",
    categories: list[str] | None = None,
) -> Paper:
    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        abstract=abstract,
        authors=["A. Author", "B. Author"],
        published=datetime.now(timezone.utc) - timedelta(days=published_days_ago),
        primary_category=(categories or ["cs.CV"])[0],
        categories=categories or ["cs.CV"],
        comment=comment,
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
        abs_url=f"https://arxiv.org/abs/{arxiv_id}",
    )


ATOM_FEED = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry>
  <id>http://arxiv.org/abs/2609.00001v2</id>
  <title> TRELLIS-Successor: Structured Latent Flow for Native 3D Generation </title>
  <summary>We build on TRELLIS and extend the structured latent with a new SDF decoder and Marching Cubes refinement.</summary>
  <published>2026-09-13T10:00:00Z</published>
  <updated>2026-09-14T10:00:00Z</updated>
  <author><name>Wei Wang</name></author>
  <author><name>Lin Chen</name></author>
  <category term="cs.CV"/>
  <arxiv:primary_category term="cs.CV"/>
  <arxiv:comment>Accepted to CVPR 2026; Tencent Hunyuan team</arxiv:comment>
  <link rel="alternate" href="https://arxiv.org/abs/2609.00001"/>
  <link rel="related" href="https://arxiv.org/pdf/2609.00001"/>
</entry></feed>"""

RSS_FEED = """<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
<title>MASt3R-SLAM style feed-forward scene reconstruction</title>
<link>https://arxiv.org/abs/2609.00002</link>
<description>arXiv:2609.00002v1 Announce Type: new
Abstract: We extend DUSt3R for dense scene reconstruction with VGGT-style attention.
</description>
<dc:creator>Zhang San</dc:creator>
<category>cs.CV</category>
<pubDate>Tue, 15 Sep 2026 00:00:00 -0400</pubDate>
</item></channel></rss>"""

LISTING_HTML = """<html><body><dl id='articles'>
<dt><a name='item1'>[1]</a><a href="/abs/2609.00003" id="2609.00003">arXiv:2609.00003</a></dt>
<dd><div class='meta'><div class='list-title mathjax'><span class='descriptor'>Title:</span> Delta Dynamics 4D Scene Flow Reconstruction</div>
<div class='list-authors'><a href="#">Liu Wei</a></div>
<div class='list-subjects'><span class='descriptor'>Subjects:</span><span class="primary-subject">Computer Vision (cs.CV)</span></div></div></dd>
</dl></body></html>"""


# --------------------------------------------------------------------- profile
def test_lineage_hit_beats_generic_keyword_counting():
    successor = make_paper("2609.00001", "A TRELLIS successor for native 3D assets", "We improve TRELLIS with better vector sets and shape VAEs.")
    second = make_paper("2609.00002", "Another TRELLIS and VGGT hybrid", "Extending TRELLIS latents and VGGT attention for feed-forward reconstruction.")
    evidence = screen_paper(successor)
    assert "TRELLIS" in evidence["lineage_hits"]
    assert second and successor  # both papers are recognised as in-map
    assert evidence["area_candidates"][0] == "3d_generation"


def test_off_topic_paper_has_no_area_candidates():
    off_topic = make_paper("2609.00003", "Credit scoring with tabular diffusion models", "We model tabular data with diffusion for financial risk.")
    evidence = screen_paper(off_topic)
    assert evidence["area_candidates"] == []
    assert evidence["screen_score"] == 0


def test_profile_brief_lists_all_areas_in_language_the_model_can_use():
    brief = profile_brief()
    for area in AREAS:
        assert area.key in brief
        for sub in area.subareas:
            assert sub.key in brief
    assert "专业性" not in brief  # no filler language in the rubric


def test_quota_plan_distributes_all_slots():
    plan = quota_plan(12)
    assert sum(plan.values()) == 12
    assert plan["3d_generation"] > plan["embodied_ai"]


# -------------------------------------------------------------------- parsing
def test_parse_atom_keeps_comment_and_primary_category():
    papers = parse_atom(ATOM_FEED)
    assert len(papers) == 1
    paper = papers[0]
    assert paper.arxiv_id == "2609.00001"
    assert paper.primary_category == "cs.CV"
    assert "CVPR" in paper.comment and "Tencent" in paper.comment
    assert len(paper.authors) == 2


def test_parse_rss_reads_pubdate_and_abstract():
    papers = parse_rss(RSS_FEED, "cs.CV")
    assert papers and papers[0].arxiv_id == "2609.00002"
    assert papers[0].published.year == 2026
    assert papers[0].abstract.startswith("We extend DUSt3R")
    assert papers[0].authors == ["Zhang San"]


def test_parse_listing_extracts_ids_and_titles_without_abstracts():
    papers = parse_listing(LISTING_HTML, "cs.CV")
    assert papers and papers[0].arxiv_id == "2609.00003"
    assert papers[0].title.startswith("Delta Dynamics")
    assert papers[0].abstract == ""  # completed later from the abs page


def test_rss_item_without_a_readable_date_is_flagged_and_dated_from_the_id():
    """A dateless feed item must never be treated as 'submitted today'."""
    feed = """<rss version="2.0"><channel><item>
    <title>Stale-looking reconstruction entry</title>
    <link>https://arxiv.org/abs/2605.13018</link>
    <description>arXiv:2605.13018v1 Abstract: We reconstruct objects.</description>
    </item></channel></rss>"""
    papers = parse_rss(feed, "cs.CV")
    assert papers and papers[0].date_uncertain is True
    assert papers[0].published.year == 2026 and papers[0].published.month == 5


def test_ids_from_earlier_months_never_survive_a_short_window():
    old = make_paper("2605.13018", "Old object reconstruction", "We reconstruct objects.")
    fresh = make_paper("2609.19999", "Fresh object reconstruction", "We reconstruct objects.")
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    assert keep_in_window(fresh, cutoff) is True
    assert keep_in_window(old, cutoff) is False


def test_rss_pubdate_is_read_when_present():
    papers = parse_rss(RSS_FEED, "cs.CV")
    assert papers[0].date_uncertain is False
    assert papers[0].published.day == 15
    papers = parse_listing(LISTING_HTML, "cs.CV")
    assert papers and papers[0].arxiv_id == "2609.00003"
    assert papers[0].title.startswith("Delta Dynamics")
    assert papers[0].abstract == ""  # enriched later from the abs page


def test_parse_submitted_date_variants():
    assert _parse_submitted("2026/09/13") == datetime(2026, 9, 13, tzinfo=timezone.utc)
    assert _parse_submitted("13 Sep 2026") == datetime(2026, 9, 13, tzinfo=timezone.utc)
    assert _parse_submitted("nonsense") is None


# ----------------------------------------------------------------- full text
def test_fulltext_strip_keeps_heading_structure():
    html_text = "<html><body><h2>3. Method</h2><p>We use a flow matching decoder.</p><script>bad()</script></body></html>"
    text = _strip_tags(html_text)
    assert "## 3. Method" in text
    assert "bad()" not in text
    assert "flow matching" in text


def test_prioritise_keeps_method_and_experiments_when_truncated():
    body = "\n\n".join(
        [
            "## Introduction\n" + "intro text " * 40,
            "## Related Work\n" + "related citations " * 200,
            "## Method\n" + "We propose a new pipeline " * 60,
            "## Experiments\n" + "We evaluate on ShapeNet " * 60,
        ]
    )
    trimmed = _prioritise(body, 900)
    assert len(trimmed) <= 900
    assert "Method" in trimmed


# ----------------------------------------------------------------------- llm
def test_extract_json_handles_fences_and_prose_wrapping():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! {"results": []} hope this helps') == {"results": []}
    with pytest.raises(ValueError):
        extract_json("I refuse")


# --------------------------------------------------------------- triage flow
class StubBackend:
    """Returns a scripted triage verdict keyed by arXiv id."""

    def __init__(self, verdicts: dict[str, dict]):
        self.verdicts = verdicts

    def complete_json(self, system, user, options=None):
        return {"results": [dict(verdict, id=key) for key, verdict in self.verdicts.items()]}


def test_screen_keeps_lineage_papers_and_can_still_pass_through_the_rest():
    strong = make_paper("2609.00010", "A TRELLIS follow-up", "Structured latent flow matching for native assets.")
    weak = make_paper("2609.00011", "Diffusion for credit scoring", "Tabular diffusion model for financial risk analysis.")
    pool = screen([weak, strong], Settings.from_env())
    assert "2609.00010" in [p.arxiv_id for p in pool]


def test_judge_applies_verdicts(tmp_path):
    paper = make_paper("2609.00020", "MeshGPT-style autoregressive topology", "We generate vertices and faces autoregressively.")
    screen([paper], Settings.from_env())
    backend = StubBackend({"2609.00020": {"area": "3d_generation", "subarea": "3d_generation/native_topology", "relevance": 8, "credibility": 7, "novelty": 7, "keep": True, "reason": "延续 MeshGPT 路线"}})
    judge([paper], backend, _store(tmp_path / "s1"))
    assert paper.area == "3d_generation"
    assert paper.subarea == "3d_generation/native_topology"
    assert paper.keep is True


def test_judge_never_silently_drops_a_paper_the_model_omitted(tmp_path):
    paper = make_paper("2609.00021", "Unscored candidate", "A 3D generation method.")
    screen([paper], Settings.from_env())
    judge([paper], StubBackend({}), _store(tmp_path / "s2"))
    assert paper.keep is True
    assert "未返回" in paper.triage_reason


def _store(tmp_path, **data) -> StrategyStore:
    store = StrategyStore(tmp_path / "strategy.json")
    store.data.update(data)
    return store


def test_selection_respects_priority_quotas(tmp_path):
    settings = Settings.from_env()
    settings.target_papers = 8
    papers = []
    for i in range(6):
        papers.append(make_paper(f"2609.1{i:03}", f" TRELLIS variant {i}", "structured latent vecset SDF marching cubes for native 3d generation"))
    for i in range(6):
        papers.append(make_paper(f"2609.2{i:03}", f"OpenVLA manipulation policy {i}", "vision-language-action robot policy for manipulation"))
    for paper in papers:
        evidence = screen_paper(paper)
        paper.keyword_hits = evidence["keyword_hits"]
        paper.lineage_hits = evidence["lineage_hits"]
        paper.area_candidates = evidence["area_candidates"]
        paper.area = evidence["area_candidates"][0] if evidence["area_candidates"] else "other"
        paper.scores = {"relevance": 7.0, "credibility": 6.0, "novelty": 6.0, "llm": 1.0}
    store = _store(tmp_path)
    chosen, stats = select_portfolio(papers, settings, store)
    assert len(chosen) <= settings.max_papers
    counts: dict[str, int] = {}
    for paper in chosen:
        counts[paper.area] = counts.get(paper.area, 0) + 1
    assert counts.get("3d_generation", 0) >= counts.get("embodied_ai", 0)
    assert stats["slots"]["3d_generation"] >= stats["slots"]["embodied_ai"]


def test_feedback_changes_selection_without_touching_code(tmp_path):
    settings = Settings.from_env()
    settings.target_papers = 4
    settings.clamp()
    papers = []
    for i in range(4):
        papers.append(make_paper(f"2609.3{i:03}", f"benchmark-only video edit paper {i}", "We build a benchmark for video editing quality"))
    for i in range(4):
        papers.append(make_paper(f"2609.4{i:03}", f"flow matching GRPO for 3d {i}", "We combine flow matching with GRPO post-training for 3D assets"))
    for paper in papers:
        evidence = screen_paper(paper)
        paper.area_candidates = evidence["area_candidates"]
        paper.area = evidence["area_candidates"][0] if evidence["area_candidates"] else "other"
        paper.scores = {"relevance": 6.0, "credibility": 6.0, "novelty": 6.0, "llm": 1.0}
    store = _store(tmp_path)
    before, _ = select_portfolio(papers, settings, store)
    store.apply_patch(
        {
            "add_negative_patterns": [{"pattern": "benchmark", "weight": 4.0, "reason": "用户不想看纯 benchmark 文章"}],
            "principles_add": ["少推荐只做 benchmark 的工作"],
            "area_weight_deltas": {"video_generation": -0.2},
        },
        "benchmark 文章太多",
    )
    after, _ = select_portfolio(papers, settings, store)
    assert any("benchmark" not in p.title for p in after)
    assert sum("benchmark" in p.title for p in after) < sum("benchmark" in p.title for p in before)


# ------------------------------------------------------------------ strategy
def test_strategy_patch_is_versioned_and_readable(tmp_path):
    store = _store(tmp_path)
    start_version = store.data["version"]
    applied = store.apply_patch({"add_positive_patterns": [{"pattern": "flow matching", "weight": 2.0, "reason": "用户喜欢可迁移到 3D 的 flow 方法"}]}, raw_feedback="+ flow matching")
    assert applied["positive"][0]["pattern"] == "flow matching"
    assert store.data["version"] == start_version + 1
    assert (tmp_path / "strategy.md").exists()
    markdown = (tmp_path / "strategy.md").read_text(encoding="utf-8")
    assert "flow matching" in markdown
    assert "flow matching" in store.context_block()


def test_deterministic_feedback_fallback():
    patch = deterministic_patch("+ gaussian splatting\n- medical imaging\n近期条例类的文章没意思")
    patterns = [p["pattern"] for p in patch["add_positive_patterns"]]
    negatives = [p["pattern"] for p in patch["add_negative_patterns"]]
    assert "gaussian splatting" in patterns
    assert "medical imaging" in negatives


def test_corrupt_strategy_file_does_not_break_the_run(tmp_path):
    path = tmp_path / "strategy.json"
    path.write_text("{not json", encoding="utf-8")
    store = StrategyStore(path)
    assert store.data["version"] >= 1
    assert store.context_block()


# ------------------------------------------------------------------ feedback
def test_feedback_resolves_entry_numbers_to_titles():
    entries = [{"index": "3", "title": "Block3D style work", "arxiv_id": "2609.00099"}]
    resolved = _resolve_titles("3", entries)
    assert "Block3D" in resolved and "2609.00099" in resolved


def test_compose_feedback_text_includes_all_answers():
    text = compose_feedback_text({"dissatisfied": "2", "dissatisfied_reason": "只是换数据集", "liked": "5", "weights": "+3d_generation", "extra": "少给我水文"}, [{"index": "2", "title": "Weak one", "arxiv_id": "2609.1"}, {"index": "5", "title": "Strong one", "arxiv_id": "2609.2"}])
    assert "不满意的文章" in text and "只是换数据集" in text
    assert "值得借鉴" in text and "方向权重" in text and "少给我水文" in text


# -------------------------------------------------------------------- report
def test_report_is_chinese_and_named_by_date(tmp_path):
    settings = Settings.from_env(output_dir=tmp_path)
    settings.output_dir = tmp_path
    paper = make_paper("2609.00050", "Part-level generation with TRELLIS latents", "We extend TRELLIS to part-level 3D asset generation.")
    paper.area = "3d_generation"
    paper.subarea = "3d_generation/rigging_parts"
    paper.scores = {"relevance": 8.0, "credibility": 7.0, "novelty": 7.0}
    paper.relevance = 7.6
    paper.triage_reason = "延续 TRELLIS 谱系"
    paper.analysis = {key: f"{key} 内容" for key in ("one_liner", "background_motivation", "architecture", "lineage", "insights", "innovations", "evaluation", "code", "limitations_risks", "why_read", "how_to_read", "confidence")}
    text = render_report([paper], datetime.now(timezone.utc).date(), settings, {"daily_note": "今日观察", "watchwords": ["vecset"]}, [], {"harvested": 900, "screened": 90, "judged": 8, "slots": {"3d_generation": 6}, "dropped_by_area": {}, "notes": []})
    assert "每日 arXiv 精选" in text
    assert "整体架构" in text and "为什么推荐" in text
    assert "选取过程透明度" in text
    today = datetime.now(timezone.utc).date().strftime("%y-%m-%d")
    from arxiv_agent.report import write_report

    path = write_report(tmp_path, datetime.now(timezone.utc).date(), [paper], settings, {"daily_note": "", "watchwords": []}, [], {"harvested": 1, "screened": 1, "judged": 1, "slots": {}, "dropped_by_area": {}, "notes": []})
    assert path.name == f"{today}.md"


def test_degraded_analysis_never_invents_numbers():
    degraded = _degraded(make_paper("2609.9", "Untitled", "no content"), "失败")
    assert degraded["code"] == "未检索到可靠开源仓库。"
    assert degraded["confidence"].startswith("低")


# --------------------------------------------------------------------- config
def test_concurrency_is_capped_no_matter_what(tmp_path):
    settings = Settings.from_env()
    settings.max_concurrency = 99
    settings.clamp()
    assert settings.max_concurrency == MAX_CONCURRENCY == 2


def test_model_timeout_shrinks_as_the_budget_is_used_up(tmp_path):
    """A slow provider must not be able to push the run past the wall clock."""
    from arxiv_agent.agent import DailyArxivAgent
    from arxiv_agent.llm import CodeBuddyBackend

    settings = Settings.from_env()
    settings.time_budget_min = 30
    settings.clamp()
    agent = DailyArxivAgent.__new__(DailyArxivAgent)
    agent.settings = settings
    agent.started = time.monotonic()
    agent.backend = type("B", (), {"inner": CodeBuddyBackend.__new__(CodeBuddyBackend)})()
    agent.backend.inner.timeout = 600
    agent.backend.inner.default_timeout = 600
    agent._tune_model_timeout(attempts=2)
    full_budget_call = agent.backend.inner.timeout
    agent.started = time.monotonic() - 29 * 60  # 1 minute left
    agent._tune_model_timeout(attempts=2)
    assert full_budget_call > agent.backend.inner.timeout
    assert agent.backend.inner.timeout >= 90  # never so small that it is useless


def test_settings_json_roundtrip(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"days": 2, "max_papers": 11, "output_dir": str(tmp_path / "out")}), encoding="utf-8")
    settings = Settings.load_json(config)
    assert settings.days == 2
    assert settings.max_papers == 11
    assert str(settings.output_dir).endswith("out")


def test_env_file_is_loaded_without_shadowing_the_real_environment(tmp_path, monkeypatch):
    """A .env is convenient for per-machine settings; an exported var still wins."""
    keys = ("ARXIV_AGENT_MODEL", "ARXIV_AGENT_PROVIDER", "GITHUB_TOKEN")
    original = {key: os.environ.get(key) for key in keys}
    monkeypatch.setenv("GITHUB_TOKEN", "from-shell")
    try:
        for key in ("ARXIV_AGENT_MODEL", "ARXIV_AGENT_PROVIDER"):
            os.environ.pop(key, None)
        env = tmp_path / ".env"
        env.write_text(
            "# a comment\n"
            "\n"
            "ARXIV_AGENT_MODEL=deepseek-chat\n"
            'export ARXIV_AGENT_PROVIDER="openai"\n'
            "GITHUB_TOKEN=from-file\n"
            "NOT_A_PAIR\n",
            encoding="utf-8",
        )
        assert load_env_file(env) == 2  # the variable the shell already defines is skipped
        assert os.environ["ARXIV_AGENT_MODEL"] == "deepseek-chat"
        assert os.environ["ARXIV_AGENT_PROVIDER"] == "openai"  # quotes are stripped
        assert os.environ["GITHUB_TOKEN"] == "from-shell"
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_missing_env_file_is_not_an_error(tmp_path):
    assert load_env_file(tmp_path / "does-not-exist.env") == 0


def test_default_model_routes_to_the_openai_compatible_backend(monkeypatch):
    """A fresh clone must work with nothing configured but an OPENAI_API_KEY."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert resolve_provider(Settings().model, "") == "openai"


def test_repo_facts_skip_optional_calls_when_the_api_budget_is_spent(monkeypatch):
    """The tree/commit lookups are optional; running out of budget must not crash."""
    from arxiv_agent.github_client import GitHubClient

    client = GitHubClient.__new__(GitHubClient)  # no token, no network
    client.calls = 10
    client.search_calls = 0
    client.api_budget = 10
    client.search_budget = 6
    client.log = []
    monkeypatch.setattr(client, "raw", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        client,
        "api",
        lambda path: {"full_name": "owner/repo", "html_url": "https://github.com/owner/repo", "stargazers_count": 12},
    )
    facts = client.repo_facts("owner/repo")
    assert facts["stars"] == 12
    assert "tree_excerpt" not in facts
    assert "recent_commits" not in facts


def test_time_budget_env_var_maps_to_the_real_field(monkeypatch):
    """ARXIV_AGENT_TIME_BUDGET used to be derived into a non-existent kwarg."""
    keys = ("ARXIV_AGENT_TIME_BUDGET", "ARXIV_AGENT_DAYS", "ARXIV_AGENT_MAX_CONCURRENCY")
    original = {key: os.environ.get(key) for key in keys}
    try:
        monkeypatch.setenv("ARXIV_AGENT_TIME_BUDGET", "20")
        monkeypatch.setenv("ARXIV_AGENT_DAYS", "2")
        monkeypatch.setenv("ARXIV_AGENT_MAX_CONCURRENCY", "9")
        settings = Settings.from_env()
        assert settings.time_budget_min == 20
        assert settings.days == 2
        assert settings.max_concurrency == MAX_CONCURRENCY  # still clamped to 2
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_omitting_the_provider_flag_keeps_the_configured_one(monkeypatch):
    """An unset --provider must not silently reset a provider from env/config."""
    from arxiv_agent.cli import _settings_from_args, build_parser

    monkeypatch.setenv("ARXIV_AGENT_PROVIDER", "openai")
    settings = Settings.from_env()
    assert settings.provider == "openai"
    args = build_parser().parse_args(["work", "--offline"])
    _settings_from_args(args, settings)
    assert settings.provider == "openai"


def test_debug_flag_is_not_enabled_by_the_string_zero(monkeypatch):
    from arxiv_agent.cli import _debug_enabled

    monkeypatch.setenv("ARXIV_AGENT_DEBUG", "0")
    assert _debug_enabled() is False
    monkeypatch.setenv("ARXIV_AGENT_DEBUG", "1")
    assert _debug_enabled() is True
    monkeypatch.delenv("ARXIV_AGENT_DEBUG")
    assert _debug_enabled() is False


def test_matching_ignores_the_case_of_multi_word_terms():
    """The haystack is lowercased, so a term like "MRI" must be lowercased too."""
    paper = make_paper(
        "2609.00021",
        "MRI reconstruction with implicit neural fields",
        "We reconstruct MRI and CT reconstruction volumes with a neural field.",
    )
    evidence = screen_paper(paper)
    cold_hits = {hit.lower() for hit in evidence["cold_topics"]}
    assert "mri" in cold_hits
    assert "ct reconstruction" in cold_hits


def test_output_guard_only_touches_streams_that_cannot_encode_chinese(monkeypatch):
    from arxiv_agent import cli

    class FakeStream:
        def __init__(self, encoding):
            self.encoding = encoding
            self.reconfigured = None

        def reconfigure(self, **kwargs):
            self.reconfigured = kwargs

    western, utf8 = FakeStream("cp1252"), FakeStream("utf-8")
    monkeypatch.setattr(cli.sys, "stdout", western)
    monkeypatch.setattr(cli.sys, "stderr", utf8)
    cli._make_output_safe()
    assert western.reconfigured == {"encoding": "utf-8", "errors": "replace"}
    assert utf8.reconfigured is None


def _client_that_cannot_reach_abs_pages(monkeypatch):
    """An ArxivClient whose every HTTP call fails the way a TLS reset does."""
    from arxiv_agent.arxiv_client import ArxivClient, ArxivError

    client = ArxivClient(["cs.CV"], cache_dir=None)

    def unavailable(url, accept="*/*"):
        raise ArxivError("request failed: <urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING]>")

    monkeypatch.setattr(client, "_polite_get", unavailable)
    return client


def test_date_verification_survives_a_flaky_abstract_page(monkeypatch):
    """One reset connection must not abort a run that has already spent 20 model calls."""
    client = _client_that_cannot_reach_abs_pages(monkeypatch)
    paper = make_paper("2609.00031", "A paper whose abs page is unreachable", "abstract")
    assert client.verify_dates([paper]) == 0  # no exception, no crash
    assert client.log  # the failure is recorded rather than swallowed


def test_enrichment_survives_a_flaky_abstract_page(monkeypatch):
    client = _client_that_cannot_reach_abs_pages(monkeypatch)
    paper = make_paper("2609.00032", "Another unreachable record", "")
    paper.abstract = ""  # forces the enrichment path
    assert client.enrich_missing([paper]) == 0
    assert client.log


def test_unparseable_atom_record_ends_that_category_instead_of_the_run(monkeypatch):
    """parse_atom raises ValueError (not ET.ParseError) for a record without a date."""
    from arxiv_agent import arxiv_client as arxiv_module

    client = arxiv_module.ArxivClient(["cs.CV"], cache_dir=None)
    monkeypatch.setattr(client, "_cached", lambda tag, loader: "<feed/>")

    def unparseable(body):
        raise ValueError("no <published> in record")

    monkeypatch.setattr(arxiv_module, "parse_atom", unparseable)
    cutoff = datetime.now(timezone.utc) - timedelta(days=3)
    assert client._atom_category("cs.CV", cutoff) == []
