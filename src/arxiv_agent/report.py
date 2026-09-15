"""Render the daily digest: one Chinese Markdown file per day."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .models import Paper, TrendingProject
from .profile import AREA_NAMES, SUBAREA_BY_KEY

SECTIONS = (
    ("background_motivation", "背景与动机"),
    ("architecture", "整体架构"),
    ("lineage", "与先前工作的联系"),
    ("insights", "Insight"),
    ("innovations", "核心创新点"),
    ("evaluation", "评测与效果"),
    ("code", "代码与实践"),
    ("limitations_risks", "局限与风险"),
    ("why_read", "为什么推荐"),
    ("how_to_read", "建议读法"),
)


def _md(value: object) -> str:
    return str(value or "").replace("\n", "\n  ").strip() or "（未提供）"


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip() or "-"


def render_report(
    papers: list[Paper],
    generated: date,
    settings: Settings,
    daily: dict[str, Any],
    projects: list[TrendingProject],
    stats: dict[str, Any],
) -> str:
    lines: list[str] = [f"# 每日 arXiv 精选 · {generated.strftime('%y-%m-%d')}", ""]
    summary = f"> 检索窗口：最近 {settings.days} 天，共 {stats.get('harvested', 0)} 篇候选；初筛保留 {stats.get('screened', 0)} 篇送审；最终入选 {len(papers)} 篇。"
    if len(papers) < settings.min_papers:
        summary += f" 本次窗口内的高相关论文不足 {settings.min_papers} 篇，为避免用旧论文凑数，保持实际数量。"
    lines.append(summary)
    detail = f"> 分析模型：`{settings.model}`（provider `{stats.get('provider', '?')}`，并发 {settings.max_concurrency}）；"
    detail += f"耗时 {stats.get('minutes', '?')} 分钟；模型调用 {stats.get('llm_calls', 0)} 次"
    if stats.get("llm_failures"):
        detail += f"，其中 {stats['llm_failures']} 次失败并降级"
    if stats.get("transport"):
        detail += f"；arXiv 抓取通道：`{stats.get('transport')}`"
    detail += "。"
    lines.append(detail)
    lines.append("")

    note = str(daily.get("daily_note", "")).strip()
    if note:
        lines += ["## 今日导读", "", note, ""]
        words = [str(w) for w in (daily.get("watchwords") or [])]
        if words:
            lines.append("**明日可重点盯的词**：" + "、".join(words))
            lines.append("")

    lines += ["## 速览", "", "| # | 标题 | 方向 | 子方向 | 综合 | 相关/可信/新颖 | 推荐理由 |", "|---:|---|---|---|---:|---|---|"]
    for index, paper in enumerate(papers, 1):
        subarea = SUBAREA_BY_KEY.get(paper.subarea)
        subarea_label = subarea.name if subarea else (paper.subarea or "-")
        scores = paper.scores
        triples = f"{scores.get('relevance', 0):.0f}/{scores.get('credibility', 0):.0f}/{scores.get('novelty', 0):.0f}"
        lines.append(
            f"| {index} | [{_cell(paper.title)}]({paper.abs_url}) | {_cell(AREA_NAMES.get(paper.area, paper.area or '-'))} "
            f"| {_cell(subarea_label)} | {paper.relevance:.2f} | {triples} | {_cell(paper.triage_reason[:90])} |"
        )
    lines.append("")

    for index, paper in enumerate(papers, 1):
        analysis = paper.analysis or {}
        lines += ["", f"## {index}. {paper.title}", ""]
        meta = [f"**arXiv**：[{paper.arxiv_id}]({paper.abs_url})　**PDF**：[下载]({paper.pdf_url})"]
        if paper.published:
            meta.append(f"**发布**：{paper.published.date().isoformat()}")
        meta.append(f"**方向**：{AREA_NAMES.get(paper.area, paper.area or '未分类')}")
        lines += ["　".join(meta), ""]
        authors = paper.authors
        if authors:
            shown = "、".join(authors[:8]) + ("等" if len(authors) > 8 else "")
            lines.append(f"**作者**：{shown}  ")
        if paper.comment:
            lines.append(f"**arXiv 备注**：{_cell(paper.comment)}  ")
        if paper.repo and paper.repo.get("url"):
            repo = paper.repo
            lines.append(f"**代码**：[{_cell(repo.get('full_name'))}]({repo.get('url')})（★{repo.get('stars', 0)}，{_cell(repo.get('language'))}，License：{_cell(repo.get('license_name')) or '未标注'}）  ")
        lines.append(f"**一句话结论**：{_cell(analysis.get('one_liner', ''))}")
        lines.append("")
        for key, heading in SECTIONS:
            value = analysis.get(key, "")
            if key == "code" and not (paper.repo and paper.repo.get("url")):
                continue
            lines += [f"### {heading}", "", _md(value), ""]
        lines.append(f"**证据等级**：{_md(analysis.get('confidence', '未标注'))}")
        fulltext_state = f"{paper.full_text_source or '无'}（{paper.full_text_chars} 字符）" if paper.full_text else "未获取到全文"
        lines.append(f"**本次读到的材料**：正文 {fulltext_state}；代码 {'已抓取' if paper.repo else '未检索到可靠仓库'}。")
        lines.append("")

    if projects:
        lines += ["", "## GitHub 近一周上升项目（非论文）", ""]
        lines.append("趋势分为 stars/天 的透明代理值，来自仓库创建时间与当前 star 数，不是真实的星标增速。")
        lines.append("")
        lines.append("| 项目 | 方向 | Stars | 趋势(stars/天) | 推荐理由 | 简介 |")
        lines.append("|---|---|---:|---:|---|---|")
        for project in projects:
            lines.append(
                f"| [{_cell(project.name)}]({project.url}) | {_cell(AREA_NAMES.get(project.area, project.area or '-'))} "
                f"| {project.stars} | {project.stars_per_day} | {_cell(project.why)} | {_cell(project.description)} |"
            )
        lines.append("")

    lines += _transparency(papers, settings, stats)
    return "\n".join(lines) + "\n"


def _transparency(papers: list[Paper], settings: Settings, stats: dict[str, Any]) -> list[str]:
    lines = ["", "## 选取过程透明度", ""]
    lines.append(f"- 候选 {stats.get('harvested', 0)} 篇 → 初筛保留 {stats.get('screened', 0)} 篇 → 模型评审 {stats.get('judged', 0)} 轮 → 入选 {len(papers)} 篇。")
    slots = stats.get("slots") or {}
    if slots:
        usage = "、".join(f"{AREA_NAMES.get(k, k)} {v}" for k, v in slots.items())
        lines.append(f"- 领域配额（按画像优先级与反馈权重计算）：{usage}。")
    dropped = stats.get("dropped_by_area") or {}
    if dropped:
        left = "、".join(f"{AREA_NAMES.get(k, k)} 余 {v} 篇未取" for k, v in dropped.items() if v)
        if left:
            lines.append(f"- 落选代表：{left}。")
    lineage_total = sum(len(p.lineage_hits) for p in papers)
    if lineage_total:
        lines.append(f"- 谱系命中（延续或对照用户已知代表作的新工作）：入选论文中共 {lineage_total} 处。")
    if stats.get("notes"):
        for note in stats["notes"]:
            lines.append(f"- {note}")
    lines += [
        "",
        "**诚实声明**：报告中的架构与结果描述来自上述模型的精读，可能存在理解偏差；所有链接直接指向 arXiv 与 GitHub，"
        "方法细节与数字请以原文为准。未获取到全文的条目已在正文中标注。此处的“机构名气”只作为弱证据参与排序，不代表质量担保。",
        "",
        "## 给 Agent 反馈",
        "",
        "读完后执行 `python -m arxiv_agent 反馈`（或 `feedback`）并按提示输入：哪些文章不满意及原因、哪些思路值得借鉴、"
        "想调整的方向权重。反馈会被合成为版本化的选文策略（`.arxiv-agent/strategy.md`），下次 `work` 自动生效。",
        "",
    ]
    return lines


def write_report(output_dir: Path, generated: date, papers: list[Paper], settings: Settings, daily: dict[str, Any], projects: list[TrendingProject], stats: dict[str, Any]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{generated.strftime('%y-%m-%d')}.md"
    path.write_text(render_report(papers, generated, settings, daily, projects, stats), encoding="utf-8")
    return path


def now_local() -> datetime:
    return datetime.now()
