# Pull request

## What and why

<!-- One paragraph: what changes, and what problem it solves. -->

## Checklist

- [ ] `python -m pytest` passes (offline — no network, no credentials added)
- [ ] `python -m ruff check src tests` passes
- [ ] I did not commit `.env`, `.arxiv-agent/`, `reports/`, or any credential
- [ ] New thresholds/coefficients are justified below and reflected in `docs/ARCHITECTURE.md` if it documents them
- [ ] If this changes a degradation path, the report's `## 选取过程透明度` output stays truthful
- [ ] If this changes user-visible behaviour, `README.md` (and `README.zh-CN.md`) are updated
- [ ] Nothing here fabricates results: failures are labelled, not papered over

## Cost impact

<!-- Model calls per run: unchanged / +N per candidate / +N per paper. Wall clock: unchanged / +N minutes. -->
