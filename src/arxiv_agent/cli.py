from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .agent import DailyArxivAgent
from .config import MAX_CONCURRENCY, Settings, load_env_file
from .feedback import collect_interactive, format_result, load_report_entries, run_feedback
from .llm import LLMBackendError, build_backend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arxiv-agent", description="领域定制的每日 arXiv 选文 Agent：研究画像初筛 → 模型评审 → 中文日报（选文策略随反馈进化）")
    sub = parser.add_subparsers(dest="command", required=True)

    work = sub.add_parser("work", aliases=["工作"], help="抓取近几天 arXiv → 研究画像筛选 → 生成中文 Markdown 日报")
    work.add_argument("--days", type=int, help="检索最近 N 天提交的论文（1-7，默认 3）")
    work.add_argument("--min-papers", type=int, help="最少入选篇数（默认 10）")
    work.add_argument("--max-papers", type=int, help="最多入选篇数（1-15，默认 15）")
    work.add_argument("--target", type=int, help="期望入选篇数（默认 12）")
    work.add_argument("--model", help="模型名：任意 OpenAI 兼容模型（gpt-4.1-mini / deepseek-chat ...）或 CLI 网关模型（如 hy4-preview）")
    # default=None (not "") so an omitted flag never overwrites a provider that
    # came from --config, the environment or .env.
    work.add_argument("--provider", choices=["auto", "openai", "codebuddy", "offline"], default=None, help="覆盖模型后端推断")
    work.add_argument("--output", type=Path, help="报告输出目录（默认 reports）")
    work.add_argument("--state-dir", type=Path, help="策略与缓存目录（默认 .arxiv-agent）")
    work.add_argument("--config", type=Path, help="JSON 配置文件")
    work.add_argument("--max-concurrency", type=int, choices=(1, MAX_CONCURRENCY), help="模型并发上限，最多 2")
    work.add_argument("--time-budget", type=int, help="总耗时预算（分钟，默认 45）")
    work.add_argument("--triage-pool", type=int, help="送入模型评审的候选数量（默认 90）")
    work.add_argument("--skip-code", action="store_true", help="跳过 GitHub 代码抓取")
    work.add_argument("--skip-trending", action="store_true", help="跳过 GitHub 趋势项目推荐")
    work.add_argument("--no-cache", action="store_true", help="忽略 arXiv 抓取缓存")
    work.add_argument("--offline", action="store_true", help="不调用任何模型（仅验证流水线）")

    feedback = sub.add_parser("feedback", aliases=["反馈"], help="交互式收集反馈并更新选文策略")
    feedback.add_argument("text", nargs="?", help="直接给出反馈文本；省略则进入交互式提问")
    feedback.add_argument("--file", type=Path, help="从文件读取多行反馈")
    feedback.add_argument("--output", type=Path, help="报告目录（用于按编号索引当次文章）")
    feedback.add_argument("--state-dir", type=Path)
    feedback.add_argument("--model", help="用于合成策略的模型")
    feedback.add_argument("--provider", choices=["auto", "openai", "codebuddy", "offline"], default=None)
    feedback.add_argument("--config", type=Path)

    show = sub.add_parser("strategy", aliases=["策略"], help="查看当前选文策略")
    show.add_argument("--state-dir", type=Path)
    show.add_argument("--config", type=Path)
    return parser


def _settings_from_args(args: argparse.Namespace, base: Settings) -> None:
    mapping = {
        "days": "days",
        "min_papers": "min_papers",
        "max_papers": "max_papers",
        "target": "target_papers",
        "model": "model",
        "provider": "provider",
        "output": "output_dir",
        "state_dir": "state_dir",
        "max_concurrency": "max_concurrency",
        "time_budget": "time_budget_min",
        "triage_pool": "triage_pool",
    }
    for arg_name, attr in mapping.items():
        value = getattr(args, arg_name, None)
        if value is not None:
            setattr(base, attr, value)
    if getattr(args, "skip_code", False):
        base.skip_code = True
    if getattr(args, "skip_trending", False):
        base.skip_trending = True
    if getattr(args, "offline", False):
        base.offline = True
    # Cache always lives under the state directory, so a custom state dir keeps
    # its own cache instead of mixing into the default one.
    base.cache_dir = Path(base.state_dir) / "cache"
    base.clamp()


def main(argv: list[str] | None = None) -> int:
    # `.env` in the working directory is the friendly way to keep per-machine
    # settings (model route, output dir) out of the shell profile. Exported
    # variables still win, and the file is git-ignored.
    load_env_file(Path.cwd() / ".env")
    _make_output_safe()
    args = build_parser().parse_args(argv)
    settings = Settings.load_json(args.config) if getattr(args, "config", None) else Settings.from_env()
    _settings_from_args(args, settings)

    if args.command in ("feedback", "反馈"):
        return _run_feedback(args, settings)
    if args.command in ("strategy", "策略"):
        from .strategy import StrategyStore

        store = StrategyStore(settings.strategy_file)
        print(store.render_markdown())
        return 0
    return _run_work(args, settings)


def _debug_enabled() -> bool:
    """``ARXIV_AGENT_DEBUG=0`` must mean off, not "the string '0' is truthy"."""
    return os.getenv("ARXIV_AGENT_DEBUG", "").strip().lower() not in ("", "0", "false", "no", "off")


def _make_output_safe() -> None:
    """Chinese output must not crash a console whose encoding cannot hold it.

    The digest, the strategy printout and every error message are Chinese. On a
    UTF-8 or CP936 console the probe below succeeds and nothing changes; on a
    legacy Western code page (or a redirect on such a machine) writing them would
    raise UnicodeEncodeError, so those streams are switched to UTF-8 with
    replacement instead of losing the whole report to a traceback.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None)
        if not encoding:
            continue
        try:
            "中文".encode(encoding)
        except (UnicodeEncodeError, LookupError):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, ValueError, OSError):
                pass


def _run_work(args: argparse.Namespace, settings: Settings) -> int:
    # During "work" the user wants no chatter: only the final path is printed.
    if getattr(args, "no_cache", False):
        import shutil

        shutil.rmtree(settings.cache_dir, ignore_errors=True)
    try:
        path = DailyArxivAgent(settings).work()
    except LLMBackendError as exc:
        print(f"arxiv-agent: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"arxiv-agent: {exc}", file=sys.stderr)
        if _debug_enabled():
            import traceback

            traceback.print_exc()
        return 1
    print(path)
    return 0


def _run_feedback(args: argparse.Namespace, settings: Settings) -> int:
    try:
        backend = build_backend(args.model or settings.model, args.provider or settings.provider, offline=args.provider == "offline")
    except LLMBackendError as exc:
        print(f"arxiv-agent: {exc}", file=sys.stderr)
        return 2
    if args.file:
        raw = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        raw = args.text
    else:
        entries = load_report_entries(Path(args.output) if getattr(args, "output", None) else settings.output_dir)
        raw = collect_interactive(entries)
    if not raw.strip():
        print("arxiv-agent: 没有收到反馈内容，策略未变更。", file=sys.stderr)
        return 1
    result = run_feedback(settings, backend, raw)
    print(format_result(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
