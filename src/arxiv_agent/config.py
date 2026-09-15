from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .profile import default_categories

MAX_CONCURRENCY = 2  # hard cap required by the user; never raise this silently


def load_env_file(path: Path | str = ".env", override: bool = False) -> int:
    """Load ``KEY=VALUE`` lines from a ``.env`` file into ``os.environ``.

    Real environment variables win unless ``override`` is set, so a shell export
    or a CI secret is never shadowed by a file that happens to sit in the working
    directory. Returns how many variables were actually set. Kept in the standard
    library on purpose: the project has no runtime dependencies.
    """
    env_path = Path(path)
    if not env_path.exists():
        return 0
    applied = 0
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.lower().startswith("export "):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key or (key in os.environ and not override):
            continue
        os.environ[key] = value
        applied += 1
    return applied


@dataclass
class Settings:
    days: int = 3
    min_papers: int = 10
    max_papers: int = 15
    target_papers: int = 12

    # Logical model name; the provider is resolved from it (see llm.resolve_provider).
    # The default is the most widely available route: any OpenAI-compatible
    # endpoint. Point it at something else with --model / ARXIV_AGENT_MODEL.
    model: str = "gpt-4.1-mini"
    provider: str = ""  # auto | openai | codebuddy | offline
    temperature: float = 0.2

    output_dir: Path = Path("reports")
    state_dir: Path = Path(".arxiv-agent")
    cache_dir: Path = Path(".arxiv-agent/cache")

    categories: list[str] = field(default_factory=default_categories)
    max_candidates: int = 600  # harvested ceiling before deterministic screening
    triage_pool: int = 90  # how many candidates reach the LLM triage stage
    triage_batch: int = 12
    fulltext_chars: int = 26000  # deep-reading budget; bigger = slower non-linearly
    max_concurrency: int = 1
    time_budget_min: int = 45  # the user asked for < 1h end to end; enforced per phase
    offline: bool = False
    skip_code: bool = False
    skip_trending: bool = False
    request_delay: float = 3.0  # arXiv asks for ~3s between requests

    @property
    def strategy_file(self) -> Path:
        return self.state_dir / "strategy.json"

    @property
    def strategy_md(self) -> Path:
        return self.state_dir / "strategy.md"

    @property
    def feedback_log(self) -> Path:
        return self.state_dir / "feedback-log.jsonl"

    @classmethod
    def from_env(cls, **overrides: object) -> Settings:
        values: dict[str, object] = {}
        env_map = {
            "ARXIV_AGENT_MODEL": "model",
            "ARXIV_AGENT_PROVIDER": "provider",
            "ARXIV_AGENT_OUTPUT_DIR": "output_dir",
            "ARXIV_AGENT_STATE_DIR": "state_dir",
            "ARXIV_AGENT_CACHE_DIR": "cache_dir",
        }
        for key, attr in env_map.items():
            if os.getenv(key):
                value = os.environ[key]
                values[attr] = Path(value) if attr.endswith(("dir", "file")) else value
        # Explicit mapping, not a derived name: the flag is ARXIV_AGENT_TIME_BUDGET
        # while the field is time_budget_min, and deriving it crashed the CLI.
        for key, attr in {
            "ARXIV_AGENT_DAYS": "days",
            "ARXIV_AGENT_MAX_PAPERS": "max_papers",
            "ARXIV_AGENT_MIN_PAPERS": "min_papers",
            "ARXIV_AGENT_MAX_CONCURRENCY": "max_concurrency",
            "ARXIV_AGENT_TIME_BUDGET": "time_budget_min",
        }.items():
            raw = os.getenv(key)
            if raw:
                values[attr] = int(raw)
        values.update({k: v for k, v in overrides.items() if v is not None})
        result = cls(**values)
        result.clamp()
        return result

    @classmethod
    def load_json(cls, path: Path) -> Settings:
        if not path or not Path(path).exists():
            return cls.from_env()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for key in ("output_dir", "state_dir", "cache_dir"):
            if key in data:
                data[key] = Path(data[key])
        return cls.from_env(**data)

    def clamp(self) -> None:
        # The user's two hard limits: concurrency <= 2 and a 10-15 paper digest.
        self.max_concurrency = max(1, min(MAX_CONCURRENCY, int(self.max_concurrency)))
        self.max_papers = max(1, min(15, int(self.max_papers)))
        # An explicitly smaller --target must win over the default floor, so the
        # floor follows the target down instead of silently overriding it.
        self.target_papers = min(self.max_papers, max(1, int(self.target_papers)))
        self.min_papers = max(1, min(self.max_papers, int(self.min_papers), self.target_papers))
        self.days = max(1, min(7, int(self.days)))
        self.triage_pool = max(self.target_papers, min(240, int(self.triage_pool)))
        self.time_budget_min = max(5, min(60, int(self.time_budget_min)))
