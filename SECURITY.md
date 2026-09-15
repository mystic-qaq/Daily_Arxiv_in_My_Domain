# Security

## Credentials

This tool holds no credential store of its own. It reads three optional secrets from the
environment (or from a `.env` file in the working directory):

| Variable | Used for |
|---|---|
| `OPENAI_API_KEY` | the OpenAI-compatible model backend |
| `DEEPSEEK_API_KEY` | the same backend, for DeepSeek-compatible endpoints |
| `GITHUB_TOKEN` | raising the GitHub API budget for repository lookups |

`.env` is git-ignored, and no key, base URL or token value is ever written into a generated
report — the report discloses only the provider name, the model name and call counts.

If you believe a key has been committed, rotate it first and rewrite history second; deleting the
file in a later commit does not remove it from the repository.

## Data that stays local

`.arxiv-agent/` contains your evolving selection strategy, the per-paper verdicts you gave in
feedback, the raw feedback log and the arXiv fetch cache. `reports/` contains your reading
history. Both are git-ignored by default and should stay that way — together they describe your
research interests in detail.

## Prompt injection

Paper abstracts, full texts and repository READMEs are untrusted input: they are attacker-
controlled text that reaches an LLM prompt. The pipeline treats them as data, and the triage and
analysis prompts state explicitly that the paper text is data rather than instructions. This
reduces, but does not eliminate, the risk — a malicious paper could still influence how a model
scores or describes it. Do not treat a digest as an authoritative statement about a paper, and
never wire the digest into an automated action without human review.

## Reporting a vulnerability

Open a GitHub issue **without** the sensitive details, or use GitHub's private vulnerability
reporting if it is enabled for the repository, and describe the class of problem. Please do not
include a working exploit against a third-party service (arXiv, GitHub, or a model provider) in a
public issue.
