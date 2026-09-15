# Contributing

Thanks for looking. This is a personal research tool that was published because the design
might be useful to someone else — contributions, forks and profile swaps are all welcome.

## Before you start

- **The digest language is Chinese by design.** The output is written for a Chinese-speaking
  researcher and the prompts are Chinese. Please do not "fix" that.
- **The runtime has no third-party dependencies**, and that is a feature: only the standard
  library plus the optional `openai` and `pypdf` extras. A PR that adds a runtime dependency
  needs a strong justification.
- **Timing matters.** A daily run has a wall-clock budget and a model-call budget; a change that
  adds model calls proportional to the number of candidates will be judged on that basis, not
  just on accuracy.

## Development setup

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[dev,fulltext]"
python -m pytest         # 38 tests, offline
python -m ruff check src tests
```

Everything must pass offline. Tests are not allowed to touch the network, call a model, or read
credentials — fixture-based only (Atom/RSS/listing XML snippets, GitHub JSON, scripted model
replies). If a change is hard to test that way, say so in the PR description rather than adding
a network-dependent test.

## What a good change looks like

1. **One concern per PR**, with the reasoning in the description.
2. **Behaviour that the report claims must be behaviour the code has.** If you change a stage's
   degradation path, update the report's transparency section (and the README's "Known
   limitations" if you remove one).
3. **New thresholds and coefficients must be justified** in the PR description and reflected in
   `docs/ARCHITECTURE.md`; the numbers in that document are meant to stay true.
4. **Nothing may silently pad, fake or guess.** A digest that is short, a note that says
   "文中未提供", a labelled degraded entry — all fine. A plausible-looking fabrication is a bug
   of the highest severity.
5. **Commits**: imperative subject line, one logical change, no unrelated reformatting.

## Proposing a different research field

Do not edit the shipped profile to your own area in a PR — it is one specific person's map. Add
or improve the *mechanism* instead (better anchor matching, a new signal, a cleaner profile
schema), and document how to swap the map: see [docs/CUSTOMIZE.md](docs/CUSTOMIZE.md).

## Reporting a bug

Include the exact command line, the Python and OS version, the model backend, and the relevant
block of the generated report (the `## 选取过程透明度` appendix is usually the most informative
part). Redact API keys and anything you do not want public. The issue template asks for exactly
this.

## Asking a question

Open a discussion or an issue with the `question` label. If the answer is "the README says X",
the README probably needs to be clearer — say so, and we will fix the README.

## License

By contributing you agree that your contribution is licensed under the MIT License (see
[LICENSE](LICENSE)).
