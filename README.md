# Daily Arxiv in My Domain

**A daily arXiv scout that knows your research map.**

Every morning it reads the last few days of arXiv, filters a few hundred submissions down to
the 10–15 papers that actually sit on *your* research lines, reads their full text and their
code, and writes a Chinese Markdown digest you can act on. Then it listens: your feedback is
compiled into a **versioned selection strategy** that changes what it picks tomorrow.

Not a generic recommender. Not a peer reviewer. The goal is narrower and harder:
**turn a few hundred noisy submissions into a short, trustworthy, explainable reading queue —
and get better at it every week.**

[![CI](https://github.com/OWNER/Daily_Arxiv_in_My_Domain/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/Daily_Arxiv_in_My_Domain/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-38%20offline-brightgreen.svg)](tests/test_agent.py)
[![Dependencies](https://img.shields.io/badge/runtime%20deps-none%20(stdlib)-lightgrey.svg)](pyproject.toml)

> 中文文档：[README.zh-CN.md](README.zh-CN.md) ·
> Sample output: [examples/2026-09-15-daily-digest.md](examples/2026-09-15-daily-digest.md) (a real, unedited run)

---

## Why this exists

arXiv is where a research field is decided, and it is a terrible interface. On a typical day
`cs.CV`, `cs.GR`, `cs.RO`, `cs.MM`, `cs.AI` and `cs.LG` together publish hundreds of new
papers. A keyword alert cannot tell *"a TRELLIS successor with a new sparse-latent interface"*
from *"diffusion applied to credit scoring"* — both contain the word "diffusion". Reading
everything is impossible; reading nothing is expensive in a different currency.

The bet behind this project: **a research field is not a set of keywords, it is a graph of
lineages.** If you write down the lineages you actually work on — the base representations, the
prior work that defines each route, the sub-problems you consider unsolved — then selection
becomes a tractable, auditable problem. That map is this project's core asset, and it lives in
[`src/arxiv_agent/profile.py`](src/arxiv_agent/profile.py) as data, not as prompt prose.

## What it does

| Command | What happens |
|---|---|
| `arxiv-agent work` (alias `工作`) | Harvest the last 1–7 days of arXiv → deterministic screen → LLM jury → portfolio allocation → full text + code → `reports/YY-MM-DD.md` |
| `arxiv-agent feedback` (alias `反馈`) | Asks 5 targeted questions (or takes one-shot text/`--file`), compiles them into a strategy patch |
| `arxiv-agent strategy` (alias `策略`) | Prints the currently active strategy, its weights and its version history |

`work` prints **nothing** while it runs except the final report path. One command in, one
Markdown file out.

## Quickstart

Requires Python 3.10+ (developed on 3.12). The runtime has **no third-party dependencies** —
everything is standard library until you pick a model backend.

```bash
git clone https://github.com/OWNER/Daily_Arxiv_in_My_Domain.git
cd Daily_Arxiv_in_My_Domain
python -m venv .venv && source .venv/bin/activate    # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[openai,fulltext]"                  # openai SDK + pypdf (PDF fallback)
cp .env.example .env                                 # Windows: copy .env.example .env
```

`.env` is read from the working directory automatically (real environment variables win over it).

```bash
# 1) any OpenAI-compatible endpoint — the default route
OPENAI_API_KEY=sk-...
arxiv-agent work

# 2) DeepSeek and friends: same client, different base URL
OPENAI_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=sk-...
arxiv-agent work --model deepseek-chat

# 3) a locally authenticated CLI gateway (how this project is run day to day)
arxiv-agent work --model hy4-preview --provider codebuddy

# pipeline self-check: no model calls, no credentials, no cost
arxiv-agent work --offline --days 3 --target 3
```

`--offline` exercises every stage except the model: the digest it writes is scored by the
deterministic heuristics alone and every paper is labelled as unjudged, so use it to validate a
setup, not to read. If a run leaves nothing inside the window after date verification, it exits
with an honest error instead of writing an empty digest — widen `--days` and retry.

Optional but recommended: `GITHUB_TOKEN` raises the GitHub API budget (core calls 30 → 45,
search 6 → 25 per run) and is used to attach a paper's repository and to look for rising
non-paper projects.

## What the output looks like

One file per day, `reports/26-09-15.md`, ~1,600 lines for 12 papers. Structure:

| Section | Contents |
|---|---|
| Header | Search window, candidates → screened → selected, model, provider, concurrency, minutes, model calls, arXiv transport used |
| `## 今日导读` (daily read) | Cross-paper trends of the day — routes clustering, lineages being extended, signals spanning areas, conspicuous gaps — plus 3–5 watchwords for tomorrow |
| `## 速览` (at a glance) | Table: title, area, sub-area, composite score, the three raw scores, one-line reason |
| `## 1..N` | Per paper: one-liner · background & motivation · architecture (input → representation → flow → losses → inference) · **relation to prior work, naming the specific works it extends, replaces or contrasts** · insight · innovations · evaluation (datasets/metrics/baselines/numbers/ablations) · code & practice (read from the repo, not guessed) · limitations & risks · why read it · how to read it (time-boxed plan) · **evidence level** |
| `## GitHub 近一周上升项目` | Rising non-paper repositories, with an explicit disclaimer that the trend number is a proxy |
| `## 选取过程透明度` | Funnel counts, area quotas, notable rejections, lineage hits, every degradation that happened, and a plain-language honesty statement |
| `## 给 Agent 反馈` | The exact command to send feedback back |

A real excerpt (translated in brackets for readers of this README):

> **今日观察**
> **一、部件级（part-level）是今天最集中的爆发点，且两篇都寄生在 TRELLIS 谱系上。**
> [[Part-level generation is today's hottest cluster, and both papers parasitise the TRELLIS lineage.]]
> 两篇 3D 生成入选论文同时把「部件」提升为一等对象，但切口相反…… 两者都没有另起表示——前者冻结复用
> Hunyuan3D 的 ShapeVAE 作为 mesh-aware 条件，后者直接把 dual-volume packing 移植到 TRELLIS.2 自己的
> O-Voxel 稀疏网格上。
> [[Both elevate "parts" to first-class objects with opposite cuts, and neither invents a new
> representation: one freezes Hunyuan3D's ShapeVAE as a mesh-aware conditioner, the other ports
> dual-volume packing onto TRELLIS.2's O-Voxel grid.]]

Full sample: [`examples/2026-09-15-daily-digest.md`](examples/2026-09-15-daily-digest.md).

## How it works

```
arxiv-agent work
│
├─ 1. harvest        arxiv_client   Atom API → RSS → monthly listing, three channels with cache
├─ 2. dedup          seen.json      papers already surfaced in the last 7 days are skipped
├─ 3. screen         profile+       deterministic: vocabulary hits + lineage anchors − cold topics
│                                   hundreds of candidates → ≤90 sent to the model
├─ 4. jury           triage         LLM scores relevance / credibility / novelty per batch of 12
├─ 5. allocate       triage         composite score → area quotas → 10–15 papers, quality floor
├─ 6. verify dates   arxiv_client   every finalist is re-dated on its abs page; stale ones are dropped
├─ 7. read           fulltext +     arXiv HTML → ar5iv → PDF, section-prioritised; attach the repo
│                    github_client  (README, tree, recent commits)
├─ 8. analyse        analyze        per-paper Chinese reading note + cross-paper daily observation
├─ 9. report         report         reports/YY-MM-DD.md, including the transparency appendix
└─ 10. trending      github_client  rising non-paper repositories, model-filtered
```

Two `ThreadPoolExecutor`s (triage batches, then papers), both capped at `--max-concurrency`
whose hard ceiling is **2**. Wall clock is enforced per phase against a single monotonic
deadline.

## The parts that matter

### 1. The research map is data, not a prompt

`profile.py` encodes 4 areas, 17 sub-areas, ~41 named seed works and ~208 vocabulary terms:

| Area | Priority | Share of the digest | Sub-areas |
|---|---:|---:|---|
| 3D Generation | 1.0 | 45% | native latent, topology-aware, precision/efficiency, generation+reconstruction, rigging/parts, agentic 3D, 3D editing, transferable generative core |
| 3D Reconstruction | 0.8 | 25% | per-scene optimisation, feed-forward, efficiency & scaling, dynamic/4D |
| Video Generation | 0.62 | 20% | base models, editing & RL, image generation |
| Embodied AI | 0.35 | 10% | VLA policies, world models & simulation |

(`quota_weight` is what actually allocates slots; `priority` orders the map as it is rendered into
the prompt, and is what `quota_plan()` would use if you call it directly.)

Each sub-area carries the *reason it matters*, the routes inside it, and its **lineage anchors** —
the prior works (TRELLIS, Hunyuan3D-2.1, TripoSG, MeshGPT, VGGT, DUSt3R, MASt3R, 3DGS,
Wan-2.1, …) that define the route. The anchors are the mechanism that makes the screen feel
like an insider: a paper that extends, replaces or measures itself against a named anchor is
almost certainly on the map, and the screen rewards that explicitly rather than hoping a
keyword appears.

Institutions and venues are encoded too — 88 institution strings, 12 venue names — and they are
deliberately kept out of the numeric score. What reaches the model is a fixed list of the top 18
institutions plus the instruction that venue acceptance, version iteration and an active
repository are bonuses rather than quality guarantees; the deterministic matcher's per-paper
institution and venue hits are currently computed but not consumed downstream. Both prompts state
that prestige may never raise a score on its own. The first question is always "would you want to
read this tomorrow morning", not "is this from a famous lab".

### 2. Cheap filtering first, expensive judgement on the tip

```
hundreds of candidates
  │  deterministic: +1 per vocabulary hit, +2 per lineage anchor (word-boundary match),
  │  −2 per cold topic; prior = score + 3×lineage + 1×areas − 2×cold
  │  keep prior > 0, force-keep anything with a lineage hit, always pass the 10 newest
  ▼
≤ 90 candidates  →  LLM jury, batches of 12, three 0–10 scores each
  │  relevance (does it sit on a named route?) · credibility (is the evidence chain visible?)
  │  novelty (is it new relative to the known anchors?) · keep = relevance ≥ 3.5
  ▼
scored pool  →  portfolio allocation  →  10–15 papers
```

A missing keyword never proves irrelevance, so the ten newest papers are pushed to the jury
regardless of their score — the deterministic stage decides what deserves expensive attention,
never what is good.

### 3. Allocation, not a top-N list

Composite score per paper:

```
0.58 × relevance + 0.22 × credibility + 0.20 × novelty
  + min(2.5, 1.2 × lineage_hits)          # lineage bonus
  + 0.4  if it fits ≥2 areas              # cross-area bonus
  + strategy delta                         # feedback patterns, watch lists
  − 1.5  if the model never judged it      # never silently trusted
  then × area weight × sub-area weight     # feedback multipliers
```

Papers are then allocated to areas by quota (`quota_weight × feedback weight`), with two rules
that matter more than the arithmetic:

- **quality floor** — once the minimum count is met, nothing below raw relevance 5.0 is added;
- **no padding** — a quiet day yields a shorter digest, and the report says so. Minimum
  presence per area can top up a missing area, but a paper the user explicitly rejected
  (strategy delta ≤ −1.5) is never used to fill a slot.

### 4. Feedback becomes a versioned strategy file

Feedback is not turned into a hidden weight vector. It is compiled into
`.arxiv-agent/strategy.json` (+ a human-readable `strategy.md` mirror and an append-only
`feedback-log.jsonl`):

```jsonc
{
  "version": 7,
  "area_weights":       { "3d_generation": 1.15, "video_generation": 0.8, ... },
  "subarea_weights":    { "3d_generation/rigging_parts": 1.3 },
  "positive_patterns":  [ { "pattern": "open-source + ablation", "weight": 1.0, "reason": "..." } ],
  "negative_patterns":  [ { "pattern": "benchmark only", "weight": 3.0, "reason": "..." } ],
  "watch":              { "labs": [...], "authors": [...], "projects": [...] },
  "principles":         [ "优先推荐有开源代码与消融实验的工作" ],
  "paper_verdicts":     [ { "arxiv_id": "...", "verdict": "bad", "reason": "只是换了数据集" } ],
  "history":            [ { "version": 7, "summary": "...", "feedback_excerpt": "..." } ]
}
```

Every stage reads it: the jury and the reading prompts get the principles, patterns, watch
lists and the last 12 verdicts; the composite gets pattern/watch deltas; allocation gets the
area weights and the rejection veto. Weights are clamped (delta ±0.6, resulting weight
0.2–3.0), history is capped, and every patch is reversible — the file is meant to be read,
hand-edited and version-controlled. Nothing edits the source code.

### 5. Honesty is enforced in the architecture, not just in the prompt

- The **daily observation** may only assert what follows from the day's material, with
  uncertainty marked; it is skipped entirely when fewer than two papers were read properly.
- Every reading note separates 【原文】 from 【推断】 (inference), fills unknowns with
  "文中未提供" instead of plausible guesses, and carries an **evidence level** plus a
  "what I actually read" line (full-text source and character count; whether code was found).
- Dates are treated as hostile: RSS items without a date get a conservative guess from the
  arXiv id and are re-verified on their abstract page before selection, and again after. A
  digest never silently contains last month's paper.
- Failed model calls become explicit `_degraded` notes with confidence "低" — never a
  plausible-looking fabrication. If the harvest or the selection is empty, the run fails
  loudly instead of writing an empty digest.
- The report's transparency appendix lists every degradation, skipped paper and budget
  exhaustion that occurred during the run.

### 6. Cost, latency and failure control

A default run is ~20 model calls and 35–45 minutes. Both are bounded by design: a hard
concurrency cap of 2, a wall-clock budget (default 45 min, ceiling 60) enforced per phase, and
a degradation ladder that trades depth for completion:

| Budget left | What is dropped |
|---|---|
| < 35% | full-text budget 26,000 → 15,600 chars |
| < 20% | repository fetching (`--skip-code` behaviour) |
| < 240 s per paper | full text: abstract-only analysis, labelled as such |
| < 200 s per paper | GitHub repository attachment |
| < 180 s | the cross-paper daily observation |
| < 150 s | trending projects |
| < 90 s per paper | the model call itself — metadata-only note, confidence "低" |

arXiv access is a three-channel fallback (Atom API → RSS → monthly listing page) with a
3-second politeness delay, on-disk caching and a documented avoidance of server-side date-range
queries, which were observed to trigger `429 Rate exceeded`. Rate limiting is never fought by
hammering: a 429 stops that category and hands it to the next channel.

## Known limitations

Written down because a tool that hides its seams is a tool you cannot trust:

- **Model judgement is not peer review.** Scores are a triage heuristic; institution and venue
  signals are weak evidence. Every claim in the digest must be checked against the paper.
- **Some profile signals are computed and then dropped.** `screen_paper` returns per-paper
  institution and venue evidence that nothing downstream consumes, and `priority` is prompt-facing
  only — `quota_weight` is what allocates. Both are documented rather than quietly implied.
- **The screen is anchored to one person's map.** Swap the profile and scores shift
  (`docs/CUSTOMIZE.md` explains exactly which constants to change).
- **No cache TTL.** `abs:{id}` pages and extracted full text are cached forever; only
  `--no-cache` clears them, and a cached full-text hit reports its provenance as `cache`.
- **Full-text coverage is uneven.** Math is stripped from HTML, and the PDF path degrades to
  head truncation because whitespace collapsing removes the paragraph structure used for
  section prioritisation.
- **A digest of the same day overwrites the previous one** (`reports/YY-MM-DD.md`).
- **`model calls` in the report is a lower bound** — internal JSON-repair calls are not counted.
- **The arXiv window is not exhaustive.** Atom pagination stops after 400 entries per category
  per run, so a busy category can exceed the window on a `--days 7` run.
- **GitHub counters are unsynchronised** across the (at most two) worker threads, so the API
  budget and the 1 req/s spacing can be slightly exceeded near exhaustion.
- **`min_papers` is an aim, not a guarantee.** A quiet day produces a shorter digest on purpose.
- `seen.json` is written before the report is rendered, so a late failure can mark a paper as
  seen without delivering it.

## Configuration

`arxiv-agent work --help` for the full list. The knobs that matter:

| Flag | Default | Notes |
|---|---|---|
| `--days N` | 3 | 1–7, clamped |
| `--target N` / `--min-papers` / `--max-papers` | 12 / 10 / 15 | `max-papers` is hard-capped at 15 |
| `--model` / `--provider` | `gpt-4.1-mini` / auto | provider inferred from the model name; `auto\|openai\|codebuddy\|offline` |
| `--max-concurrency 1\|2` | 1 | hard cap 2, enforced in the CLI, the config layer and the orchestrator |
| `--time-budget N` | 45 | minutes, 5–60 |
| `--triage-pool N` | 90 | how many candidates reach the jury |
| `--output DIR` / `--state-dir DIR` | `reports` / `.arxiv-agent` | reports and personal state |
| `--skip-code` / `--skip-trending` / `--no-cache` / `--offline` | off | `--no-cache` deletes the fetch cache first |

Environment variables: `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `DEEPSEEK_API_KEY`,
`GITHUB_TOKEN`, `ARXIV_AGENT_MODEL`, `ARXIV_AGENT_PROVIDER`, `ARXIV_AGENT_OUTPUT_DIR`,
`ARXIV_AGENT_STATE_DIR`, `ARXIV_AGENT_DAYS`, `ARXIV_AGENT_MIN_PAPERS`,
`ARXIV_AGENT_MAX_PAPERS`, `ARXIV_AGENT_MAX_CONCURRENCY`, `ARXIV_AGENT_TIME_BUDGET`,
`ARXIV_AGENT_DEBUG`. Precedence: **CLI flag > `--config` JSON > real env var > `.env` > default**.

Deeper knobs (`categories`, `max_candidates`, `triage_batch`, `fulltext_chars`,
`request_delay`) live in a JSON config passed with `--config`:

```json
{ "days": 2, "target_papers": 12, "categories": ["cs.CV", "cs.GR", "cs.RO"], "triage_batch": 12 }
```

## Make it yours

The project is written for one researcher's map but structured so the map is the only thing you
have to replace: the four `ResearchArea` literals, `default_categories()`, and the
institution/venue/cold-topic lists in `profile.py` — see **[docs/CUSTOMIZE.md](docs/CUSTOMIZE.md)**
for the exact swap points and the traps (for example: stored `area_weights` keys that no longer
exist are dropped silently, so re-seed `.arxiv-agent/strategy.json` after a profile swap).

Design rationale and the original brief: **[docs/DESIGN.md](docs/DESIGN.md)**.
Module-by-module architecture and every constant: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**.
Releasing your own copy: **[docs/PUBLISHING.md](docs/PUBLISHING.md)**.

## Repository layout

```
src/arxiv_agent/            17 modules, ~3.5k lines, no runtime dependencies
  profile.py                the research map: areas, sub-areas, seed works, vocabulary
  arxiv_client.py           three-channel harvest, caching, date verification
  fulltext.py               HTML → ar5iv → PDF extraction with section prioritisation
  github_client.py          paper → repository binding; rising-project discovery
  triage.py                 deterministic screen, LLM jury, portfolio allocation
  analyze.py                per-paper reading note, daily observation, project judging
  strategy.py               versioned feedback memory (JSON + Markdown mirror)
  feedback.py               the interactive/one-shot feedback conversation
  report.py                 the Chinese Markdown digest
  agent.py                  orchestration: phases, budget, degradation ladder
  llm.py                    one interface, three backends (HTTP / CLI / offline)
  cli.py, config.py, models.py, prompts.py, __main__.py
tests/test_agent.py         38 offline tests: parsing, screening, allocation, strategy, CLI wiring
examples/                   a real, unedited digest
docs/                       design, architecture, customization, publishing
```

## Development

```bash
pip install -e ".[dev,fulltext]"
python -m pytest        # 38 tests, fully offline: no network, no credentials
python -m ruff check src tests
```

The test suite deliberately covers **logic, not the network**: fixtures are Atom/RSS/listing
XML fragments, GitHub JSON and scripted model replies. CI runs lint plus the suite on Python
3.10, 3.11 and 3.12, then smoke-tests the CLI. Since the offline backends never pretend to
analyse anything, `--offline` runs still exercise the entire pipeline end to end.

Contributions are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md). Security notes (key
handling, what stays local, prompt-injection exposure) are in [SECURITY.md](SECURITY.md).

## How this was built

This project was built by its author **with an AI coding agent**, and that is part of the
point: the author wrote the research map and the requirements brief, chose the architecture
(profile-as-data, two-stage funnel, strategy-as-a-file), reviewed every stage's behaviour
against real runs, and drove the iteration loop; the AI wrote most of the code under that
direction. The domain content — which routes matter, which lineage anchors define them, what
counts as a paper worth reading — is the author's, and it is the part that a generic tool
cannot supply. `docs/DESIGN.md` keeps the original brief alongside what was actually
implemented, including what was dropped.

## Roadmap

- A weekly roll-up that tracks how a route evolves across days instead of resetting each morning.
- Reading-queue state (read / skipped / worth-citing) so feedback can distinguish "bad pick"
  from "not yet read".
- Embedding-based near-duplicate detection beyond the arXiv id.
- A cache TTL and a lock file for the shared cache directory.

## License

MIT — see [LICENSE](LICENSE). Never commit `.env`, `.arxiv-agent/` or `reports/`: those hold
your keys, your evolving strategy and your research interests.
