# Architecture

The mechanics of the pipeline, module by module and constant by constant. Everything below was read out of `src/arxiv_agent/` (v0.3.0, 17 modules, 3,473 lines) and `tests/test_agent.py`, not out of the README.
[DESIGN.md](DESIGN.md) covers why these choices were made, [CUSTOMIZE.md](CUSTOMIZE.md) the swap points if you replace the research map, [PUBLISHING.md](PUBLISHING.md) how to release a copy, [../README.md](../README.md)
the pitch and quickstart.

## 1. Module map

| Module | Lines | Responsibility | Owns |
|---|---:|---|---|
| `__init__.py` | 3 | package marker | `__version__ = "0.3.0"` |
| `__main__.py` | 3 | `python -m arxiv_agent` entry | delegates to `cli.main` |
| `cli.py` | 175 | argparse tree (`work`/`feedback`/`strategy` + `工作`/`反馈`/`策略`), `.env` loading, settings assembly | flag names, precedence, `--provider` choices, exit codes 0/1/2 |
| `config.py` | 136 | `Settings` dataclass, clamping, env/JSON loading | `MAX_CONCURRENCY = 2`, all defaults, `.env` parser, `clamp()` |
| `models.py` | 76 | `Paper` / `TrendingProject` dataclasses | the data contract every stage mutates |
| `profile.py` | 463 | research map as data; deterministic evidence extraction | 4 areas, 17 sub-areas, 41 seed works, 208 vocab terms, 88 institutions, 12 venues, 25 cold topics, `screen_paper`, `profile_brief` |
| `prompts.py` | 17 | brace-safe prompt templating | `render_template` |
| `arxiv_client.py` | 472 | three-channel harvest, cache, date verification | Atom/RSS/listing parsers, `keep_in_window`, `ArxivClient` |
| `fulltext.py` | 159 | HTML → ar5iv → PDF extraction, section prioritisation | `FullTextFetcher`, `_strip_tags`, `_cut_noise`, `_prioritise` |
| `github_client.py` | 282 | paper → repo binding; rising non-paper projects | `GitHubClient` budgets, `TRENDING_QUERIES`, spam filter |
| `triage.py` | 251 | screen → LLM jury → portfolio allocation | `screen`, `judge`, `composite_score`, `select_portfolio`, triage prompt |
| `analyze.py` | 234 | deep reading, daily observation, trend judging | `ANALYSIS_KEYS`, the analysis/daily/trend prompts, `analyze_paper`, `daily_note`, `judge_projects`, `_degraded` |
| `strategy.py` | 333 | versioned feedback memory (JSON + Markdown mirror) | `StrategyStore`, `DEFAULT_STRATEGY`, `PATCH_SCHEMA_NOTE`, clamp bounds, `deterministic_patch` |
| `feedback.py` | 215 | feedback conversation and patch synthesis | `QUESTIONS`, `SYNTHESIS_SYSTEM`, report-entry parsing, weight shorthand, `run_feedback` |
| `report.py` | 164 | the Chinese Markdown digest | `SECTIONS`, `render_report`, `_transparency`, `write_report` |
| `agent.py` | 282 | orchestration: phases, wall clock, degradation | `DailyArxivAgent.work`, `_CountingBackend`, `_tune_model_timeout`, `SEEN_TTL_DAYS = 7` |
| `llm.py` | 208 | one backend interface, three implementations, JSON recovery | `LLMBackend`, `GenOptions`, `extract_json`, `resolve_provider`, `build_backend`, `JSON_RETRY_SYSTEM` |

**Present but never called from the pipeline** — lint-clean, *not* live behaviour:

- `profile.quota_plan` / `profile.area_priority_rank` (allocation is inline in `select_portfolio`; `quota_plan` is called only by one test); `profile.area_of`; `profile.iter_seed_names`.
- `agent.now_utc`; `report.now_local`; `feedback.resolve_reference_date`; `feedback.paper_entries_from_papers` (`load_report_entries` parses the digest instead); `strategy.StrategyStore.record_verdict_by_title`;
  `github_client.attach_repo_to_paper`.
- `ArxivClient.retries` is stored and never read (the Atom retry count is hard-coded: 2 for page 0, 1 after); `ArxivClient.log` and `GitHubClient.log` are appended to all run and never read.
- `Settings.temperature` and `Settings.strategy_md` are dead config: that temperature never reaches a backend, and `StrategyStore.save` derives the `.md` path itself.
- `OpenAICompatBackend(prefer_chat=False)` — the Responses-API branch is reachable only by building the backend directly; `build_backend` never sets it. `stats["github_calls"]` is written by `work()` and never rendered by `report.py`.
- `ARXIV_AGENT_CACHE_DIR` and `cache_dir` in `--config` are read by `from_env`/`load_json`, then overwritten by `cli._settings_from_args` with `<state_dir>/cache`.

## 2. The `Paper` object lifecycle
One mutable dataclass flows through every stage; each stage writes its own slice and never invents evidence. Field order follows `models.py`.

| Field | Type / default | Written by | Stage |
|---|---|---|---|
| `arxiv_id` | `str`, required | `parse_atom` / `parse_rss` / `parse_listing` | harvest |
| `title` | `str`, required | same parsers | harvest |
| `abstract` | `str`, required | Atom and RSS parsers; `enrich_missing` for listing papers (`""` until then) | harvest, enrichment |
| `authors` | `list[str]`, required | Atom `author/name`, RSS `dc:creator`, listing anchors | harvest |
| `published` | `datetime`, required | parsers; **overwritten** by `enrich_missing` and `verify_dates` from the abs page | harvest, enrichment, verification |
| `updated` | `datetime \| None` | `parse_atom` only | harvest |
| `primary_category` | `str = ""` | `arxiv:primary_category`, first `<category>`, or `primary-subject` | harvest |
| `categories` | `list[str] = []` | parsers | harvest |
| `comment` | `str = ""` | `parse_atom` only (`arxiv:comment`) | harvest |
| `pdf_url` | `str = ""` | parsers (`related` link, else synthesised) | harvest |
| `abs_url` | `str = ""` | parsers (`alternate` link, else synthesised); re-set by `enrich_missing` | harvest, enrichment |
| `doi` | `str = ""` | `parse_atom` only | harvest |
| `date_uncertain` | `bool = False` | set `True` by `parse_rss` when no date is readable; cleared by `enrich_missing` / `verify_dates` | harvest, enrichment, verification |
| `keyword_hits` | `list[str] = []` | `triage.screen` ← `screen_paper` (area terms and `subarea:term`, de-duplicated) | screen |
| `lineage_hits` | `list[str] = []` | `triage.screen` ← `screen_paper` (canonical seed names, word-boundary matched) | screen |
| `area_candidates` | `list[str] = []` | `triage.screen` ← `screen_paper` (area keys by evidence score) | screen |
| `area` | `str = ""` | `triage.judge`: normalised from the model's `subarea`/`area`, else `area_candidates[0]`, else `"other"` | jury |
| `subarea` | `str = ""` | `triage.judge` (`area/subarea` key, or `""`) | jury |
| `scores` | `dict[str, float] = {}` | `triage.judge` → `{relevance, credibility, novelty, llm}` | jury |
| `triage_reason` | `str = ""` | `triage.judge` (model reason, ≤200 chars); **appended** by `select_portfolio` with the composite reasons | jury, allocation |
| `keep` | `bool = True` | `triage.judge`: `bool(row["keep"]) and relevance >= 3.5` | jury |
| `relevance` | `float = 0.0` | `triage.select_portfolio` — the **composite score**, not the jury relevance | allocation |
| `full_text` | `str \| None = None` | `FullTextFetcher.__call__` via `agent.work.process` | reading |
| `full_text_source` | `str = ""` | same: `arxiv-html`, `ar5iv`, `pdf`, `cache`, or `""` | reading |
| `full_text_chars` | `int = 0` | same: length of the trimmed text actually kept | reading |
| `repo` | `dict \| None = None` | `GitHubClient.attach_repo` (`{}` when nothing was found) | reading |
| `analysis` | `dict[str, str] = {}` | `analyze.analyze_paper`, or `analyze._degraded` | reading |

Two naming traps: `Paper.relevance` is the composite while `Paper.scores["relevance"]` is the raw 0–10 jury score (the report prints both), and `repo = {}` means "attempted, nothing found" while `repo = None` means "not
attempted" — `report.py` and `analyze._code_block` both require a `url` key.

```
harvest ──► screen ──────► enrich / verify ──► jury ──────► allocate ──► read ─────────► report
ids         keyword_hits   abstract            area          relevance    full_text       rendered
titles      lineage_hits   published           subarea       (composite)  repo            Markdown
abstracts   area_cands     date_uncertain      scores        triage_      analysis
published                                      keep          reason
```

`Paper.prompt_view(abstract_chars=1400)` is the only projection sent to the jury: id, title, first 6 authors, primary category, first 6 categories, comment (≤220 chars), abstract (triage passes 850), first 12 keyword
hits, first 8 lineage hits.

## 3. Stage-by-stage walkthrough of `work()`
`DailyArxivAgent.work()` (`agent.py:127`) is the whole pipeline. The wall clock is one monotonic origin, `self.started = time.monotonic()`, set in `__init__`.

```
 0%          25%            40%     45%                              100%
 |-----------|--------------|-------|---------------------------------|
 harvest     date           enrich  remaining-ratio gates: 0.35 / 0.30 / 0.20
 deadline    verification   done
             deadline              (per-paper second-level gates run after 45%)
```

| # | Stage | Implementation | Gate that can cut it short | Run stats |
|---:|---|---|---|---|
| 1 | Harvest | `arxiv.search(days, max_results=max_candidates, deadline=…)` | absolute deadline `started + budget*60*0.25`; categories skipped once passed | `harvested` |
| 2 | Already-seen filter | `agent._load_seen(state_dir/"seen.json")` | none | `harvested`, note |
| 3 | Deterministic screen | `triage.screen` → `profile.screen_paper` | none (pure CPU) | `screened` |
| 4 | Enrich + re-anchor | `arxiv.enrich_missing(deadline_monotonic=…)`, then `keep_in_window` | absolute deadline `started + budget*60*0.45` | note |
| 5 | LLM jury | `triage.judge`, batches of `triage_batch` (12), first thread pool | `budget_exhausted(0.30)` after each consumed batch | `judged` |
| 6 | Allocation | `triage.select_portfolio` | none | `slots`, `dropped_by_area` |
| 7 | Date verification + backfill | `agent._confirm_dates` → `arxiv.verify_dates` | absolute deadline `started + budget*60*0.40` | note |
| 8 | Budget downgrades | inline in `work`, before the reading pool | `budget_exhausted(0.35)`, `budget_exhausted(0.20)` | notes |
| 9 | Per-paper reading | nested `process(paper)`, second thread pool | `remaining_seconds()` vs 240 / 200 / 90 | fills `full_text*`, `repo`, `analysis` |
| 10 | Daily observation | `analyze.daily_note` | needs ≥2 papers whose `confidence` does not start with `低`, and `remaining_seconds() > 180` | `daily` dict |
| 11 | Seen ledger | `agent._save_seen(...)` | none | — |
| 12 | Trending projects | `github.trending(TRENDING_QUERIES, window_days=7)` + `judge_projects(limit=5)` | `not skip_trending and remaining_seconds() > 150` | `projects` |
| 13 | Render | `report.write_report(output_dir, date.today(), …)` | none | `reports/YY-MM-DD.md` |

What the table cannot carry:

- **Harvest** tries Atom first per category (`sortBy=submittedDate&sortOrder=descending`, `start=0..300` step 100, so **400 entries per category per run** — the documented `--days 7` blind spot). A `429` abandons that
  category rather than retrying; RSS is tried next, and if an RSS category's date spread is thinner than `max(1, days - 1)` the monthly listing page fills it. `transport` ends as `atom`, `rss`, `listing` or `mixed`. An
  empty harvest raises `RuntimeError` (CLI exit 1, no file).
- **Seen filter** drops ids recorded within `SEEN_TTL_DAYS = 7`; if everything was seen the unfiltered list is used (`harvested = fresh or harvested`), so `stats["harvested"]` — the report's "候选 N 篇" — is the post-filter count.
- **Screen** sorts by `prior` descending, keeps `prior > 0`, force-appends every lineage-hit paper that did not survive, appends the 10 newest by `published`, then truncates to `triage_pool` (90). If that is empty it
  falls back to `harvested[:triage_pool]`: the screen decides what deserves expensive attention, never whether anything is worth reading.
- **Jury** cuts the pool into batches of 12 (90 candidates → 8 batches, 7×12 + 6). `executor.map` submits **all** batches up front, so the `budget_exhausted(0.30)` break stops *consuming* results and appends
  "模型评审阶段耗时超出预期，已在处理完当前批次后收束。" — submitted batches still run to completion when the `with` block closes the pool, and `judged` counts consumed batches only.
- **Allocation** overwrites `paper.relevance` with the composite (§4.4). If the jury rejected everything, the unfiltered pool is used. An empty selection raises `RuntimeError`.
- **Date verification** re-dates each finalist from its abs page and backfills drops from the ranked pool by composite score, one fetch per candidate, until the digest regains its size. Its `0.40` deadline is *earlier*
  than the `0.45` enrichment deadline: independent absolute stamps, not cumulative ones. **Per-paper gates** are re-derived per paper because two workers share one clock:

  ```python
  remaining = self.remaining_seconds()
  if remaining > 240:                   # else: no full text at all
      text, source, size = self.fulltext(paper, max_chars=fulltext_chars)
  if not skip_code and remaining > 200: # else: no repository
      self.github.attach_repo(paper)
  if self.remaining_seconds() < 90:     # else: no model call
      paper.analysis = _degraded(paper, "时间预算耗尽，未进行深度解析。")
  else:
      self._tune_model_timeout(attempts=2)
      paper.analysis = analyze_paper(paper, self.backend, self.strategy, body_chars=fulltext_chars)
  ```

- **Daily observation** sees a compact digest per paper (id, title, area, sub-area, one-liner, ≤400 chars of innovations, ≤300 of lineage) plus the strategy block. **Seen ledger** is written *before* the report renders —
  a documented limitation, since a late failure can mark papers as seen without delivering them.
- **Trending** runs one GitHub search per area (4 areas × 3 terms, OR-ed, `created:>{since}`, `per_page=10`), keeps `age <= window_days + 1`, `stars >= 3` and no spam hint, scores by `stars / max(age_days, 1.0)`, keeps
  the top 20, and has the model pick up to 5 with a reason.
- **Stats** are `{harvested, screened, judged, slots, dropped_by_area, minutes, llm_calls, llm_failures, provider, transport, notes, github_calls}`. The GitHub-budget note is appended after that literal, but
  `stats["notes"]` aliases the same list, so it does reach the report; `github_calls` never does.

## 4. Scoring and allocation arithmetic
### 4.1 Deterministic screen (`profile.screen_paper`, `triage.screen`)
The text under test is `f"{title} {abstract} {comment}".lower()`.

| Signal | Match rule | Weight |
|---|---|---:|
| Area vocabulary | plain substring | `+1.0` each |
| Sub-area vocabulary | plain substring, recorded as `"{sub.key}:{term}"` | `+1.0` each |
| Lineage anchor | regex `(?<![a-zA-Z0-9])alias(?![a-zA-Z0-9])` over the seed name and its aliases | `+2.0` each; the canonical seed name enters `lineage_hits` |
| Cold topic | plain substring against `COLD_TOPICS` | `-2.0` each, in the prior only — never in `screen_score` |

`screen_score = round(sum(area_scores.values()), 2)`, where `area_scores[area]` accumulates the hits attributed to that area. `triage.screen` then computes

```
prior = screen_score + 3.0 * len(lineage_hits) + 1.0 * len(area_candidates) - 2.0 * len(cold_topics)
```

and keeps `prior > 0`. Institutions and venues reach `screen_paper`'s return dict but **never** any score — only the prompt shows them, as explicitly weak context.

### 4.2 Jury rubric (`triage.TRIAGE_SYSTEM`, `triage.judge`)
Per paper the model returns `{id, area, subarea, relevance, credibility, novelty, keep, reason}` on a 0–10 scale with a ≤40-character Chinese reason. `_clamp_score` bounds values to `[0.0, 10.0]`; absent fields default
to relevance `4.0`, credibility `5.0`, novelty `5.0`. The verdict is

```
keep   = bool(row.get("keep", True)) and relevance >= 3.5
scores = {"relevance": r, "credibility": c, "novelty": n, "llm": 1.0}
```

Call shape: `GenOptions(max_output_tokens=200 * len(batch) + 800, temperature=0.1)` over `prompt_view(abstract_chars=850)`. Any exception in `triage_batch_with_llm` returns `{}` for the whole batch, and `judge` then
keeps every paper in it with `scores = {4.0, 4.0, 4.0, llm: 0.0}` and the reason "模型未返回该篇评分，按启发式保留（请人工确认）。" — a parsing hiccup cannot silently delete a paper.

### 4.3 Composite score (`triage.composite_score`)
```
base = 0.58 * relevance + 0.22 * credibility + 0.20 * novelty
if not scores.get("llm"):            base -= 1.5                          # -1.5 未经模型评审
lineage = len(paper.lineage_hits)
if lineage:                          base += min(2.5, 1.2 * lineage)
if len(paper.area_candidates) >= 2:  base += 0.4                          # cross-area
delta, why = strategy.paper_adjustment(text_lower, area, subarea); base += delta
multiplier = strategy.area_multiplier(area) if area in AREA_BY_KEY else 1.0
if paper.subarea:                    multiplier *= strategy.subarea_multiplier(paper.subarea)
base *= multiplier
return round(base, 3), reasons
```

Every coefficient: `0.58 / 0.22 / 0.20`, `-1.5`, `1.2` per lineage hit capped at `2.5`, `+0.4` for ≥2 area candidates, and a **multiplicative** area × sub-area weight applied last — the strategy multipliers scale the
whole score including bonuses, while pattern deltas are additive and applied before them. `paper_adjustment` is deterministic and model-free: `+weight` per matched positive pattern, `-weight` per negative pattern
(substring on the lowercased title + abstract + comment), `+1.5` per matched watch-list lab/author/project; area and sub-area weights appear there only as reasons. Numeric check: `scores = {8, 8, 8, llm: 1}` with no
strategy gives exactly `8.0`; with `llm: 0` it gives `2.5`.

### 4.4 Quota allocation (`triage.select_portfolio`)
```
ranked  = pool sorted by (-composite, published)     # ties: earlier submission first
target  = len(ranked)                                if len(ranked) <= min_papers
          min(max_papers, len(ranked), max(min_papers, target_papers))   otherwise
weights = {area: max(0.05, area.quota_weight * strategy.area_multiplier(area))}
total   = sum(weights.values()) or 1.0
slots   = {area: int(round(target * weight / total))}
```

then three repair passes, in order:

1. **Hit `target`.** While `sum(slots) < target`, add 1 to the highest-weight area that still has unallocated candidates; while `sum(slots) > target`, subtract 1 from the lowest-weight area with a non-zero slot. Both
   loops break when no area qualifies.
2. **Minimum presence.** For each area in `AREAS` order that got no paper: take its best remaining candidate with raw `scores["relevance"] >= 5.0`, provided `len(chosen) < max_papers`, and **skip it if
   `strategy.paper_adjustment(...)` returns `delta <= -1.5`** — the rejection veto. A diversity rule never overrides an explicit user rejection.
3. **Leftover fill.** Walk `ranked` in composite order until `min(target, max_papers)`; once `len(chosen) >= min_papers`, anything with raw relevance `< 5.0` is skipped — the **quality floor**. Below `min_papers` the
   floor does not apply, and that is the only path by which a sub-5.0 paper can enter.

The digest is ordered by `(index of area in AREAS, -composite)` and truncated to `max_papers`. `stats` returns `pool`, `kept_by_judge`, `target`, `slots`, and `dropped_by_area`. Worked example with defaults (quota
weights 0.45/0.25/0.20/0.10, no feedback, `--target 12`): slots come out 5/3/2/1 = 11, so pass 1 adds one to `3d_generation` → 6/3/2/1. `min_papers` is an aim, not a guarantee: `_transparency` prints the shortfall
sentence whenever fewer papers were selected, and nothing is padded to reach it.

## 5. State on disk
Personal state lives under `state_dir` (default `.arxiv-agent`); reports under `output_dir` (default `reports`). `.gitignore` excludes both.

| Path | Written by | Read by | Lifetime |
|---|---|---|---|
| `<state>/strategy.json` | `StrategyStore.save()` ← `apply_patch` (only the `feedback` command) | `StrategyStore.__init__` on every `work` | permanent; `version` increments per patch; corrupt JSON is ignored and defaults are used |
| `<state>/strategy.md` | `StrategyStore.save()` → `render_markdown()` | humans; `arxiv-agent strategy` prints it | overwritten per patch; editing it changes nothing |
| `<state>/feedback-log.jsonl` | `feedback.run_feedback` (append) | nothing in the code base | append-only, one object per run (`date`, `mode`, `feedback` ≤800 chars, `applied`) |
| `<state>/seen.json` | `agent._save_seen` | `agent._load_seen` | rolling 7-day horizon; older ids are filtered on read but only physically dropped on the next write |
| `<state>/cache/<sha1(tag)[:16]>.xml` | `ArxivClient._cached` | `ArxivClient._cached` | **no TTL**; only `--no-cache` clears it (`shutil.rmtree(cache_dir)` before the run) |
| `<state>/cache/fulltext/<arxiv_id>.txt` | `FullTextFetcher.__call__` | `FullTextFetcher.__call__` | **no TTL**; stores the already-trimmed text, so the character budget of whichever run populated it is baked in |
| `<output>/YY-MM-DD.md` | `report.write_report` | humans; `feedback.load_report_entries` reads the newest `*.md` to resolve entry numbers | overwritten by a second run that day — one file per day, no history |

Cache keys are `sha1(tag.encode("utf-8")).hexdigest()[:16]`; the full-text cache uses the arXiv id verbatim (`/` → `_`) plus `.txt`, and is written only when extraction succeeded with more than 1,500 characters. A cache
hit is reported as source `cache`.

```
{YYYYMMDD}:atom:{category}:{offset}     offset in 0, 100, 200, 300
{YYYYMMDD}:rss:{category}
listing:{category}:{YYYY-MM}:probe
listing:{category}:{YYYY-MM}:{skip}:{want}
abs:{arxiv_id}                          shared by enrich_missing and verify_dates
```

**Known limitation: there is no TTL and no eviction.** Atom pages are keyed by day and go stale naturally, but `abs:{id}` and `fulltext/{id}.txt` are cached forever — a paper's full text is never re-fetched, a wrong
repository guess is re-analysed from a stale README, and disk use grows without bound. There is also no locking, so two runs sharing a state directory can race on the same cache file. Both are in the README's roadmap.

## 6. Concurrency and time budget
Two `ThreadPoolExecutor`s are created sequentially inside `work()`, both with `max_workers = settings.max_concurrency`:

| Pool | Work unit | Blocking call inside |
|---|---|---|
| Triage pool | one batch of up to `triage_batch` (12) papers | one `complete_json` jury call |
| Reading pool | one `Paper` | full-text HTTP/PDF, GitHub API, one `complete_json` analysis call |

**The hard cap of 2** is the constant `config.MAX_CONCURRENCY = 2` (commented as never to be raised silently), and it is enforced at three layers on top of it:

1. `Settings.clamp()`: `max_concurrency = max(1, min(MAX_CONCURRENCY, int(...)))`, reached from `from_env`, `load_json` and `cli._settings_from_args`.
2. `cli.build_parser()`: `--max-concurrency` uses `choices=(1, MAX_CONCURRENCY)`, so argparse rejects anything else before the pipeline starts.
3. `DailyArxivAgent.__init__` re-clamps the value in place, so an agent built directly in a script is capped too.

**Time budget.** One monotonic origin, four derived quantities:

```
elapsed_minutes()   = (time.monotonic() - started) / 60
remaining_seconds() = max(0, time_budget_min * 60 - (time.monotonic() - started))
remaining_ratio()   = max(0, 1 - elapsed_minutes() / max(time_budget_min, 1))
budget_exhausted(t) = remaining_ratio() <= t
```

Phases use **absolute** deadlines off `started` — harvest `0.25`, date verification `0.40`, enrichment `0.45` — while everything after the reading pool uses **remaining-second** gates and the whole-run downgrades use
**remaining-ratio** gates (`0.35`, `0.30`, `0.20`). `time_budget_min` is clamped to 5–60 in `Settings.clamp()`.

**Live model-timeout tuning.** `_tune_model_timeout(attempts)` re-derives the per-call timeout from the remaining wall clock before every analysis call and once before the daily note:

```
per_attempt   = (remaining_seconds() - 30) / max(1, attempts)
inner.timeout = int(max(90, min(inner.default_timeout, per_attempt)))   # default_timeout = 600
```

It applies **only when `self.backend.inner` is a `CodeBuddyBackend`**: the `isinstance` guard returns immediately for every other backend, so the OpenAI-compatible route keeps its constructor timeout (180 s) and its
retry backoff, and the offline backend is untouched. The 30 s reserve is room for the report itself; the 90 s floor keeps a shrunk timeout from being useless.

**Rate limiting.** `ArxivClient` spaces requests by `request_delay` (3.0 s) through a `_polite_get` tracking one `last_request` timestamp, and it is only driven from the serial phases (harvest, enrichment, verification),
so that timestamp is not contended. `GitHubClient` *is* driven from the 2-worker reading pool and its `calls`, `search_calls` and `_last_call` counters are unsynchronised — the documented consequence is that its budget
and 1 req/s spacing can be slightly exceeded near exhaustion. README fetches from `raw.githubusercontent.com` bypass the API budget entirely.

## 7. Degradation ladder

| Condition (exact) | What is dropped | What the report says |
|---|---|---|
| `budget_exhausted(0.30)` after a jury batch | remaining batches not consumed (submitted ones still finish) | 模型评审阶段耗时超出预期，已在处理完当前批次后收束。 |
| harvest past `started + 0.25 × budget` | remaining Atom pages/categories and their RSS+listing fallback | nothing — `ArxivClient.log` only, which is never rendered |
| enrichment past `started + 0.45 × budget` | abs-page completion for listing papers and dateless RSS items | nothing directly; those papers keep `abstract == ""` / their id-guessed date |
| verification past `started + 0.40 × budget` | re-dating of remaining finalists | nothing directly; they keep their feed date, so the window check runs on unverified data |
| `budget_exhausted(0.35)` | full-text budget `26,000 → int(26,000 × 0.6) = 15,600` chars | 时间预算紧张：正文截取长度已下调。 |
| `budget_exhausted(0.20)` | GitHub repo attachment for every remaining paper | 时间预算紧张：跳过代码抓取，报告中不写“代码与实践”。 and `### 代码与实践` omitted per paper |
| `remaining_seconds() <= 240` for one paper | its full-text fetch | 正文 未获取到全文; the analysis prompt's evidence line says the note rests on title/abstract/metadata |
| `remaining_seconds() <= 200` for one paper | its repo attachment | 代码 未检索到可靠仓库; `### 代码与实践` omitted |
| `remaining_seconds() < 90` for one paper | the analysis model call | `_degraded`: 证据等级 低 — 本轮未获得模型分析结果。, 局限与风险 时间预算耗尽，未进行深度解析。 |
| first analysis attempt fails, or returns a non-dict / >6 of 12 fields empty | nothing — one retry with the body halved | on success, `limitations_risks` gains （本次为缩短正文后的重试结果，覆盖面可能偏窄。） |
| both analysis attempts fail | the reading note | 证据等级 低, 局限与风险 深度解析失败（`<ExceptionType>`），已重试仍未成功，以下仅为元数据概要。 |
| unparseable JSON from `complete_json` | one repair call at temperature 0.0 | nothing; the repair call is not counted in `llm_calls`, so that figure is a lower bound |
| fewer than 2 papers with a non-`低` confidence, or `remaining_seconds() <= 180` | the cross-paper observation | the whole `## 今日导读` section is absent |
| `--skip-trending`, or `remaining_seconds() <= 150` | trending projects | the GitHub section is absent; if only the model call fails, `judge_projects` falls back to un-judged projects with 推荐理由 （模型未参与筛选） |
| a triage batch call raises | that batch's verdicts | every paper keeps `llm: 0.0` → composite `-1.5`, reason 模型未返回该篇评分，按启发式保留（请人工确认）。 |
| GitHub core budget (30, or 45 with `GITHUB_TOKEN`) or search budget (6, or 25) exhausted | repo tree, then recent commits, then repo discovery / trending | GitHub API 调用预算（N 次）用尽… appended when `github.calls >= github.api_budget` |
| `pypdf` not installed | the PDF fallback | the path silently reduces to arXiv HTML → ar5iv; on failure, 正文 未获取到全文 |
| empty harvest, empty selection, or empty post-verification selection | the whole run | no file; `RuntimeError`, CLI exit 1 |
| backend cannot be constructed (missing key or CLI) | the whole run | no file; `LLMBackendError`, CLI exit 2 |

The per-paper analysis retry is `analyze_paper`'s `attempts` list: `[(body_chars, 0.25)]`, extended with `(max(4000, body_chars // 2), 0.2)` when `body_chars > 6000`. The JSON repair is `LLMBackend.complete_json`'s
single extra call with `JSON_RETRY_SYSTEM` at `temperature=0.0`; if the repair also fails to parse, the `ValueError` propagates and becomes one of the failures above.

## 8. Model backends
`LLMBackend` (`llm.py:65`) is a two-method interface: `complete(system, user, options)` returns text, `complete_json(system, user, options)` returns a parsed object. `complete_json` is implemented **once in the base
class**: it forces `json_mode = True` on the caller's `GenOptions` (a mutation), calls `complete`, and on a `ValueError` from `extract_json` makes exactly one repair call with `JSON_RETRY_SYSTEM`, the broken text, the
same `max_output_tokens` and `temperature=0.0`. `extract_json` strips a ```` ```json ```` fence, tries `json.loads`, then the span from the first `{` to the last `}` and from the first `[` to the last `]`, and raises
otherwise. `GenOptions` defaults: `max_output_tokens=2400`, `temperature=0.2`, `json_mode=False`.

| Backend | `name` | Transport, timeout, retries, JSON behaviour |
|---|---|---|
| `OpenAICompatBackend` | `openai` | `openai` SDK; Chat Completions by default, Responses API when `prefer_chat=False`; timeout 180 s; `retries=2` → 3 attempts with `sleep(2.0 × (attempt+1))` (2 s, 4 s), then `LLMBackendError`. `json_mode` maps to `response_format={"type": "json_object"}` on the Chat path; the Responses path has no JSON mode and relies on the base repair |
| `CodeBuddyBackend` | `codebuddy` | `subprocess.run([exe, "-p", "--model", model, *extra_args])` with the prompt on stdin; `timeout=600`, mirrored as `default_timeout` for live tuning; **no retry** — a timeout or non-zero exit raises immediately. `json_mode` appends a Chinese "return one legal JSON object, no fences" instruction; ANSI escapes are stripped from stdout |
| `OfflineBackend` | `offline` | no transport; overrides `complete_json` to return `{"results": []}` when `"triage" in system` and `{}` otherwise; `complete` returns `""`. Never raises, never calls a model |

`CodeBuddyBackend` finds its executable with `shutil.which("codebuddy") or shutil.which("codebuddy.cmd")` and raises `LLMBackendError` if neither exists. `OpenAICompatBackend` requires `OPENAI_API_KEY` or
`DEEPSEEK_API_KEY` at construction and takes `base_url` from its argument or `OPENAI_BASE_URL`; the `openai` package is imported lazily, which is what keeps the runtime dependency-free.

**Provider resolution** (`resolve_provider(model, explicit)`), in evaluation order:

1. `explicit` set and not `"auto"` → that value.
2. model lowercased starts with `"hy"` or contains `"codebuddy"` → `codebuddy`.
3. contains `"deepseek"` **or** `DEEPSEEK_API_KEY` is set → `openai`.
4. starts with `gpt`, `o1`, `o3`, `o4`, `gpt-oss` or `oss` → `openai`.
5. `OPENAI_BASE_URL` is set → `openai`.
6. otherwise → `codebuddy`.

Two consequences: rule 5 makes *any* unrecognised model name silently take the OpenAI-compatible route when `OPENAI_BASE_URL` is exported, and rule 6 makes the fallback for an unknown name with no gateway the CLI backend
— which fails at construction if `codebuddy` is not installed. `build_backend(model, provider, offline)` short-circuits to `OfflineBackend` when `offline=True` and raises `LLMBackendError` for any other kind (unreachable
through `resolve_provider`). `_CountingBackend` in `agent.py` wraps whichever backend is built: `complete` and `complete_json` increment `calls`, and only `complete_json`'s exception path increments `failures` — those
become `llm_calls` and `llm_failures` in the report header.

## 9. Testing strategy
`tests/test_agent.py` is 553 lines and **38 test functions**, all offline: no network, no credentials, no model SDK. Fixtures are inline XML/HTML/JSON strings, and `StubBackend` returns scripted jury verdicts keyed by arXiv id.

| Group | n | What is pinned |
|---|---:|---|
| profile / screening | 5 | a lineage hit beats keyword counting; an off-topic paper scores 0 with no candidates; `profile_brief` names every area and sub-area key; `quota_plan` fills every slot; multi-word cold topics such as `MRI` match despite the lowercased haystack |
| parsing | 7 | Atom comment/category/authors; RSS `pubDate` and the `Abstract:` split; a dateless item flagged `date_uncertain` and dated from the id; earlier-month ids never surviving a short window; listing pages yielding ids and titles with `abstract == ""`; both `_parse_submitted` formats |
| full text | 2 | `_strip_tags` keeps headings and drops `<script>`; `_prioritise` stays in budget and keeps the method section |
| LLM plumbing | 1 | `extract_json` fences, prose-wrapped JSON, raising on refusal |
| triage / allocation | 5 | `screen` keeps lineage papers; `judge` applies verdicts and area keys; an omitted paper is kept, not dropped; quotas favour the higher-priority area; a feedback patch changes the selection without touching code |
| strategy / feedback | 5 | versioned patches mirrored to `strategy.md` and `context_block`; the `+`/`-` fallback; a corrupt `strategy.json` does not break the run; entry numbers resolve to titles; composed feedback keeps every answer |
| report / degradation | 2 | the digest is Chinese, carries the section headings and transparency appendix, is named `YY-MM-DD.md`; `_degraded` never invents a repository and always reports confidence `低` |
| config, CLI, clients | 11 | concurrency clamped to 2; the model timeout shrinks with the budget but never below 90 s; JSON config round-trips; `.env` never shadows a real env var; a missing `.env` is not an error; the default model resolves to `openai`; `repo_facts` skips optional calls at budget; `ARXIV_AGENT_TIME_BUDGET` maps to `time_budget_min`; an omitted `--provider` does not reset the configured one; `ARXIV_AGENT_DEBUG=0` is false; the stdout encoding guard only touches streams that cannot encode Chinese |

**What it deliberately does not cover.** No HTTP anywhere: `ArxivClient.search`, `_atom_category`, `_rss_category`, `_listing_category`, `verify_dates`, `enrich_missing` and the cache layer are untested (only the pure
parsers, plus `keep_in_window`/`id_month_start` directly); `GitHubClient.find_repo_candidate`, `search_repo` and `trending` are untested, and `repo_facts` runs with `api`/`raw` monkeypatched. No live
`OpenAICompatBackend`/`CodeBuddyBackend` call is made — only `resolve_provider` and the CLI backend's timeout arithmetic. There is no `DailyArxivAgent.work()` end-to-end run: the single agent test builds the object with
`__new__` to exercise `_tune_model_timeout`, so phase ordering, every budget gate in §3, `_confirm_dates`, `_load_seen`/`_save_seen` and both thread pools have no coverage. `analyze_paper`'s happy path, `daily_note`,
`judge_projects`, `FullTextFetcher.__call__`, `feedback.run_feedback`, `apply_patch`'s clamp bounds and `_transparency`'s slot/lineage branches are untested too; nothing compares the Markdown to a golden file, and
nothing asserts that a degradation reaches the appendix.

**CI** (`.github/workflows/ci.yml`): one `test` job on `ubuntu-latest`, matrix `["3.10", "3.11", "3.12"]`, `fail-fast: false`, pip cache on. Steps: install `-e ".[dev,fulltext]"`, `python -m ruff check src tests`,
`python -m pytest`, then a CLI wiring smoke test (`arxiv-agent --help`, `arxiv-agent strategy --state-dir "$RUNNER_TEMP/arxiv-state"`, `python -m arxiv_agent --help`). Ruff runs `line-length = 200`, `target-version =
"py310"`, `select = ["E9", "F", "B", "UP"]` — correctness, dead code, bugbears and 3.10 compatibility, deliberately not a formatting gate. `pyproject.toml` sets `pythonpath = ["src"]` and `testpaths = ["tests"]`, so the
suite runs from a checkout without an install.

## 10. Extension points
**A new selection signal**, cheapest first:

1. *Vocabulary or lineage* — add a term to `SubArea.vocab`, or a `SeedWork(name, route, aliases)` to `SubArea.seeds` in `profile.py`. Vocabulary is `+1.0`, a word-boundary seed alias `+2.0` plus `+3.0` in the prior and
   `+1.2` per hit in the composite (capped at `+2.5`). A new `SeedWork` also changes `LINEAGE_INDEX`, the force-keep rule and what the prompts name as the route. Screen, jury prompt, composite, allocation and report all
   pick it up with no other edit.
2. *A negative signal* — add to `COLD_TOPICS` (`-2.0` in the prior only), or emit a runtime negative pattern through feedback.
3. *A new term in the composite* — edit `composite_score` in `triage.py`, keeping it deterministic and reason-returning (append to `reasons`) so the report can show its work; the coefficients are asserted nowhere today.
   `area_candidates` and `lineage_hits` feed both the prior and the composite, so a signal added in `screen_paper` needs a matching decision in `triage.py` if it should affect ranking rather than only recall.

**A new model backend.** Subclass `LLMBackend`, set `name`, implement `complete` (override `complete_json` only if the provider needs something other than the base repair flow), then wire it into `resolve_provider` and
`build_backend`. Three things to update alongside: the `--provider` `choices` in `cli.build_parser()` (`auto|openai|codebuddy|offline`), the `isinstance(inner, CodeBuddyBackend)` check in `agent._tune_model_timeout` if
the backend should get live timeout shrinking, and the failure accounting — `_CountingBackend` increments `failures` only on `complete_json` exceptions, so a backend that fails inside `complete` under-reports.

**A new report section.** Per-paper sections come from three places that must stay in sync: `ANALYSIS_KEYS` and the field list in `ANALYSIS_SYSTEM` (`analyze.py`), and the `SECTIONS` tuple of `(analysis_key, Chinese
heading)` in `report.py`. `analyze_paper` fills any missing key with "文中未提供。" and rejects a result when `len(missing) > len(ANALYSIS_KEYS) // 2` — with 12 keys, 7 empty fields trigger the halved-body retry — so
growing `ANALYSIS_KEYS` also loosens that gate unless the divisor is revisited. A document-level section (like the trending table or the transparency appendix) is added in `render_report` and fed from the `stats` dict
assembled at the end of `work()`.

**A new arXiv ingestion channel.** Add a `_<name>_category(category, …)` method to `ArxivClient` returning `list[Paper]`, call it from the per-category loop in `search()` when the earlier transports return nothing, and
set `self.transport`. Two contracts matter: the records must carry enough for `enrich_missing` to complete them (it triggers on `not paper.abstract or paper.date_uncertain`), and anything with a synthesised date must set
`date_uncertain=True` so `verify_dates` re-dates it before it can enter a digest. Cache through `self._cached(tag, fetch)` with a new tag shape — the tag is hashed, so any string works, but a tag with no date component
is never invalidated.
