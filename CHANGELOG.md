# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — first public release

The first version published as an open-source project. Earlier 0.1.x/0.2.x builds
were private iterations of the same pipeline.

### Added

- **Research profile as data** (`profile.py`): 4 areas, 17 sub-areas, priority and
  quota weights, ~41 named seed works used as lineage anchors, ~208 vocabulary terms,
  and a deterministic `screen_paper` scorer.
- **Two-stage selection**: deterministic screening → batched LLM jury (relevance /
  credibility / novelty) → portfolio allocation with per-area quotas, lineage
  bonuses and feedback deltas.
- **Full-text reading**: arXiv HTML → ar5iv → PDF extraction with section
  prioritisation and a per-paper character budget.
- **Code awareness**: paper→repository binding and a "rising projects" section for
  non-paper repositories.
- **Chinese daily digest**: per-paper architecture / lineage / insight / evaluation /
  code / limitations / why-read / reading plan / evidence level, plus a cross-paper
  daily observation and a transparency appendix.
- **Feedback loop**: interactive or one-shot feedback synthesised into a versioned
  `strategy.json` (+ human-readable `strategy.md` and an append-only
  `feedback-log.jsonl`) that re-weights the next run without touching source code.
- **Three model backends** behind one interface: any OpenAI-compatible HTTP endpoint,
  a locally authenticated CLI gateway, and a deterministic offline backend.
- **Graceful degradation**: three arXiv ingestion channels, per-phase time budget,
  model-timeout shrinking, and an explicit record of every degradation in the report.
- **Offline test suite**: 38 tests, no network and no credentials.

### Changed

- Default model is now a widely available OpenAI-compatible id instead of a
  machine-specific CLI model; `.env` in the working directory is loaded automatically
  (real environment variables still win).
- CLI help text no longer assumes one particular research area.

### Fixed

- Python 3.10 and 3.11 could not even parse `report.py` (nested same-type quotes in an
  f-string, PEP 701), so the advertised `requires-python = ">=3.10"` was wrong.
- `GitHubClient.repo_facts` raised `UnboundLocalError` once fewer than four GitHub API
  calls remained in the budget.
- `ARXIV_AGENT_TIME_BUDGET` crashed startup with `TypeError` — it was derived into a
  field name that does not exist.
- An omitted `--provider` flag silently overwrote a provider configured through the
  environment or a config file.
- Case-sensitive matching meant cold-topic terms such as `MRI` and `CT reconstruction`
  could never match, because the text they are matched against is lowercased.
- `ARXIV_AGENT_DEBUG=0` enabled tracebacks (string truthiness).
- Removed `ranking.py`: dead code that referenced fields which do not exist and would
  have crashed if it had ever been called.

[0.3.0]: https://github.com/OWNER/Daily_Arxiv_in_My_Domain/releases/tag/v0.3.0
