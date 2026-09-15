# Publishing your own copy

This repository is written to be cloned, renamed and published. This is the checklist for
turning your working copy into your own public project. Nothing here is required to *use* the
tool — only to publish it.

---

## 1. Replace the `OWNER` placeholder

Every outbound link currently points at `github.com/OWNER/Daily_Arxiv_in_My_Domain`. Replace
`OWNER` with your GitHub username (the repository name can stay as it is, or be renamed
everywhere in the same pass).

```bash
# macOS / Linux — preview first, then apply
grep -rl "OWNER" --include="*.md" --include="*.toml" --include="*.cff" --include="*.yml" . | grep -v '^./.venv'
grep -rl "OWNER" --include="*.md" --include="*.toml" --include="*.cff" --include="*.yml" . | grep -v '^./.venv' | xargs sed -i 's|OWNER|<your-github-username>|g'
```

```powershell
# Windows PowerShell
$files = Get-ChildItem -Recurse -Include *.md,*.toml,*.cff,*.yml -File |
    Where-Object { $_.FullName -notmatch '\\\.venv\\|\\\.git\\' }
$files | Select-String -Pattern 'OWNER' | Select-Object Path, LineNumber
$files | ForEach-Object {
    (Get-Content $_.FullName -Raw) -replace 'OWNER', '<your-github-username>' |
        Set-Content $_.FullName -NoNewline -Encoding utf8
}
```

Files that contain the placeholder:

| File | Where |
|---|---|
| `README.md` | CI badge URL (twice), clone command |
| `README.zh-CN.md` | same |
| `pyproject.toml` | `[project.urls]` — Homepage, Repository, Issues, Changelog |
| `CHANGELOG.md` | the release link at the bottom |
| `CITATION.cff` | `repository-code` and `url` |
| `docs/PUBLISHING.md` | this document |

## 2. Put your name on it

| File | What to change |
|---|---|
| `LICENSE` | `Copyright (c) 2026 …` — your name or handle |
| `CITATION.cff` | `authors:` — replace the placeholder with your family/given names, and optionally an ORCID |
| `pyproject.toml` | optionally add an `authors` list under `[project]` |

## 3. Verify that nothing private is about to be published

```bash
git status --short                 # what is actually staged
git check-ignore -v .env .arxiv-agent reports   # all three must be ignored
git ls-files | grep -Ei '\.env$|strategy\.json|seen\.json|feedback-log|^reports/'   # must print nothing
```

**Must never be committed:** `.env` and any API key, `.arxiv-agent/` (your evolving strategy,
your paper verdicts, the raw feedback log, the fetch cache), `reports/` (your reading history),
and any note file you wrote for yourself.

The repository ships with a real digest under `examples/` — it is the author's own output and was
published deliberately. If you replace it with one of yours, remember that it reveals your
research interests in detail.

A cheap secret scan before the first push:

```bash
git grep -nE "sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}" $(git rev-list --all) || echo "clean"
```

## 4. Create the repository and push

```bash
git add -A
git commit -m "Initial public release"
git branch -M main
git remote add origin https://github.com/<your-github-username>/Daily_Arxiv_in_My_Domain.git
git push -u origin main
```

Or, with the GitHub CLI:

```bash
gh repo create Daily_Arxiv_in_My_Domain --public --source=. --push
```

Then, in the repository settings:

- **Description** — one line, for example *"A daily arXiv scout that knows your research map:
  deterministic screen → LLM jury → portfolio allocation, with a selection strategy that evolves
  from your feedback."*
- **Topics** — `arxiv`, `llm-agent`, `literature-review`, `research-tools`,
  `paper-recommendation`, `python`.
- **Social preview** — optional; a screenshot of a digest section works better than the default.

## 5. Confirm CI is green

Open the **Actions** tab. The workflow runs on every push and pull request:

1. install (`pip install -e ".[dev,fulltext]"`),
2. `ruff check src tests`,
3. `pytest` — 38 offline tests, no network and no credentials,
4. a CLI smoke test (`--help`, `strategy`, `python -m arxiv_agent`).

All of it on Python 3.10, 3.11 and 3.12. The badge in the README renders only after the first
run completes; if it shows "no status", either the workflow has not run yet or the `OWNER`
placeholder was not replaced.

## 6. Cutting a release (later)

Versions live in three places and must agree:

| File | Field |
|---|---|
| `pyproject.toml` | `version` |
| `src/arxiv_agent/__init__.py` | `__version__` |
| `CHANGELOG.md` | a new section, plus the release link at the bottom |

```bash
git tag -a v0.4.0 -m "v0.4.0"
git push origin v0.4.0
gh release create v0.4.0 --generate-notes
```

## 7. Ongoing hygiene

- The skill that makes this project useful is the profile, not the code: when your own reading
  changes your map, edit `profile.py` and say so in the commit message (see
  [CUSTOMIZE.md](CUSTOMIZE.md)).
- Keep `.arxiv-agent/` out of every commit, including `git add -A` sweeps. It is in
  `.gitignore`; do not remove it from there.
- If you add a screenshot or a demo, put it in `docs/` and reference it relatively so the README
  renders correctly on GitHub.
- After copying this repository, delete or rewrite `examples/` — a published digest is a
  snapshot of what you were reading.
