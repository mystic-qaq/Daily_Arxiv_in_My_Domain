# Customizing the research profile

`src/arxiv_agent/profile.py` is the one file you have to replace to point this agent at your own
field: everything else reads the profile as data. Line numbers are from the shipped revision; for why
the map is data rather than prompt prose, see [DESIGN.md](DESIGN.md).

## 1. What the profile is

Three frozen dataclasses carry the whole map (`profile.py:33-57`):

| Dataclass | Lines | Fields |
|---|---|---|
| `SeedWork` | 33-37 | `name`, `route` (one line on what the work defines), `aliases` |
| `SubArea` | 40-46 | `key`, `name`, `why`, `seeds`, `vocab` |
| `ResearchArea` | 49-57 | `key`, `name`, `priority`, `quota_weight`, `posture`, `subareas`, `vocab` |

The shipped instance: 4 areas, 17 sub-areas, 41 seed works, 208 vocabulary terms (32 at area level,
176 at sub-area level). Four consumers read that data:

| Consumer | Reads it in | Effect |
|---|---|---|
| Deterministic screen | `profile.screen_paper` (`profile.py:338-390`), called by `triage.screen` (`triage.py:44-71`) | vocabulary hits and lineage anchors become the prior score that decides which candidates reach the model |
| LLM prompts | `profile.profile_brief` (`profile.py:396-425`) | the map as Chinese prose, into the triage prompt (`triage.py:94-95`), the reading prompt (`analyze.py:128`), the project filter (`analyze.py:218`) and the feedback synthesiser (`feedback.py:139`) |
| Feedback vocabulary | `strategy.py:19,26,174-187`; `feedback.py:166-169` | `area_weights` / `subarea_weights` are keyed by `ResearchArea.key` and `"<area_key>/<subarea_key>"` |
| Allocation weights | `quota_weight`, in `triage.select_portfolio` (`triage.py:191`) | how the digest slots are split between areas |

## 2. The five swap points

| # | Symbol | Lines | Edit it? |
|---|---|---|---|
| 1 | four `ResearchArea` literals + `AREAS` | 60-150, 152-202, 204-237, 239-266; `AREAS` 268 | yes — the core edit |
| 2 | `AREA_BY_KEY`, `SUBAREA_BY_KEY`, `AREA_NAMES`, `AREA_INDEX` | 269, 270, 271, 393 | **no** — derived at import |
| 3 | `default_categories()`; `Settings.categories` | `profile.py:453-459`; `config.py:61` | yes |
| 4 | `TOP_INSTITUTIONS`, `VENUE_TERMS`, `COLD_TOPICS` | 279-299, 301-303, 307-312 | yes, but read the caveats |
| 5 | the `vocab` tuples on areas and sub-areas | inside the literals | yes |

**1. The area literals and `AREAS`.** `AREAS` (268) is the ordered tuple the pipeline iterates, so its
order is also the digest's reading order (`triage.py:241-242`), the tie-break for area candidates
(`profile.py:376`) and the `quota_plan` tie-break (`profile.py:439`). `key` is the contract with the
model's JSON reply and the strategy file: an unknown key is thrown away by `_normalise_area`
(`triage.py:82-90`), the paper falls back to `area_candidates[0]` or to `"other"`, and `"other"` is
excluded from quota allocation (`triage.py:186-189`), recoverable only by the leftover-fill loop
(`triage.py:227-238`). Weights are normalised by their own sum (`triage.py:191-193`), so `quota_weight`
need not total 1.0 — but `profile_brief` prints `quota_weight × 100` as 目标份额 (405), so a set that
does not sum to 1.0 tells the model something false. Keep sub-area keys unique *within* an area:
`SUBAREA_BY_KEY` is a dict comprehension (270) and a duplicate silently overwrites.

**2. The derived dicts — do not edit.** `AREA_BY_KEY` (269), `SUBAREA_BY_KEY` (270), `AREA_NAMES`
(271) and `AREA_INDEX` (393) are all built from `AREAS` at import; edit an area and they follow.
Nothing validates a hand-edited profile, so a manual edit only produces one that contradicts itself.
The composite key format `f"{area.key}/{subarea.key}"` (270) is what the model must return, what the
feedback shorthand accepts (`feedback.py:166-169`) and what `subarea_weights` is keyed by.

**3. `default_categories()` and `Settings.categories`.** `default_categories()` returns the six arXiv
categories the harvest queries: `cs.CV, cs.GR, cs.RO, cs.MM, cs.AI, cs.LG`. `Settings.categories`
(`config.py:61`) is a `default_factory` over it, unless you pass `--config`:
`Settings.load_json` (`config.py:116-124`) feeds arbitrary field names into the dataclass, so
`{"categories": ["q-bio.BM", "cs.CE"]}` replaces the list without touching the source. These are the
*only* categories harvested, so a list that misses where your field publishes gives an empty run —
the agent raises `最近 N 天内没有抓到任何候选论文` (`agent.py:136-138`) rather than writing an empty
digest — and a broader list competes for the same `max_candidates = 600` and `--triage-pool`
(`config.py:62-63`). The shipped list deliberately drops the `cs.CL`/`cs.NE` bulk (docstring 456-458).

**4. `TOP_INSTITUTIONS`, `VENUE_TERMS`, `COLD_TOPICS`.** What the code actually does here:
`TOP_INSTITUTIONS` (279-299) and `VENUE_TERMS` (301-303) are matched case-insensitively as plain
substrings (377-378) and returned as `institutions`/`venues` (386-387) — but **nothing else reads
those two keys**; `triage.screen` consumes only `keyword_hits`, `lineage_hits`, `area_candidates`,
`screen_score` and `cold_topics` (`triage.py:48-56`), and `Paper` has no field for them. The only
place the institution list reaches a model is the generic line in `profile_brief` rendering **the
first 18 entries** (416); editing `VENUE_TERMS` has no effect at all. `COLD_TOPICS` (307-312) is read
twice: the full tuple as `-2` per distinct term in the prior (`triage.py:55-56`), and **the first 10
entries** shown to the model as a down-weight instruction (418). So treat #4 as low-leverage.

**5. The vocabulary lists.** `ResearchArea.vocab` and `SubArea.vocab` are matched as **plain
substrings** of the lowercased `title + abstract + comment` (`paper_text`, 334-335; loop at
353-362), *not* on word boundaries. Every hit is worth exactly `+1` to the prior whichever level it
came from, because sub-area scores roll up into the area score (368-369) and the prior's `base` is
their sum (389; `triage.py:52`). Precision, not recall, is the risk: verified collisions in the
shipped map are `rig` inside "originals" and `faces` inside "surfaces". Stems are deliberate
(`histopatholog`, `agricultur`); keep terms long enough to be unambiguous.

## 3. Seed works: lineage anchors

The most valuable part of the file. The mechanism, verified end to end:

1. **Word-boundary match.** Each seed's `name.lower()` and every alias are matched with
   `(?<![a-zA-Z0-9])term(?![a-zA-Z0-9])` (`_word_re`, 330-331) against the lowercased haystack, so
   `TRELLIS.2` matches the anchor `trellis` but `TRELLIS2` and `3DGSplat` match nothing — add glued
   and versioned forms as aliases.
2. **+2 per anchor** into the sub-area score (363-367), part of `screen_score` and so of `base`.
3. **+3 per distinct anchor** in the prior: `prior = base + 3×lineage + 1×areas − 2×cold`
   (`triage.py:56`). `lineage_hits` stores the seed's `name`, de-duplicated (366, 382), so two aliases
   of one seed give `+4` in `base` but one `+3`: alias coverage beats more seeds.
4. **Forced inclusion.** Any paper with a lineage hit is appended to the jury pool even when its prior
   is not positive (`triage.py:63-64`), before truncation to `--triage-pool` (71); the ten newest
   candidates follow (68).
5. **Composite bonus** `min(2.5, 1.2 × lineage_hits)` (`triage.py:150-154`): one hit `+1.2`, two
   `+2.4`, three or more `+2.5`.
6. **Shown to the model as the definition of the route.** `profile_brief` renders
   `已知代表工作：TRELLIS（Structured (sparse voxel) latent + rectified flow…）` plus the rule that a
   work extending, contrasting or improving one of those is high-relevance (411-413), and the reading
   prompt asks for a `lineage` section naming them (`analyze.py:48-49`). `route` strings are read by
   the model — write them for it.

Practical guidance:

- **Pick works that define a route, not the most-cited papers.** An anchor earns its keep when new
  abstracts say "we extend X" or "unlike X"; a famous paper nobody positions against adds nothing.
- **Cover each sub-area with 2-6 anchors.** Zero seeds is legal — `video_generation/video_edit_rl`
  and `video_generation/image_gen` ship with `seeds=()` — but such a sub-area can never earn the
  lineage signal and lives on vocabulary alone.
- **Write aliases the way titles write them**: short, hyphenated and spaced forms, as `Hunyuan3D-2.1`
  does with `("hunyuan3d", "hunyuan-3d", "hunyuan 3d")`.
- **Avoid generic names.** The shipped map shows the failure mode: `SeedWork("Procedure", …,
  ("procedure",))` (122) matches any abstract containing the word "procedure" — verified.
- Keep keys and names stable once feedback accumulates: anchor names surface in the report appendix.

Worked micro-example — a different field, storage engines and transaction processing (note the English
prose: a non-Chinese profile mixes languages in a Chinese prompt frame, see §7):

```python
SubArea(
    key="storage_engines",
    name="Storage engines and transaction processing",
    why="LSM and B-tree engines plus concurrency control set the throughput ceiling everything above inherits.",
    seeds=(
        SeedWork("RocksDB", "LSM-tree engine, compaction and write stalls", ("rocksdb", "rocks db")),
        SeedWork("LevelDB", "The LSM design RocksDB forked from", ("leveldb", "level db")),
        SeedWork("Bw-tree", "Latch-free B-tree with delta records", ("bw-tree", "bw tree")),
        SeedWork("WiredTiger", "Engine with checkpoints and hazard pointers", ("wiredtiger", "wired tiger")),
        SeedWork("TicToc", "Timestamp-ordering optimistic concurrency control", ("tictoc", "tic-toc")),
        SeedWork("Umbra", "Disk-based system with in-memory performance", ("umbra",)),
    ),
    vocab=("lsm-tree", "compaction", "write amplification", "mvcc", "concurrency control"),
),
```

## 4. Weights that actually change behaviour

| Field | Read at | Live effect |
|---|---|---|
| `quota_weight` | `triage.py:191` | slot share per area; also rendered to the model at `profile.py:405` |
| `quota_weight` | `profile.py:436`, in `quota_plan` (432-446) | **none at runtime** — nothing in `src/` calls `quota_plan`; only `tests/test_agent.py:114` does |
| `priority` | `profile.py:439` via `area_priority_rank` (449-450) | only inside `quota_plan`, so also inert at runtime |
| `priority` | `profile.py:405` | printed into the prompt as 优先级=…, a nudge rather than a rule |

So `quota_weight` decides the digest shape and `priority` is documentation plus prompt context. What
45/25/20/10 means for a 12-paper digest, from `triage.py:191-204` and verified by running it:

```
weights       = quota_weight × strategy.area_multiplier           # 0.45  0.25  0.20  0.10
raw slots     = 12 × weight / Σweight              ->  5.4    3.0    2.4    1.2
int(round(·))                                      ->   5      3      2      1     = 11
top-up: +1 to the largest weight with candidates   ->   6      3      2      1     = 12
```

The top-up fires only if that area still has candidates below its slot count; otherwise it moves to the
next-largest weight, and if nothing is growable the digest is shorter than the target
(`triage.py:195-199`) — rounding overshoot is shrunk back from the smallest weight (200-204). A
feedback weight multiplies an area's composite scores as well as its slot share (`triage.py:162-165`).

`COLD_TOPICS` subtracts `2` per **distinct** matching term from the deterministic prior
(`triage.py:55-56`) — a set, so repeats do not compound — and is **never a hard filter**: a cold paper
still reaches the jury through a lineage hit (63-64) or by being among the ten newest (68), and `+3`
per anchor usually outweighs a single `-2`.

## 5. After the swap: reset the stored strategy

`.arxiv-agent/strategy.json` holds area and sub-area weights keyed by profile keys, and both write
paths **silently drop** unknown keys: `apply_patch` skips `key not in AREA_BY_KEY` /
`key not in SUBAREA_BY_KEY` (`strategy.py:174-187`) and the `+area/key` shorthand does the same
(`feedback.py:166-169`). Nothing warns you: `context_block` prints unknown area weights under their
raw key (`strategy.py:78-83`) and `render_markdown` lists unknown sub-area weights as `未知`
(`strategy.py:270-274`), while stale *area* keys are missing from that table entirely (267-268).

Delete `.arxiv-agent/strategy.json` and `.arxiv-agent/strategy.md`, but keep `cache/` and `seen.json`
in that directory: `cache/` saves the re-download and `seen.json` stops the next digest repeating
papers you were already shown (`agent.py:142-147`). Then verify with `arxiv-agent strategy` (alias
`策略`), which prints `store.render_markdown()` (`cli.py:94-99`): with no file you get version 1, every
area at `×1.00` and no sub-area rows — the clean state. To keep accumulated feedback, hand-edit the
JSON keys instead and re-run until no `未知` rows remain.

## 6. Sanity check

`--offline` is verified to do exactly one thing: install `OfflineBackend` instead of a real backend
(`cli.py:75-76` → `settings.offline` → `llm.py:200-202`; the only reader of that flag in `src/`).
Consequently no model call is made — `complete()` returns `""`, `complete_json()` returns `{}` or
`{"results": []}` (`llm.py:170-182`) — and all scores are heuristics:

- Triage falls back to relevance/credibility/novelty `= 4.0` with the `llm` flag `0`
  (`triage.py:120-126`), so the composite is `4.0 − 1.5 = 2.5` plus lineage and cross-area bonuses,
  and every reading note becomes the degraded metadata-only note with confidence 低
  (`analyze.py:154-171`); the daily observation is skipped, needing two non-低 notes (`agent.py:219`).
- Harvest, abs-page date verification, full-text fetching and GitHub lookups **still run and still
  need the network** (or a warm `.arxiv-agent/cache`); `--skip-code --skip-trending` keeps it cheap.
- Offline relevance is exactly 4.0, below the quality floor of 5.0 (`triage.py:233`), so the digest
  stops at `min_papers`; `--target 3` also drags `min_papers` down to 3 (`config.py:133`).

```bash
# 1. pipeline only, no model cost: does your map produce candidates at all?
arxiv-agent work --offline --days 2 --target 3 --skip-code --skip-trending

# 2. a real but small run: does the map select the right things?
arxiv-agent work --days 2 --target 5 --triage-pool 30 --min-papers 3

# 3. the offline suite — no network, no credentials
python -m pytest
```

Then open `reports/YY-MM-DD.md` and read `## 选取过程透明度` (`report.py:124-153`): the funnel
(`候选 → 初筛保留 → 模型评审 N 轮 → 入选`), the per-area quota actually used, the leftovers and the
day's lineage-hit count. Check the quota line against §4's arithmetic for your weights, and that the
hits are successors of your anchors — zero hits for an area means your aliases never appear in abstracts.

The suite is 38 offline tests. Four assert on the shipped map and are expected to fail after a swap;
they are that map's regression tests, not a generic contract:

| Test (`tests/test_agent.py`) | Coupling |
|---|---|
| `test_lineage_hit_beats_generic_keyword_counting` (89) | requires `"TRELLIS"` as a lineage hit and `3d_generation` ranked first |
| `test_off_topic_paper_has_no_area_candidates` (98) | assumes a tabular-diffusion finance paper matches nothing |
| `test_quota_plan_distributes_all_slots` (114) | indexes `plan["3d_generation"]` and `plan["embodied_ai"]` |
| `test_selection_respects_priority_quotas` (255) | builds fixtures from `TRELLIS`/`OpenVLA`, reads `stats["slots"]["3d_generation"]` |

`test_profile_brief_lists_all_areas_in_language_the_model_can_use` (105) is the one generic
invariant — it walks `AREAS` and asserts every area and sub-area key survives rendering. Keep it, and
rewrite the other four around your own anchors.

## 7. Common mistakes

- **Sub-area keys are composite**: `"<area_key>/<subarea_key>"` (`profile.py:270`), not the sub-area
  key alone; otherwise the model's `subarea` value is discarded (`triage.py:82-90`) and
  `subarea_weights` never apply.
- **The profile is Chinese by design.** `posture`, `why` and `route` are injected verbatim into
  Chinese prompts with Chinese section headers (`profile.py:396-425`, `analyze.py:35-62`): either
  write your replacement in Chinese too, or translate the prompt layer consistently.
- **Two different matching rules.** Vocabulary terms are plain substrings of the lowercased
  `title + abstract + comment`; seed aliases use ASCII word boundaries. So `"3d"` as a vocab term
  matches everything, `rig` matches "originals", and `faces` matches "surfaces".
- **Capitals in `COLD_TOPICS` can never match.** The haystack is lowercased (`profile.py:334-335`) and
  the comparison is `name in text` (379), so the shipped `"CT reconstruction"`, `"MRI"`, `"fMRI"` and
  `"EEG"` entries are dead — verified: a paper titled "MRI reconstruction" yields `cold_topics: []`.
  Write your own entries in lowercase, and delete the ones describing your new field instead of
  someone else's (`protein`, `drug discovery` are shipped cold topics).
- **`priority` allocates nothing at runtime** — `quota_weight` does (§4) — and **the derived dicts are
  rebuilt from `AREAS` at import**, so never hand-edit them.
- **New routes need the right categories**: sub-areas in `q-bio.BM` with `default_categories()` still
  returning `cs.*` harvest nothing relevant.
- **Stale weights are dropped silently**, so a profile swap can look successful while every stored
  preference is already gone (§5).
