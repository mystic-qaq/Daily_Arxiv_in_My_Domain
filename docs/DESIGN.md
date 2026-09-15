# Design notes

This document is the specification the project was built against, kept alongside what was
actually implemented. It exists because the interesting decisions in a system like this are not
in the code — they are in what was chosen, what was refused, and why.

The original brief was written by the author for an AI coding agent before any code existed.
It is not published as-is — it reads as a set of instructions to a builder rather than as a
specification of a system, and this document replaces it. The domain knowledge it contained is
preserved where it belongs: encoded as data in
[`src/arxiv_agent/profile.py`](../src/arxiv_agent/profile.py), and summarised in §4 below.

This file restates the brief as a design document, records the domain knowledge, and marks the
places where the implementation deliberately diverged from it.

---

## 1. Problem

A researcher working on fast-moving generative-modelling topics faces a daily triage problem:
several hundred new arXiv submissions land per day across `cs.CV`, `cs.GR`, `cs.RO`, `cs.MM`,
`cs.AI` and `cs.LG`, of which perhaps ten matter to them, and the signal that identifies those
ten is **not lexical**. A keyword alert cannot distinguish "a TRELLIS successor with a new
structured-latent interface" from "diffusion applied to an unrelated domain"; both contain
"diffusion", "latent" and "generation".

The same problem appears twice more:

- **After selection**: knowing *that* a paper is relevant is not the same as knowing what to
  read first, what it changes relative to prior work, and whether the evidence supports it.
- **Over time**: a static filter cannot absorb the reader's judgement. A recommendation that
  was wrong yesterday will be wrong again tomorrow.

## 2. Goals

| # | Goal | Acceptance |
|---|---|---|
| G1 | Select 10–15 papers from the last 1–7 days that sit on the reader's research lines | Selection is explainable per paper: area, sub-area, three scores, a one-line reason, and which named prior work it relates to |
| G2 | Read each selected paper properly and produce an actionable Chinese Markdown note | Per-paper sections: architecture, relation to prior work, insight, innovations, evaluation, code, limitations, why read, how to read, evidence level |
| G3 | Absorb reader feedback into future selection without touching source code | Feedback compiles into a versioned, human-readable, hand-editable strategy file that visibly changes the next run |
| G4 | Stay inside the reader's attention and token budget | Hard concurrency cap of 2, wall-clock ceiling under one hour, **no intermediate output** during a run |
| G5 | Be honest about what it does not know | Evidence levels per paper, 【原文】/【推断】 separation, explicit degradation notes, refusal to pad the digest |

## 3. Non-goals

- **Not a literature search engine.** It answers "what should I read this morning", not "find me
  everything about X".
- **Not a peer reviewer.** Scores are triage heuristics, not quality verdicts.
- **Not a general recommender.** It is deliberately overfit to one research map; generality is
  the reader's job, via `CUSTOMIZE.md`.
- **Not a citation-graph service.** Lineage detection is lexical + model-based, not a citation
  database lookup.

## 4. The domain knowledge (the part a generic tool cannot supply)

The brief supplied a research map, which is encoded in
[`src/arxiv_agent/profile.py`](../src/arxiv_agent/profile.py). It is the project's core asset.

### Areas, in order of relevance to the reader

| Area | Priority | Share | Routes inside it |
|---|---:|---:|---|
| **3D Generation** | 1.0 | 45% | Native latent-space generation (VecSet-like and voxel-like representations decoded to SDF/fields, surface extraction); topology-aware generation (vertices + faces, AR / diffusion / flow-matching); precision-efficiency work; generation fused with reconstruction for instruction following; native rigging and part decomposition for interaction-ready assets; agentic 3D generation (3D + LLM/VLM agents); 3D editing; transferable generative cores (AR / flow / diffusion / VLM / RL) |
| **3D Reconstruction** | 0.8 | 25% | Per-scene optimisation (SfM/MVS, NeRF and variants, 3DGS and variants); feed-forward reconstruction (object-level and scene-level); efficiency and scaling laws; dynamic/4D reconstruction |
| **Video Generation** | 0.62 | 20% | Base models and architectures; editing and RL post-training; benchmark quality; image generation as the degenerate case |
| **Embodied AI** | 0.35 | 10% | VLA models and robot policies; world models and simulation |

Each sub-area carries **lineage anchors**: the named prior works that define the route
(TRELLIS, Hunyuan3D-2.1, TripoSG, Seed3D, Direct3D, MeshGPT, Nexus, LATO.2, Block3D, Pixal3D,
SAM3D, PartCrafter, PhysX-Anything, SAGE, Procedure, Lucida, Hunyuan-Buffalo, DreamDPO,
FlowGRPO, DiffusionNFT, Diffusion-OPSD, COLMAP, MVSNet, NeRF, 3DGS, LRM, TripoSR, DUSt3R,
MASt3R, VGGT, VGGT-Omega, D4RT, Wan-2.1, MiniMax, OpenVLA, π₀ …).

**This list is the mechanism.** A new paper that extends, replaces or benchmarks against one of
these anchors is almost certainly inside the reader's map, whether or not it reuses the
vocabulary — and the pipeline treats such a hit as strong evidence at every stage. Encoding the
map as data rather than prompt prose also makes it auditable: every selection decision can be
traced back to a named route.

### The affiliation heuristic, and why it was demoted

The brief suggested that a first or corresponding author from a well-known company or
institution makes a paper "probably not a bad paper". That is a real-world-useful prior and a
bad ranking signal: it is unverifiable from the abstract, it systematically favours labs that
already have attention, and it invites the model to hallucinate prestige.

The implementation therefore encodes institutions and venues (88 institution strings, 12 venue
names) but **never lets them enter the numeric screen or the composite score**. A fixed list of
the top 18 institutions reaches the prompts as explicitly weak context, alongside the instruction
that venue acceptance, version iteration and an active repository are bonuses rather than quality
guarantees — and both the triage and analysis prompts forbid scoring on fame, next to the general
ban on inventing authors, institutions, metrics and links. (The deterministic matcher also
computes per-paper institution and venue hits; nothing consumes them yet — see the README's known
limitations.) The first question is "would the reader actually want to read this tomorrow
morning".

## 5. Constraints (from the brief, and how each is enforced)

| Constraint | Enforcement |
|---|---|
| Model concurrency at most 2 | `MAX_CONCURRENCY = 2` in `config.py`, re-clamped by `Settings.clamp()`, by the CLI's argparse `choices=(1, 2)`, and again in the orchestrator |
| A run must finish inside an hour | `time_budget_min` default 45, clamped to 5–60; a single monotonic deadline; per-phase deadlines and remaining-ratio gates; the model timeout itself shrinks as the budget is consumed |
| No intermediate output during `work` | The CLI prints only the final report path; all progress and failure detail goes into the report's transparency appendix instead |
| 10–15 papers, min 10, target 12 | `max_papers` hard-capped at 15 in the config layer; `min_papers` is a floor on the *target*, never a reason to pad (see G5) |
| Feedback must change future selection | Versioned strategy file, read by the jury prompt, the composite score, the allocation weights and the area top-up veto |
| Read the open-source code, not just the abstract | Repository binding from the full text / abstract / comment, then README, tree overview and recent commits are fed to the reading prompt |
| Optional: rising non-paper GitHub projects | Implemented, with an explicit disclosure that "trend" is `stars / age_in_days` — a transparent proxy, because GitHub does not expose star history |

## 6. Key design decisions

**1. Two-stage funnel, not one big prompt.** Hundreds of candidates cannot be shown to a model
within any sane budget, and a keyword counter cannot judge quality. Stage one is deterministic
and cheap and decides *what deserves expensive attention* (≤90 candidates). Stage two is a
batched LLM jury that scores relevance, credibility and novelty. The expensive judgement is
spent on the tip of the funnel.

**2. Lineage anchors over keyword frequency.** Vocabulary hits are worth 1 point; a
word-boundary match on a lineage anchor is worth 2 — and any paper with a lineage hit is
force-included in the jury pool regardless of its deterministic score. Anchors also give the
report its most useful section: what a paper changes relative to the work the reader already
knows.

**3. A missing keyword never proves irrelevance.** The deterministic stage always forwards the
ten newest candidates even with zero profile signal. Cheap filters are allowed to be wrong in
the recall direction only.

**4. Allocation with quotas instead of top-N ranking.** A pure ranking collapses into whichever
area has the most submissions that day. Area quotas (with feedback multipliers) plus a
per-area minimum-presence rule keep the digest representative — but every diversity rule yields
to an explicit user rejection: a paper with a strongly negative feedback delta cannot be used to
fill a slot.

**5. Quality floor and no padding.** Below raw relevance 5.0, nothing is added once the minimum
count is met; on a quiet day the digest is short and the report states the shortfall. This is a
product decision: a digest padded to twelve is worse than a digest of six, because it destroys
the reader's trust in the ordering.

**6. Feedback as a versioned file, not fine-tuning or a hidden weight vector.** A strategy
patch can adjust area/sub-area weights, add positive and negative patterns with weights and
reasons, extend watch lists, add durable principles, and record per-paper verdicts. State is
plain JSON plus a Markdown mirror plus an append-only feedback log — readable, hand-editable,
revertible, portable between machines, and never a source-code edit.

**7. Honesty as an architectural property.** Evidence levels, `【推断】` prefixes, "文中未提供"
instead of guesses, degraded notes with confidence "低", and a transparency appendix listing
every failure. A failed model call produces a *labelled* failure, never a plausible-looking
fabrication. An empty harvest or empty selection aborts the run rather than writing an empty
digest.

**8. Degrade, do not fail.** Network and budget failures are expected, so the pipeline has a
documented ladder (shorter full text → skip code → skip trends → metadata-only) and records
which rungs it used. arXiv ingestion itself has three channels (Atom API → RSS → monthly
listing) with caching and a politeness delay; a `429` stops that category immediately instead of
retrying into the rate limiter.

**9. Zero runtime dependencies.** Everything is standard library (`urllib`, `xml.etree`,
`concurrent.futures`, `subprocess`, `dataclasses`). The `openai` SDK and `pypdf` are optional
extras. For a personal daily tool that must still run in three years, dependency rot is the
dominant long-term risk; the cost is some hand-written parsing.

## 7. What the brief asked for and what was built

| Asked for | Status | Notes |
|---|---|---|
| `work`: 10–15 papers from the last 2–3 days | Built | Window is configurable 1–7 days; defaults to 3 |
| Chinese Markdown named `yy-mm-dd` | Built | `reports/YY-MM-DD.md`, ~1,600 lines for 12 papers |
| Architecture, prior-work links, insight, innovations, evaluation, code, why-read | Built | Plus limitations, a time-boxed reading plan and an evidence level per paper |
| Use the repository when the paper is open source | Built, bounded | Repo discovery + README, file-tree overview and 3 recent commit subjects; GitHub API budget is disclosed in the report |
| `feedback`: ask the reader, then adapt selection | Built | 5 guided questions, or one-shot text / `--file`; compiled into a versioned strategy patch with clamped weights |
| Rising non-paper GitHub projects (optional) | Built with a caveat | `stars/day` proxy, spam-filtered, model-judged, disclosed as a proxy |
| Quiet execution, ≤2 concurrency, <1h | Built | See §5 |
| "Carefully consider the initial selection strategy" | Built | Deterministic screen + LLM jury + portfolio allocation; see §6 |

## 8. Open questions

- **Reading-queue state.** Feedback currently conflates "this was a bad pick" with "I never got
  to it". Tracking read/skipped/worth-citing would sharpen the signal considerably.
- **Multi-day memory.** The daily observation is reset each morning. A weekly roll-up that
  tracks how a route evolves would serve the reader's stated goal of building insight, not just
  a queue.
- **Beyond lexical lineage.** Citation-graph or embedding-based lineage detection would catch
  work that is on the reader's map without naming an anchor.
- **Calibrating the jury.** Nothing currently measures whether the model's scores correlate with
  the reader's actual satisfaction; the feedback log contains the data to do it.
