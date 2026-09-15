> English: [README.md](README.md)

# Daily Arxiv in My Domain

**一个懂你研究地图的每日 arXiv 侦察员。**

每天早上，它会读完 arXiv 最近几天的投稿，从几百篇里筛出 10–15 篇真正落在*你*研究主线上的论文，
读完正文和代码，写出一份能直接上手的中文 Markdown 日报。然后它会听你说话：你的反馈被编译成一份
**带版本号的选取策略**，直接改变它明天挑什么。

不是通用推荐器，也不是审稿人。目标更窄，也更难：
**把几百篇鱼龙混杂的投稿，变成一份简短、可信、可解释的阅读队列——并且每周都比上一周做得更好。**

[![CI](https://github.com/OWNER/Daily_Arxiv_in_My_Domain/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/Daily_Arxiv_in_My_Domain/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue.svg)](pyproject.toml)
[![Tests](https://img.shields.io/badge/tests-38%20offline-brightgreen.svg)](tests/test_agent.py)
[![Dependencies](https://img.shields.io/badge/runtime%20deps-none%20(stdlib)-lightgrey.svg)](pyproject.toml)

> 示例输出：[examples/2026-09-15-daily-digest.md](examples/2026-09-15-daily-digest.md)（一次真实、未删改的运行）

---

## 为什么会有这个项目

arXiv 是一个研究领域被裁决的地方，却也是一个糟糕透顶的界面。平常一天里，`cs.CV`、`cs.GR`、`cs.RO`、
`cs.MM`、`cs.AI` 和 `cs.LG` 加起来就有几百篇新论文挂出来。关键词提醒分不清*「TRELLIS 的继任者，换了新的
稀疏隐空间接口」*和*「把 diffusion 用到信用评分上」*——两篇里都有 "diffusion" 这个词。全部读完是不可能
的；什么都不读，代价只是换了一种货币来支付。

这个项目押的注是：**一个研究领域不是一组关键词，而是一张谱系图。** 只要你把自己真正在做的谱系写下来
——基础的表示方式、定义每条路线的前序工作、你认为尚未解决的子问题——筛选就变成一个可处理、可审计的
问题。这张地图是本项目的核心资产，它以数据的形式住在
[`src/arxiv_agent/profile.py`](src/arxiv_agent/profile.py) 里，而不是写成提示词里的一段话。

## 它能做什么

| 命令 | 会发生什么 |
|---|---|
| `arxiv-agent work`（别名 `工作`） | 抓取 arXiv 最近 1–7 天的投稿 → 确定性初筛 → LLM 评审团 → 组合分配 → 全文 + 代码 → `reports/YY-MM-DD.md` |
| `arxiv-agent feedback`（别名 `反馈`） | 问 5 个有针对性的问题（也可以一次性贴文本 / 用 `--file`），把它们编译成一份策略补丁 |
| `arxiv-agent strategy`（别名 `策略`） | 打印当前生效的策略、它的权重和版本历史 |

`work` 运行期间**什么都不输出**，只在最后打印报告路径。一条命令进去，一个 Markdown 文件出来。

## 快速开始

需要 Python 3.10+（开发环境是 3.12）。运行时**没有任何第三方依赖**——在你选定模型后端之前，一切都是
标准库。

```bash
git clone https://github.com/OWNER/Daily_Arxiv_in_My_Domain.git
cd Daily_Arxiv_in_My_Domain
python -m venv .venv && source .venv/bin/activate    # Windows: .\.venv\Scripts\Activate.ps1
pip install -e ".[openai,fulltext]"                  # openai SDK + pypdf (PDF fallback)
cp .env.example .env                                 # Windows: copy .env.example .env
```

`.env` 会从工作目录自动读取（真实环境变量优先级更高）。

```bash
# 1) any OpenAI-compatible endpoint — the default route
OPENAI_API_KEY=sk-...
arxiv-agent work

# 2) DeepSeek and friends: same client, different base URL
OPENAI_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=sk-...
arxiv-agent work --model deepseek-chat

# 3) a locally authenticated CLI gateway (how this project is run day to day)
arxiv-agent work --model hy4-preview --provider codebuddy

# pipeline self-check: no model calls, no credentials, no cost
arxiv-agent work --offline --days 3 --target 3
```

`--offline` 会把除模型之外的每个阶段都跑一遍：它写出的日报只由确定性启发式打分，每篇论文都会被标记为
未经评判，所以它是用来验证环境配置的，不是用来读的。如果一次运行在日期校验之后窗口里什么都不剩，它会
带着一条诚实的错误退出，而不是写一份空日报——这时把 `--days` 调大再试。

可选但推荐：`GITHUB_TOKEN` 能提高 GitHub API 的额度（每次运行 core 调用 30 → 45，search 调用
6 → 25），并用于给论文关联代码仓库、寻找正在上升的非论文项目。

## 输出长什么样

每天一个文件，`reports/26-09-15.md`，12 篇论文约 1,600 行。结构如下：

| 章节 | 内容 |
|---|---|
| 报告头 | 检索窗口、候选 → 初筛 → 入选、模型、provider、并发数、耗时、模型调用次数、使用的 arXiv 传输通道 |
| `## 今日导读` | 当天的跨论文趋势——路线聚类、正在被延伸的谱系、横跨多个领域的信号、显眼的空白——外加 3–5 个第二天的关注词 |
| `## 速览` | 表格：标题、领域、子方向、综合得分、三个原始分数、一句话理由 |
| `## 1..N` | 每篇论文：一句话 · 背景与动机 · 架构（输入 → 表示 → 数据流 → 损失 → 推理） · **与先前工作的联系，点名它延伸、替换或对照了哪些具体工作** · insight · 创新点 · 评测（数据集/指标/基线/数字/消融） · 代码与实践（从仓库里读出来的，不是猜的） · 局限与风险 · 为什么值得读 · 怎么读（带时间盒的阅读计划） · **证据等级** |
| `## GitHub 近一周上升项目` | 近一周上升的非论文仓库，并明确声明热度数字只是一个代理指标 |
| `## 选取过程透明度` | 漏斗计数、领域配额、值得注意的拒稿、谱系命中、过程中发生的每一次降级，以及一段用大白话写的诚实声明 |
| `## 给 Agent 反馈` | 把反馈发回去的那条确切命令 |

一段真实节选：

> **今日观察**
> **一、部件级（part-level）是今天最集中的爆发点，且两篇都寄生在 TRELLIS 谱系上。**
> 两篇 3D 生成入选论文同时把「部件」提升为一等对象，但切口相反…… 两者都没有另起表示——前者冻结复用
> Hunyuan3D 的 ShapeVAE 作为 mesh-aware 条件，后者直接把 dual-volume packing 移植到 TRELLIS.2 自己的
> O-Voxel 稀疏网格上。

完整示例：[`examples/2026-09-15-daily-digest.md`](examples/2026-09-15-daily-digest.md)。

## 工作原理

```
arxiv-agent work
│
├─ 1. harvest        arxiv_client   Atom API → RSS → monthly listing, three channels with cache
├─ 2. dedup          seen.json      papers already surfaced in the last 7 days are skipped
├─ 3. screen         profile+       deterministic: vocabulary hits + lineage anchors − cold topics
│                                   hundreds of candidates → ≤90 sent to the model
├─ 4. jury           triage         LLM scores relevance / credibility / novelty per batch of 12
├─ 5. allocate       triage         composite score → area quotas → 10–15 papers, quality floor
├─ 6. verify dates   arxiv_client   every finalist is re-dated on its abs page; stale ones are dropped
├─ 7. read           fulltext +     arXiv HTML → ar5iv → PDF, section-prioritised; attach the repo
│                    github_client  (README, tree, recent commits)
├─ 8. analyse        analyze        per-paper Chinese reading note + cross-paper daily observation
├─ 9. report         report         reports/YY-MM-DD.md, including the transparency appendix
└─ 10. trending      github_client  rising non-paper repositories, model-filtered
```

两个 `ThreadPoolExecutor`（先跑评审批次，再跑论文），都受 `--max-concurrency` 约束，而它的硬上限是
**2**。墙钟时间按阶段强制执行，全部对照同一个单调时钟的截止时间。

## 真正重要的几个部分

### 1. 研究地图是数据，不是提示词

`profile.py` 编码了 4 个领域、17 个子方向、约 41 个具名种子工作和约 208 个词表术语：

| 领域 | 优先级 | 日报占比 | 子方向 |
|---|---:|---:|---|
| 3D Generation | 1.0 | 45% | 原生隐空间、拓扑感知、精度/效率、生成+重建、绑骨/部件、Agentic 3D、3D 编辑、可迁移的生成核心 |
| 3D Reconstruction | 0.8 | 25% | 逐场景优化、Feed Forward、效率与 Scaling、动态/4D |
| Video Generation | 0.62 | 20% | 基座模型、编辑与 RL、图像生成 |
| Embodied AI | 0.35 | 10% | VLA 策略、世界模型与仿真 |

每个子方向都写明了*它为什么重要*、它内部有哪些路线，以及它的**谱系锚点**——那些定义这条路线的先前工作
（TRELLIS、Hunyuan3D-2.1、TripoSG、MeshGPT、VGGT、DUSt3R、MASt3R、3DGS、Wan-2.1……）。谱系锚点
正是让初筛显得「内行」的机制：一篇延伸、替换或拿某个具名锚点做对比的论文，几乎一定在这张地图上，而
初筛会明确奖励这一点，而不是指望某个关键词恰好出现。

机构和会议也被编码进去了——但被刻意**排除在排序信号之外**。它们只是表层证据，作为弱上下文展示给
模型，提示词里明确禁止按声望打分。第一个问题永远是「你明天早上想不想读这篇」，而不是「这是不是某个
著名实验室做的」。

### 2. 先用便宜的过滤，把昂贵的判断留给塔尖

```
hundreds of candidates
  │  deterministic: +1 per vocabulary hit, +2 per lineage anchor (word-boundary match),
  │  −2 per cold topic; prior = score + 3×lineage + 1×areas − 2×cold
  │  keep prior > 0, force-keep anything with a lineage hit, always pass the 10 newest
  ▼
≤ 90 candidates  →  LLM jury, batches of 12, three 0–10 scores each
  │  relevance (does it sit on a named route?) · credibility (is the evidence chain visible?)
  │  novelty (is it new relative to the known anchors?) · keep = relevance ≥ 3.5
  ▼
scored pool  →  portfolio allocation  →  10–15 papers
```

关键词缺失从来不能证明一篇论文不相关，所以最新挂出的十篇论文无论得分多少都会被直接送进评审团——
确定性阶段决定的是「什么值得花昂贵的注意力」，从来不是「什么好」。

### 3. 做的是配额分配，不是 Top-N 列表

每篇论文的综合得分：

```
0.58 × relevance + 0.22 × credibility + 0.20 × novelty
  + min(2.5, 1.2 × lineage_hits)          # lineage bonus
  + 0.4  if it fits ≥2 areas              # cross-area bonus
  + strategy delta                         # feedback patterns, watch lists
  − 1.5  if the model never judged it      # never silently trusted
  then × area weight × sub-area weight     # feedback multipliers
```

随后论文按配额分配到各领域（`quota_weight × feedback weight`），其中有两条规则比算术本身更重要：

- **质量下限**——一旦达到最低篇数，原始 relevance 低于 5.0 的一律不再加入；
- **不凑数**——平静的一天就该产出更短的日报，报告里也会如实说明。每个领域的最低在场数可以补上一个缺位的
  领域，但用户明确拒掉的论文（strategy delta ≤ −1.5）绝不会被拿来填坑。

### 4. 反馈会变成一份带版本号的策略文件

反馈不会被做成一个隐藏的权重向量。它被编译进 `.arxiv-agent/strategy.json`（外加一份人类可读的
`strategy.md` 镜像和一个只追加的 `feedback-log.jsonl`）：

```jsonc
{
  "version": 7,
  "area_weights":       { "3d_generation": 1.15, "video_generation": 0.8, ... },
  "subarea_weights":    { "3d_generation/rigging_parts": 1.3 },
  "positive_patterns":  [ { "pattern": "open-source + ablation", "weight": 1.0, "reason": "..." } ],
  "negative_patterns":  [ { "pattern": "benchmark only", "weight": 3.0, "reason": "..." } ],
  "watch":              { "labs": [...], "authors": [...], "projects": [...] },
  "principles":         [ "优先推荐有开源代码与消融实验的工作" ],
  "paper_verdicts":     [ { "arxiv_id": "...", "verdict": "bad", "reason": "只是换了数据集" } ],
  "history":            [ { "version": 7, "summary": "...", "feedback_excerpt": "..." } ]
}
```

每个阶段都会读它：评审团和阅读提示词会拿到原则、模式、关注名单和最近 12 条判定；综合打分拿到模式与
关注名单带来的增量；分配环节拿到领域权重和拒稿否决权。权重会被钳制（单次增量 ±0.6，最终权重 0.2–3.0），
历史长度有上限，每一次补丁都可回滚——这个文件本来就是给人读、手改、纳入版本管理的。没有任何东西会去
改源码。

### 5. 诚实是架构强制的，不只是提示词里的要求

- **今日观察**只能断言当天材料支撑得起的内容，并标注不确定性；如果当天认真读完的论文不足两篇，整节
  直接跳过。
- 每篇阅读笔记都把【原文】和【推断】分开，未知信息一律填「文中未提供」，而不是填一个看起来合理的
  猜测，并且带一个**证据等级**和一行「我实际读了什么」（全文来源与字符数、有没有找到代码）。
- 日期被当成敌情处理：没有日期的 RSS 条目会根据 arXiv id 做保守推测，入选前在它的 abs 页面上复核
  一遍，入选之后再复核一遍。日报里绝不会悄无声息地混进上个月的论文。
- 失败的模型调用会变成显式的 `_degraded` 备注，置信度为「低」——绝不会变成一段看起来很像样的编造。
  如果抓取或筛选为空，整个运行会大声失败，而不是写出一份空日报。
- 报告的透明度附录会列出本次运行中发生的每一次降级、每一篇被跳过的论文、每一次预算耗尽。

### 6. 成本、延迟与失败控制

默认一次运行约 20 次模型调用、35–45 分钟。两者都在设计上被封顶：并发硬上限 2、按时段强制执行的墙钟
预算（默认 45 分钟，上限 60），以及一条用深度换完成度的降级阶梯：

| 剩余预算 | 放弃什么 |
|---|---|
| < 35% | 全文预算 26,000 → 15,600 字符 |
| < 20% | 仓库抓取（即 `--skip-code` 的行为） |
| 每篇 < 240 s | 全文：只分析摘要，并明确标注 |
| 每篇 < 200 s | GitHub 仓库关联 |
| < 180 s | 跨论文的今日观察 |
| < 150 s | 上升项目 |
| 每篇 < 90 s | 模型调用本身——只写元数据笔记，置信度「低」 |

arXiv 访问是一条三通道回退链（Atom API → RSS → 月度列表页），带 3 秒礼貌延迟、磁盘缓存，并且有意
避开服务端的日期范围查询——实测这种查询会触发 `429 Rate exceeded`。限流从来不是靠猛敲解决的：一旦
遇到 429，就停下该类别，把它交给下一个通道。

## 已知局限

之所以写下来，是因为一个藏起自己接缝的工具，就是一个你没法信任的工具：

- **模型的判断不是同行评审。** 得分只是一种初筛启发式；机构和会议信号是弱证据。日报里的每一条论断
  都必须回到论文本身核对。
- **初筛锚定在某一个人的地图上。** 换掉画像，得分就会跟着变（`docs/CUSTOMIZE.md` 里写明了该改哪些
  常量）。
- **缓存没有 TTL。** `abs:{id}` 页面和抽出的全文会被永久缓存；只有 `--no-cache` 能清掉，而命中缓存全文
  时，来源会记为 `cache`。
- **全文覆盖率参差不齐。** 数学公式在 HTML 里会被剥掉，PDF 这条路径会退化成只截开头，因为空白折叠
  破坏了用于章节优先级排序的段落结构。
- **同一天的日报会覆盖上一份**（`reports/YY-MM-DD.md`）。
- **报告里的 `model calls` 是下界**——内部的 JSON 修复调用没有被计入。
- **arXiv 窗口并不穷尽。** Atom 分页每次运行每个类别最多 400 条，所以跑 `--days 7` 时，一个繁忙的
  类别可能超出窗口。
- **GitHub 计数器在（至多两个）工作线程之间没有同步**，所以 API 预算和 1 req/s 的间隔在接近耗尽时
  可能被轻微突破。
- **`min_papers` 是目标，不是保证。** 平静的一天就是会产出更短的日报，这是有意为之。
- `seen.json` 在报告渲染之前就写入了，所以一次迟到的失败可能把一篇论文标记成已见，却没有真正交付。

## 配置

`arxiv-agent work --help` 里有完整列表。真正要紧的几个开关：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--days N` | 3 | 1–7，会被钳制在该区间内 |
| `--target N` / `--min-papers` / `--max-papers` | 12 / 10 / 15 | `max-papers` 硬上限为 15 |
| `--model` / `--provider` | `gpt-4.1-mini` / auto | provider 由模型名推断；`auto\|openai\|codebuddy\|offline` |
| `--max-concurrency 1\|2` | 1 | 硬上限 2，在 CLI、配置层和编排器里都会强制 |
| `--time-budget N` | 45 | 分钟，5–60 |
| `--triage-pool N` | 90 | 有多少候选能进入评审团 |
| `--output DIR` / `--state-dir DIR` | `reports` / `.arxiv-agent` | 报告与个人状态 |
| `--skip-code` / `--skip-trending` / `--no-cache` / `--offline` | off | `--no-cache` 会先删掉抓取缓存 |

环境变量：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`DEEPSEEK_API_KEY`、`GITHUB_TOKEN`、
`ARXIV_AGENT_MODEL`、`ARXIV_AGENT_PROVIDER`、`ARXIV_AGENT_OUTPUT_DIR`、`ARXIV_AGENT_STATE_DIR`、
`ARXIV_AGENT_DAYS`、`ARXIV_AGENT_MIN_PAPERS`、`ARXIV_AGENT_MAX_PAPERS`、
`ARXIV_AGENT_MAX_CONCURRENCY`、`ARXIV_AGENT_TIME_BUDGET`、`ARXIV_AGENT_DEBUG`。优先级：
**CLI flag > `--config` JSON > 真实环境变量 > `.env` > 默认值**。

更深的开关（`categories`、`max_candidates`、`triage_batch`、`fulltext_chars`、`request_delay`）放在
一个通过 `--config` 传入的 JSON 配置里：

```json
{ "days": 2, "target_papers": 12, "categories": ["cs.CV", "cs.GR", "cs.RO"], "triage_batch": 12 }
```

## 改成你自己的

这个项目是为一位研究者的地图写的，但结构上做了隔离：你唯一需要替换的就是那张地图——`profile.py` 里
的四个 `ResearchArea` 字面量、`default_categories()`，以及机构/会议/冷门主题列表；具体替换点和坑见
**[docs/CUSTOMIZE.md](docs/CUSTOMIZE.md)**（例如：策略里存的 `area_weights` 键如果已经不存在，会被
静默丢弃，所以换完画像之后要重新初始化 `.arxiv-agent/strategy.json`）。

设计理由与最初的需求文档：**[docs/DESIGN.md](docs/DESIGN.md)**。
逐模块架构与每一个常量：**[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**。
发布你自己的副本：**[docs/PUBLISHING.md](docs/PUBLISHING.md)**。

## 仓库结构

```
src/arxiv_agent/            17 modules, ~3.5k lines, no runtime dependencies
  profile.py                the research map: areas, sub-areas, seed works, vocabulary
  arxiv_client.py           three-channel harvest, caching, date verification
  fulltext.py               HTML → ar5iv → PDF extraction with section prioritisation
  github_client.py          paper → repository binding; rising-project discovery
  triage.py                 deterministic screen, LLM jury, portfolio allocation
  analyze.py                per-paper reading note, daily observation, project judging
  strategy.py               versioned feedback memory (JSON + Markdown mirror)
  feedback.py               the interactive/one-shot feedback conversation
  report.py                 the Chinese Markdown digest
  agent.py                  orchestration: phases, budget, degradation ladder
  llm.py                    one interface, three backends (HTTP / CLI / offline)
  cli.py, config.py, models.py, prompts.py, __main__.py
tests/test_agent.py         38 offline tests: parsing, screening, allocation, strategy, CLI wiring
examples/                   a real, unedited digest
docs/                       design, architecture, customization, publishing
```

## 开发

```bash
pip install -e ".[dev,fulltext]"
python -m pytest        # 38 tests, fully offline: no network, no credentials
python -m ruff check src tests
```

测试套件有意只覆盖**逻辑，不碰网络**：fixture 都是 Atom/RSS/列表页的 XML 片段、GitHub JSON 和脚本化的
模型回复。CI 会在 Python 3.10、3.11、3.12 上跑 lint 和整个测试套件，然后再对 CLI 做一次冒烟测试。由于
离线后端从不假装自己分析了任何东西，`--offline` 运行依然会端到端跑完整条流水线。

欢迎贡献——见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全说明（密钥怎么处理、哪些东西留在本地、提示词注入
的风险面）见 [SECURITY.md](SECURITY.md)。

## 这个项目是怎么建起来的

这个项目是它的作者**在 AI 编码助手的协助下**构建的，而这本身就是重点的一部分：作者写了研究地图和
需求文档，定了架构（画像即数据、两阶段漏斗、策略即文件），拿真实运行结果逐个阶段地检查行为，并推动
整个迭代闭环；AI 则在这套方向下写了大部分代码。领域内容——哪些路线重要、哪些谱系锚点定义了它们、
什么算得上一篇值得读的论文——都是作者的，而这恰恰是通用工具给不了的那部分。`docs/DESIGN.md` 里把
最初的需求文档和实际实现的内容放在一起，包括被砍掉的东西。

## 路线图

- 一份每周汇总，跟踪某条路线在跨天尺度上的演进，而不是每天早上从零开始。
- 阅读队列状态（已读 / 已跳过 / 值得引用），让反馈能区分「选得差」和「还没读」。
- 基于 embedding 的近重复检测，不再只依赖 arXiv id。
- 给共享缓存目录加上缓存 TTL 和锁文件。

## 许可证

MIT——见 [LICENSE](LICENSE)。永远不要提交 `.env`、`.arxiv-agent/` 或 `reports/`：那里装着你的密钥、
你正在演化的策略和你的研究兴趣。
