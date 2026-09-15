"""The agent's memory: a versioned, human-editable strategy evolved from feedback.

Design goal (from the project brief): feedback must not merely add
keywords, it must change *future selection strategy* in a way the user can read,
correct, and carry to another machine. So state lives in JSON (machine-usable)
and is mirrored to Markdown (human-readable, reviewed like a config file).

Nothing here edits source code: the pipeline reads the strategy at every stage.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .profile import AREA_BY_KEY, SUBAREA_BY_KEY

SCHEMA_VERSION = 1

DEFAULT_STRATEGY: dict[str, Any] = {
    "version": 1,
    "updated": "",
    "area_weights": {key: 1.0 for key in AREA_BY_KEY},
    "subarea_weights": {},
    "positive_patterns": [],
    "negative_patterns": [],
    "watch": {"labs": [], "authors": [], "projects": []},
    "principles": [],
    "paper_verdicts": [],
    "history": [],
}

PATCH_SCHEMA_NOTE = """返回一个合法 JSON 对象，键如下：
{
  "area_weight_deltas": {"3d_generation": 0.1},          // 领域权重增量，可正可负，范围 [-0.5, 0.5]
  "subarea_weight_deltas": {"3d_generation/native_latent": 0.2},
  "add_positive_patterns": [{"pattern": "flow matching", "weight": 2.0, "reason": "用户偏好"}],
  "add_negative_patterns": [{"pattern": "benchmark survey", "weight": 3.0, "reason": "用户不感兴趣"}],
  "watch": {"labs": ["Tencent Hunyuan"], "authors": [], "projects": ["Articraft"]},
  "principles_add": ["优先选有开源代码与消融实验的工作"],
  "principles_remove": ["……"],
  "verdict_paper_ids": [{"arxiv_id": "2609.12345", "verdict": "bad", "reason": "只是换数据集"}],
  "notes": "中文总结这次反馈带来的策略变化"
}
只输出 JSON，不要包裹代码块。未知信息留空，不要编造 arxiv_id。"""


class StrategyStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data: dict[str, Any] = json.loads(json.dumps(DEFAULT_STRATEGY))
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    for key, value in loaded.items():
                        self.data[key] = value
            except (OSError, json.JSONDecodeError):
                pass  # a corrupt file must not brick the daily run
        for key, default in DEFAULT_STRATEGY.items():
            self.data.setdefault(key, default)

    # ------------------------------------------------------------------ io --
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        md = self.path.with_suffix(".md")
        md.write_text(self.render_markdown(), encoding="utf-8")

    # -------------------------------------------------------------- prompt --
    def context_block(self) -> str:
        data = self.data
        parts: list[str] = ["# 当前选取策略（来自用户反馈，逐轮进化）"]
        weights = {k: round(v, 2) for k, v in data.get("area_weights", {}).items() if abs(v - 1.0) > 1e-6}
        if weights:
            parts.append("## 领域权重调整")
            for key, value in weights.items():
                label = AREA_BY_KEY[key].name if key in AREA_BY_KEY else key
                parts.append(f"- {label}：×{value}")
        sub = {k: round(v, 2) for k, v in data.get("subarea_weights", {}).items() if abs(v - 1.0) > 1e-6}
        if sub:
            parts.append("## 子方向权重调整")
            for key, value in sub.items():
                sub_obj = SUBAREA_BY_KEY.get(key)
                label = sub_obj.name if sub_obj else key
                parts.append(f"- {label}：×{value}")
        for label, key in (("偏好信号（命中则加分）", "positive_patterns"), ("排斥信号（命中则扣分）", "negative_patterns")):
            items = data.get(key) or []
            if items:
                parts.append(f"## {label}")
                for item in items:
                    if isinstance(item, dict):
                        parts.append(f"- {item.get('pattern', '')}（权重 {item.get('weight', 1.0)}）：{item.get('reason', '')}")
                    else:
                        parts.append(f"- {item}")
        watch = data.get("watch") or {}
        if any(watch.get(k) for k in ("labs", "authors", "projects")):
            parts.append("## 关注名单")
            for kind in ("labs", "authors", "projects"):
                values = watch.get(kind) or []
                if values:
                    parts.append(f"- {kind}：" + "、".join(str(v) for v in values))
        principles = data.get("principles") or []
        if principles:
            parts.append("## 长期原则")
            for item in principles:
                parts.append(f"- {item}")
        verdicts = (data.get("paper_verdicts") or [])[-12:]
        if verdicts:
            parts.append("## 近期论文评价（避免重犯同类错误）")
            for item in verdicts:
                parts.append(f"- [{item.get('verdict', '?')}] {item.get('title', item.get('arxiv_id', ''))}：{item.get('reason', '')}")
        notes = self._latest_note()
        if notes:
            parts.append(f"## 最近一次反馈总结\n{notes}")
        if len(parts) == 1:
            parts.append("（尚无反馈，使用默认领域优先级。）")
        return "\n".join(parts)

    def _latest_note(self) -> str:
        history = self.data.get("history") or []
        for item in reversed(history):
            if isinstance(item, dict) and item.get("summary"):
                return str(item["summary"])
        return ""

    # -------------------------------------------------------------- scoring --
    def paper_adjustment(self, text_lower: str, area_key: str = "", subarea_key: str = "") -> tuple[float, list[str]]:
        """Deterministic effect of past feedback, independent of any model call."""
        delta = 0.0
        reasons: list[str] = []
        for item in self.data.get("positive_patterns") or []:
            pattern = item.get("pattern", "") if isinstance(item, dict) else str(item)
            weight = float(item.get("weight", 1.0)) if isinstance(item, dict) else 1.0
            if pattern and pattern.lower() in text_lower:
                delta += weight
                reasons.append(f"+{weight} 命中偏好「{pattern}」")
        for item in self.data.get("negative_patterns") or []:
            pattern = item.get("pattern", "") if isinstance(item, dict) else str(item)
            weight = float(item.get("weight", 1.0)) if isinstance(item, dict) else 1.0
            if pattern and pattern.lower() in text_lower:
                delta -= weight
                reasons.append(f"-{weight} 命中排斥「{pattern}」")
        watch = self.data.get("watch") or {}
        for kind in ("labs", "authors", "projects"):
            for value in watch.get(kind) or []:
                token = str(value).lower()
                if token and token in text_lower:
                    delta += 1.5
                    reasons.append(f"+1.5 命中关注{kind}「{value}」")
        if area_key:
            multiplier = float((self.data.get("area_weights") or {}).get(area_key, 1.0))
            if abs(multiplier - 1.0) > 1e-6:
                reasons.append(f"领域权重 ×{multiplier:.2f}")
        if subarea_key:
            multiplier = float((self.data.get("subarea_weights") or {}).get(subarea_key, 1.0))
            if abs(multiplier - 1.0) > 1e-6:
                reasons.append(f"子方向权重 ×{multiplier:.2f}")
        return delta, reasons

    def area_multiplier(self, area_key: str) -> float:
        return float((self.data.get("area_weights") or {}).get(area_key, 1.0))

    def subarea_multiplier(self, subarea_key: str) -> float:
        return float((self.data.get("subarea_weights") or {}).get(subarea_key, 1.0))

    # --------------------------------------------------------------- mutate --
    def apply_patch(self, patch: dict[str, Any], raw_feedback: str = "") -> dict[str, Any]:
        applied: dict[str, Any] = {"areas": {}, "subareas": {}, "positive": [], "negative": [], "watch": {}, "principles": [], "verdicts": []}
        for key, delta in (patch.get("area_weight_deltas") or {}).items():
            if key not in AREA_BY_KEY:
                continue
            delta = max(-0.6, min(0.6, float(delta)))
            new_value = max(0.2, min(3.0, float(self.data["area_weights"].get(key, 1.0)) + delta))
            self.data["area_weights"][key] = round(new_value, 3)
            applied["areas"][key] = round(new_value, 3)
        for key, delta in (patch.get("subarea_weight_deltas") or {}).items():
            if key not in SUBAREA_BY_KEY:
                continue
            delta = max(-0.6, min(0.6, float(delta)))
            new_value = max(0.2, min(3.0, float(self.data["subarea_weights"].get(key, 1.0)) + delta))
            self.data["subarea_weights"][key] = round(new_value, 3)
            applied["subareas"][key] = round(new_value, 3)
        for kind in ("positive", "negative"):
            target = "positive_patterns" if kind == "positive" else "negative_patterns"
            existing = {str(p.get("pattern", "")).lower() for p in self.data[target] if isinstance(p, dict)}
            for item in patch.get(f"add_{kind}_patterns") or []:
                if not isinstance(item, dict) or not item.get("pattern"):
                    continue
                pattern = str(item["pattern"]).strip()
                if pattern.lower() in existing:
                    continue
                entry = {"pattern": pattern, "weight": round(max(0.2, min(6.0, float(item.get("weight", 1.0)))), 2), "reason": str(item.get("reason", "来自反馈"))[:200]}
                self.data[target].append(entry)
                applied[kind].append(entry)
                existing.add(pattern.lower())
        watch_patch = patch.get("watch") or {}
        for kind in ("labs", "authors", "projects"):
            current = set(self.data["watch"].get(kind) or [])
            for value in watch_patch.get(kind) or []:
                text = str(value).strip()
                if text and text not in current:
                    current.add(text)
                    applied["watch"].setdefault(kind, []).append(text)
            self.data["watch"][kind] = sorted(current)[:40]
        for principle in patch.get("principles_add") or []:
            text = str(principle).strip()
            if text and text not in self.data["principles"]:
                self.data["principles"].append(text)
                applied["principles"].append(text)
        removals = {str(p).strip() for p in patch.get("principles_remove") or []}
        if removals:
            self.data["principles"] = [p for p in self.data["principles"] if p not in removals]
        for verdict in patch.get("verdict_paper_ids") or []:
            if not isinstance(verdict, dict) or not verdict.get("arxiv_id"):
                continue
            entry = {
                "arxiv_id": str(verdict["arxiv_id"]),
                "title": str(verdict.get("title", ""))[:200],
                "verdict": str(verdict.get("verdict", "bad"))[:16],
                "reason": str(verdict.get("reason", ""))[:300],
                "date": datetime.now(timezone.utc).date().isoformat(),
            }
            self.data["paper_verdicts"].append(entry)
            applied["verdicts"].append(entry)
        self.data["paper_verdicts"] = self.data["paper_verdicts"][-200:]
        self.data["version"] = int(self.data.get("version", 1)) + 1
        summary = str(patch.get("notes") or "").strip() or "（未提供总结）"
        self.data["history"].append({
            "version": self.data["version"],
            "date": datetime.now(timezone.utc).date().isoformat(),
            "summary": summary[:600],
            "feedback_excerpt": " ".join(raw_feedback.split())[:600],
        })
        self.data["history"] = self.data["history"][-50:]
        self.save()
        return applied

    def record_verdict_by_title(self, title_hint: str, verdict: str, reason: str, arxiv_id: str = "") -> None:
        self.data["paper_verdicts"].append({
            "arxiv_id": arxiv_id,
            "title": title_hint[:200],
            "verdict": verdict[:16],
            "reason": reason[:300],
            "date": datetime.now(timezone.utc).date().isoformat(),
        })

    # ----------------------------------------------------------- rendering --
    def render_markdown(self) -> str:
        data = self.data
        lines = [
            "# 选文策略（Agent 的可读记忆）",
            "",
            f"- 版本：{data.get('version', 1)}",
            f"- 更新时间：{data.get('updated', 'n/a')}",
            "",
            "> 本文件由 `feedback` 命令自动生成，也可以手工编辑；下次 `work` 会读到。改 JSON 之外的说明文字不会被解析。",
            "",
            "## 领域权重",
            "| 领域 | 权重 |",
            "|---|---:|",
        ]
        for key, area in AREA_BY_KEY.items():
            lines.append(f"| {area.name} `{key}` | ×{(data.get('area_weights') or {}).get(key, 1.0):.2f} |")
        lines += ["", "## 子方向权重"]
        sub_items = {k: v for k, v in (data.get("subarea_weights") or {}).items() if abs(v - 1.0) > 1e-6}
        if sub_items:
            for key, value in sub_items.items():
                sub = SUBAREA_BY_KEY.get(key)
                lines.append(f"- `{key}`（{sub.name if sub else '未知'}）：×{value:.2f}")
        else:
            lines.append("- 无调整")
        for label, key in (("偏好信号", "positive_patterns"), ("排斥信号", "negative_patterns")):
            lines += ["", f"## {label}"]
            items = data.get(key) or []
            if items:
                for item in items:
                    if isinstance(item, dict):
                        lines.append(f"- `{item.get('pattern', '')}` 权重 {item.get('weight', 1.0)} — {item.get('reason', '')}")
                    else:
                        lines.append(f"- {item}")
            else:
                lines.append("- 无")
        lines += ["", "## 关注名单"]
        watch = data.get("watch") or {}
        wrote = False
        for kind in ("labs", "authors", "projects"):
            values = watch.get(kind) or []
            if values:
                lines.append(f"- {kind}：" + "、".join(str(v) for v in values))
                wrote = True
        if not wrote:
            lines.append("- 无")
        lines += ["", "## 长期原则"]
        principles = data.get("principles") or []
        lines += [f"- {p}" for p in principles] if principles else ["- 无"]
        lines += ["", "## 近期论文评价"]
        verdicts = (data.get("paper_verdicts") or [])[-20:]
        lines += [f"- [{v.get('verdict')}] {v.get('title') or v.get('arxiv_id')} — {v.get('reason', '')}" for v in verdicts] if verdicts else ["- 无"]
        lines += ["", "## 变更历史"]
        history = (data.get("history") or [])[-20:]
        lines += [f"- v{h.get('version')}（{h.get('date')}）：{h.get('summary', '')}" for h in history] if history else ["- 无"]
        lines.append("")
        return "\n".join(lines)


FEEDBACK_LINE = re.compile(r"^\s*([+-])\s*(.+?)\s*$")


def deterministic_patch(text: str) -> dict[str, Any]:
    """Fallback extraction when no model is available: +/- keyword lines."""
    positives, negatives, notes = [], [], []
    for raw in text.splitlines():
        match = FEEDBACK_LINE.match(raw)
        if match:
            term = match.group(2).strip()
            if not term:
                continue
            if match.group(1) == "+":
                positives.append({"pattern": term, "weight": 2.0, "reason": "用户明确偏好"})
            else:
                negatives.append({"pattern": term, "weight": 3.0, "reason": "用户明确排斥"})
        elif raw.strip():
            notes.append(raw.strip())
    return {
        "add_positive_patterns": positives,
        "add_negative_patterns": negatives,
        "notes": "；".join(notes[-3:]) or "（离线解析）",
    }
