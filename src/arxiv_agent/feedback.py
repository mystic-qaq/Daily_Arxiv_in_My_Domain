"""The feedback loop: ask, understand, then rewrite tomorrow's strategy.

The user wanted feedback to change *future selection*, not just add keywords. So
the interaction does two things:

1. it asks structured questions (including which entries were bad and why);
2. it lets a model translate that into strategy deltas - area/subarea weights,
   positive/negative patterns, watch lists, durable Chinese principles -
   which are versioned, printed back, and mirrored into readable Markdown.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

from .config import Settings
from .llm import GenOptions, LLMBackend
from .models import Paper
from .profile import AREA_BY_KEY, SUBAREA_BY_KEY, profile_brief
from .prompts import render_template
from .strategy import PATCH_SCHEMA_NOTE, StrategyStore, deterministic_patch

REPORT_ENTRY_RE = re.compile(r"^## (\d+)\. (.+)$")
ARXIV_LINE_RE = re.compile(r"\*\*arXiv\*\*：\[(\d+\.\d+)\]")

QUESTIONS = (
    ("dissatisfied", "哪些入选文章实际上让你不满意？可填编号/标题片段，多个用逗号分隔（直接回车跳过）"),
    ("dissatisfied_reason", "它们糟糕在哪里？（一句话；例如：只是换数据集 / 精度没意义 / 与我路线无关）"),
    ("liked", "哪些文章的思路最值得借鉴？编号 + 原因（直接回车跳过）"),
    ("weights", "想调整方向权重吗？例如 `+3d_generation -embodied_ai` 或 `+3d_generation/native_latent`（直接回车跳过）"),
    ("extra", "还有其他想让 Agent 记住的吗？（多行输入，空行后结束）"),
)

SYNTHESIS_SYSTEM = """你是选文策略的进化器。用户刚刚反馈了今天的 arXiv 精选质量，请把这些反馈**内化为可执行的选文策略变更**。

# 要求
- 优先采用显式信号：用户可能直接按 area/subarea key 调整权重，务必照做；可用的 key 见下方研究画像。
- 把用户的抱怨转成可判别的模式（pattern）：既可以是主题词，也可以是"水文特征"（如"只换数据集""没有消融""纯 benchmark"）。
- reason 必须写清为什么，便于未来的人工审阅和回滚。
- 不要把单次偏好当成永久真理：权重增减控制在 ±0.3，权重正负不要超过合理范围。
- 关注名单 labs/authors/projects 只在用户明确点名时使用；不要臆测人名或仓库名。
- 若用户指定了不满意文章的编号，请在 verdict_paper_ids 里带上对应 arxiv_id（只能来自给定材料）。

{profile}

{PATCH_SCHEMA}
"""


def resolve_reference_date() -> date:
    return date.today()


def load_report_entries(reports_dir: Path) -> list[dict[str, str]]:
    """Parse the most recent digest so the user can refer to entries by number."""
    if not reports_dir.exists():
        return []
    candidates = sorted(reports_dir.glob("*.md"), reverse=True)
    if not candidates:
        return []
    lines = candidates[0].read_text(encoding="utf-8").splitlines()
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in lines:
        match = REPORT_ENTRY_RE.match(line)
        if match:
            current = {"index": match.group(1), "title": match.group(2).strip(), "arxiv_id": ""}
            entries.append(current)
            continue
        if current and not current["arxiv_id"]:
            found = ARXIV_LINE_RE.search(line)
            if found:
                current["arxiv_id"] = found.group(1)
    return entries


def _resolve_titles(text: str, entries: list[dict[str, str]]) -> str:
    """Turn "3, 7" into the actual titles so the synthesis has real anchors."""
    tokens = [t.strip() for t in re.split(r"[,，、\s]+", text) if t.strip()]
    resolved: list[str] = []
    by_index = {e["index"]: e for e in entries}
    for token in tokens:
        entry = by_index.get(token)
        if entry:
            resolved.append(f"#{entry['index']} {entry['title']}（{entry['arxiv_id']}）")
        else:
            matched = [e for e in entries if token.lower() in e["title"].lower()]
            if matched:
                resolved.extend(f"#{e['index']} {e['title']}（{e['arxiv_id']}）" for e in matched[:2])
            else:
                resolved.append(token)
    return "；".join(resolved)


def collect_interactive(entries: list[dict[str, str]]) -> str:
    print("—— 反馈模式：回答几个问题（直接回车跳过） ——\n")
    answers: dict[str, str] = {}
    for key, question in QUESTIONS:
        print(f"{question}\n> ", end="", flush=True)
        if key == "extra":
            lines: list[str] = []
            while True:
                line = sys.stdin.readline()
                if not line or line.strip() == "":
                    break
                lines.append(line.rstrip("\n"))
            answers[key] = "\n".join(lines)
        else:
            answers[key] = sys.stdin.readline().rstrip("\n")
    return compose_feedback_text(answers, entries)


def compose_feedback_text(answers: dict[str, str], entries: list[dict[str, str]]) -> str:
    parts: list[str] = []
    dissatisfied = _resolve_titles(answers.get("dissatisfied", ""), entries)
    if dissatisfied.strip():
        parts.append(f"不满意的文章：{dissatisfied}")
        reason = answers.get("dissatisfied_reason", "").strip()
        if reason:
            parts.append(f"不满意的原因：{reason}")
    liked = _resolve_titles(answers.get("liked", ""), entries)
    if liked.strip():
        parts.append(f"值得借鉴的文章：{liked}")
    weights = answers.get("weights", "").strip()
    if weights:
        parts.append(f"希望调整的方向权重：{weights}")
    extra = answers.get("extra", "").strip()
    if extra:
        parts.append("其他要求：\n" + extra)
    return "\n".join(parts)


def synthesize_patch(raw_feedback: str, strategy: StrategyStore, backend: LLMBackend, entries: list[dict[str, str]]) -> dict[str, Any]:
    system = render_template(SYNTHESIS_SYSTEM, profile=profile_brief(style="analyse"), PATCH_SCHEMA=PATCH_SCHEMA_NOTE)
    user = (
        f"当前策略（JSON）：\n{json.dumps(strategy.data, ensure_ascii=False)}\n\n"
        f"今日报告条目：\n{json.dumps(entries, ensure_ascii=False)}\n\n"
        f"用户反馈（原文）：\n{raw_feedback}\n\n"
        "请只输出策略变更 JSON。"
    )
    patch = backend.complete_json(system, user, GenOptions(max_output_tokens=1600, temperature=0.2))
    if not isinstance(patch, dict):
        raise ValueError("策略合成返回了非 JSON 结构")
    return _apply_weight_shorthand(raw_feedback, patch)


# "+3d_generation -embodied_ai" style shorthand, so explicit intent always wins
# even if the model misses it.
SHORTHAND_RE = re.compile(r"([+-])\s*([A-Za-z0-9_./-]+)")


def _apply_weight_shorthand(raw_feedback: str, patch: dict[str, Any]) -> dict[str, Any]:
    patch.setdefault("area_weight_deltas", {})
    patch.setdefault("subarea_weight_deltas", {})
    for line in raw_feedback.splitlines():
        if "方向权重" not in line:
            continue
        for sign, token in SHORTHAND_RE.findall(line):
            token = token.strip().strip("，,")
            delta = 0.15 if sign == "+" else -0.15
            if token in AREA_BY_KEY:
                patch["area_weight_deltas"][token] = patch["area_weight_deltas"].get(token, 0.0) + delta
            elif token in SUBAREA_BY_KEY:
                patch["subarea_weight_deltas"][token] = patch["subarea_weight_deltas"].get(token, 0.0) + delta
    return patch


def run_feedback(settings: Settings, backend: LLMBackend, raw_text: str) -> dict[str, Any]:
    store = StrategyStore(settings.strategy_file)
    entries = load_report_entries(settings.output_dir)
    try:
        patch = synthesize_patch(raw_text, store, backend, entries)
        mode = "模型合成"
    except Exception as exc:
        patch = deterministic_patch(raw_text)
        mode = f"离线关键词解析（模型不可用：{type(exc).__name__}）"
    applied = store.apply_patch(patch, raw_text)
    log_line = json.dumps({"date": date.today().isoformat(), "mode": mode, "feedback": " ".join(raw_text.split())[:800], "applied": applied}, ensure_ascii=False)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    with settings.feedback_log.open("a", encoding="utf-8") as handle:
        handle.write(log_line + "\n")
    return {"store": store, "applied": applied, "mode": mode, "summary": patch.get("notes", "")}


def format_result(result: dict[str, Any]) -> str:
    applied = result["applied"]
    lines = [f"策略已更新 → v{result['store'].data['version']}（{result['mode']}）"]
    if applied.get("areas"):
        lines.append("领域权重：" + "、".join(f"{k} → ×{v}" for k, v in applied["areas"].items()))
    if applied.get("subareas"):
        lines.append("子方向权重：" + "、".join(f"{k} → ×{v}" for k, v in applied["subareas"].items()))
    for kind, label in (("positive", "新增偏好"), ("negative", "新增排斥")):
        items = applied.get(kind) or []
        if items:
            lines.append(f"{label}：" + "、".join(f"{i['pattern']}({i['weight']})" for i in items))
    if applied.get("watch"):
        lines.append("关注名单：" + json.dumps(applied["watch"], ensure_ascii=False))
    if applied.get("principles"):
        lines.append("长期原则：" + "、".join(applied["principles"]))
    if applied.get("verdicts"):
        lines.append("记录文章评价：" + "、".join(f"[{v['verdict']}] {v['title'] or v['arxiv_id']}" for v in applied["verdicts"]))
    summary = str(result.get("summary", "")).strip()
    if summary:
        lines.append(f"策略总结：{summary}")
    lines.append(f"可读策略：{result['store'].path.with_suffix('.md')}")
    return "\n".join(lines)


def paper_entries_from_papers(papers: list[Paper]) -> list[dict[str, str]]:
    return [{"index": str(i), "title": p.title, "arxiv_id": p.arxiv_id} for i, p in enumerate(papers, 1)]
