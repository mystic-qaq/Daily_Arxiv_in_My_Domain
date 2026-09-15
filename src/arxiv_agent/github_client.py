"""GitHub support: attach code to papers, and surface rising non-paper projects.

Both features are best-effort. GitHub hides historical star counts from us, so
every "trend" number here is a transparent stars-per-day proxy computed from
``created_at`` - never presented as a measurement of real momentum.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .models import Paper, TrendingProject

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
USER_AGENT = "domain-specific-daily-arxiv/0.3"
GITHUB_URL_RE = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
# Ignore matches that are clearly not repositories.
NON_REPO_PATHS = {"topics", "orgs", "sponsors", "features", "collections", "trending", "settings", "about", "marketplace"}
SPAM_HINTS = ("interview", "leetcode", "course", "tutorial", "cheatsheet", "awesome-list", "roadmap", "作业", "学习笔记")


class GitHubClient:
    """Best-effort client with an explicit call budget.

    Unauthenticated GitHub allows ~60 API requests/hour, and paper screening can
    consume that quickly. The budget makes the degradation predictable instead of
    random 403s in the middle of a run.
    """

    def __init__(self, timeout: int = 15, api_budget: int | None = None, search_budget: int | None = None):
        self.timeout = timeout
        token = os.getenv("GITHUB_TOKEN")
        # Unauthenticated GitHub allows ~60 core requests/hour but **only 10
        # search requests/hour** - and both trending and repo discovery are
        # search-heavy. Two budgets make that limit explicit and actionable
        # instead of an unpredictable 403 halfway through a run.
        self.api_budget = api_budget if api_budget is not None else (45 if token else 30)
        self.search_budget = search_budget if search_budget is not None else (25 if token else 6)
        self.calls = 0
        self.search_calls = 0
        self.log: list[str] = []
        self._last_call = 0.0

    # ------------------------------------------------------------------ http --
    def _headers(self, accept: str = "application/vnd.github+json") -> dict[str, str]:
        headers = {"Accept": accept, "User-Agent": USER_AGENT}
        token = os.getenv("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def api(self, path: str, search: bool = False) -> dict | None:
        budget = self.search_budget if search else self.api_budget
        used = self.search_calls if search else self.calls
        if used >= budget:
            self.log.append(f"GitHub {'search' if search else 'core'} budget exhausted before {path}")
            return None
        wait = time.monotonic() - self._last_call
        if wait < 1.0:
            time.sleep(1.0 - wait)
        self._last_call = time.monotonic()
        if search:
            self.search_calls += 1
        else:
            self.calls += 1
        try:
            req = urllib.request.Request(API + path, headers=self._headers())
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                # Rate limited (or the budget was optimistic): stop spending time.
                if search:
                    self.search_budget = self.search_calls
                else:
                    self.api_budget = self.calls
            self.log.append(f"GitHub {path} -> HTTP {exc.code}")
            return None
        except Exception as exc:
            self.log.append(f"GitHub {path} failed: {exc}")
            return None

    def raw(self, url: str, limit: int = 6000) -> str:
        """Raw content is fetched without touching the API rate limit."""
        try:
            req = urllib.request.Request(url, headers=self._headers("text/plain"))
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                return response.read().decode("utf-8", errors="replace")[:limit]
        except Exception:
            return ""

    # ------------------------------------------------------- paper -> repo --
    def find_repo_candidate(self, paper: Paper) -> str | None:
        """Cheapest reliable source first: the URL printed inside the paper."""
        haystacks = [paper.full_text or "", paper.abstract, paper.comment]
        for text in haystacks:
            for owner, repo in GITHUB_URL_RE.findall(text):
                repo = repo.rstrip(".,);]")
                owner = owner.strip()
                if owner.lower() in NON_REPO_PATHS or repo.lower() in NON_REPO_PATHS:
                    continue
                if repo.endswith((".md", ".png", ".jpg")):
                    continue
                candidate = f"{owner}/{repo}"
                meta = self.api(f"/repos/{candidate}")
                if isinstance(meta, dict) and meta.get("html_url"):
                    return candidate
        return None

    def search_repo(self, paper: Paper) -> str | None:
        """Fallback: search by title when the paper does not print its URL."""
        words = [w for w in re.findall(r"[A-Za-z0-9]{4,}", paper.title.lower())]
        stop = {"with", "from", "that", "this", "your", "ours", "towards", "using", "into", "when", "their"}
        keywords = [w for w in words if w not in stop][:6]
        if len(keywords) < 2:
            return None
        query = " ".join(keywords)
        data = self.api("/search/repositories?" + urllib.parse.urlencode({"q": query, "sort": "stars", "order": "desc", "per_page": "3"}), search=True)
        items = (data or {}).get("items") or []
        title_tokens = set(re.findall(r"[a-z0-9]{4,}", paper.title.lower()))
        for item in items:
            name = str(item.get("full_name", ""))
            haystack = f"{name} {item.get('description') or ''}".lower()
            overlap = len(title_tokens & set(re.findall(r"[a-z0-9]{4,}", haystack)))
            if overlap >= 2 or self._title_in_project(title_tokens, name):
                return name
        return None

    @staticmethod
    def _title_in_project(title_tokens: set[str], full_name: str) -> bool:
        repo_name = full_name.split("/")[-1].lower()
        joined = re.sub(r"[^a-z0-9]", "", repo_name)
        for token in title_tokens:
            if len(token) >= 5 and token in joined:
                return True
        return False

    def repo_facts(self, full_name: str) -> dict:
        """Assemble the material the analyst needs to talk about the code."""
        meta = self.api(f"/repos/{full_name}") or {}
        if not meta:
            return {}
        facts = {
            "url": meta.get("html_url", f"https://github.com/{full_name}"),
            "full_name": meta.get("full_name", full_name),
            "stars": int(meta.get("stargazers_count") or 0),
            "language": meta.get("language") or "",
            "license_name": (meta.get("license") or {}).get("spdx_id") or (meta.get("license") or {}).get("name") or "",
            "description": (meta.get("description") or "")[:300],
            "topics": (meta.get("topics") or [])[:10],
            "created_at": meta.get("created_at", ""),
            "pushed_at": meta.get("pushed_at", ""),
            "open_issues": int(meta.get("open_issues_count") or 0),
        }
        default_branch = meta.get("default_branch") or "main"
        readme = self.raw(f"{RAW}/{full_name}/{default_branch}/README.md", limit=5000)
        if not readme:
            readme = self.raw(f"{RAW}/{full_name}/{default_branch}/README.MD", limit=5000)
        facts["readme_excerpt"] = " ".join(readme.split())[:3500]
        # Repo metadata + README is the minimum viable "here is the code" package;
        # the tree and recent commits are spent only while budget headroom lasts.
        tree = None
        if self.calls < self.api_budget - 4:
            tree = self.api(f"/repos/{full_name}/git/trees/{default_branch}?recursive=1")
        if isinstance(tree, dict) and tree.get("tree"):
            paths = [item.get("path", "") for item in tree["tree"] if item.get("type") == "blob"]
            top: dict[str, int] = {}
            for path in paths:
                first = path.split("/")[0] if "/" in path else "(root)"
                top[first] = top.get(first, 0) + 1
            ranked = sorted(top.items(), key=lambda kv: -kv[1])[:14]
            facts["tree_excerpt"] = "; ".join(f"{name}({count})" for name, count in ranked)
        if self.calls < self.api_budget - 2:
            commits = self.api(f"/repos/{full_name}/commits?per_page=3")
            if isinstance(commits, list):
                facts["recent_commits"] = [str(item.get("commit", {}).get("message", "")).split("\n")[0][:120] for item in commits]
        facts["code_chars"] = len(facts["readme_excerpt"]) + len(facts.get("tree_excerpt", ""))
        return facts

    def attach_repo(self, paper: Paper) -> dict | None:
        if paper.repo is not None:
            return paper.repo
        name = self.find_repo_candidate(paper) or self.search_repo(paper)
        if not name:
            paper.repo = {}
            return None
        facts = self.repo_facts(name)
        paper.repo = facts or {}
        return paper.repo or None

    # ------------------------------------------------------------- trending --
    def trending(self, queries: dict[str, list[str]], window_days: int = 7, limit_per_query: int = 10) -> list[dict]:
        """One search per area (terms OR-ed together) - the search quota is small."""
        since = (datetime.now(timezone.utc) - timedelta(days=window_days)).date().isoformat()
        seen: dict[str, dict] = {}
        for area, terms in queries.items():
            if self.search_calls >= self.search_budget:
                self.log.append("GitHub trending stopped: search quota nearly exhausted")
                break
            expression = " OR ".join(f'"{term}"' for term in terms[:3])
            query = urllib.parse.urlencode({"q": f"{expression} created:>{since}", "sort": "stars", "order": "desc", "per_page": str(limit_per_query)})
            data = self.api(f"/search/repositories?{query}", search=True)
            for item in (data or {}).get("items") or []:
                item["_area"] = area
                seen.setdefault(str(item.get("full_name")), item)
        projects: list[dict] = []
        now = datetime.now(timezone.utc)
        for item in seen.values():
            created = _parse_dt(str(item.get("created_at", "")))
            if created is None:
                continue
            age = max((now - created).total_seconds() / 86400, 1.0)
            if age > window_days + 1:
                continue
            stars = int(item.get("stargazers_count") or 0)
            if stars < 3:  # below this, stars/day is noise
                continue
            description = str(item.get("description") or "")
            if _is_spam(item, description):
                continue
            projects.append({
                "name": str(item.get("full_name")),
                "url": str(item.get("html_url")),
                "description": description[:240],
                "stars": stars,
                "age_days": round(age, 1),
                "stars_per_day": round(stars / age, 2),
                "area": str(item.get("_area", "")),
                "language": str(item.get("language") or ""),
                "pushed_at": str(item.get("pushed_at", "")),
            })
        projects.sort(key=lambda p: (p["stars_per_day"], p["stars"]), reverse=True)
        return projects[:20]


TRENDING_QUERIES: dict[str, list[str]] = {
    "3d_generation": ["3d-generation", "text-to-3d", "3d asset generation"],
    "3d_reconstruction": ["3d-reconstruction", "gaussian-splatting", "nerf"],
    "video_generation": ["video-generation", "text-to-video", "video diffusion"],
    "embodied_ai": ["embodied-ai", "vision-language-action", "robot policy"],
}


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_spam(item: dict, description: str) -> bool:
    lowered = (str(item.get("full_name", "")) + " " + description).lower()
    return any(hint in lowered for hint in SPAM_HINTS)


def to_trending_project(raw: dict, why: str = "") -> TrendingProject:
    return TrendingProject(
        name=raw.get("name", ""),
        url=raw.get("url", ""),
        description=raw.get("description", ""),
        stars=int(raw.get("stars", 0)),
        age_days=float(raw.get("age_days", 1.0)),
        stars_per_day=float(raw.get("stars_per_day", 0.0)),
        area=raw.get("area", ""),
        why=why,
        language=raw.get("language", ""),
        pushed_at=raw.get("pushed_at", ""),
    )


def attach_repo_to_paper(paper: Paper, client: GitHubClient) -> dict | None:
    return client.attach_repo(paper)
