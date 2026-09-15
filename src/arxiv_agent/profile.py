"""The user's research profile, encoded as data.

This module is the reason the agent can select papers like a domain insider
instead of counting keywords. Everything here is a direct transcription of the
research map the author supplied in the project brief: which areas matter, in
which order, which prior works define each lineage, and which groups reliably
ship strong work in those lineages. See docs/DESIGN.md for the reasoning.

It serves three consumers:

* deterministic screening (:func:`screen_paper`) - decides what reaches the LLM;
* LLM prompts (:func:`profile_brief`) - gives the model the same map;
* the feedback loop - area keys and subarea keys are the vocabulary that
  feedback is allowed to re-weight.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Iterable

from .models import Paper


# --------------------------------------------------------------------------- #
# Seed works: the papers/projects the user already knows and cares about.
# Each one doubles as a lineage anchor: if a new paper cites or extends one of
# these, it is almost certainly inside the user's map.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SeedWork:
    name: str
    route: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubArea:
    key: str
    name: str
    why: str
    seeds: tuple[SeedWork, ...] = ()
    vocab: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResearchArea:
    key: str
    name: str
    priority: float  # 1.0 = core to the user, lower = filler
    quota_weight: float  # relative share of the daily digest
    posture: str  # how the user relates to this area, in the user's own words
    subareas: tuple[SubArea, ...] = ()
    vocab: tuple[str, ...] = ()


AREA_3D_GENERATION = ResearchArea(
    key="3d_generation",
    name="3D Generation",
    priority=1.0,
    quota_weight=0.45,
    posture="用户最熟悉的领域。任何在架构上真正推进 Native 3D 生成、Agentic 3D 生成、3D 编辑或可迁移到 3D 的生成范式（RL/Flow/Diffusion/VLM）的工作都优先看；与 World Model、Infra 结合也受欢迎。",
    subareas=(
        SubArea(
            key="native_latent",
            name="Native 3D Generation - Latent decoding to SDF/field + surface extraction",
            why="从 Latent Space 解码出 SDF 后用 Marching Cubes 等做曲面提取；隐空间形态是区分不同路线的关键。",
            seeds=(
                SeedWork("Hunyuan3D-2.1", "Vecset-like latent + SDF + Marching Cubes", ("hunyuan3d", "hunyuan-3d", "hunyuan 3d")),
                SeedWork("TripoSG", "Vecset-like latent + SDF based large reconstruction/generation model", ("triposg", "tripo sg")),
                SeedWork("Seed3D-1.0", "Vecset-like latent native 3D generation", ("seed3d", "seed 3d")),
                SeedWork("Direct3D", "Voxel-like latent native 3D diffusion", ("direct3d", "direct 3d")),
                SeedWork("TRELLIS", "Structured (sparse voxel) latent + rectified flow, with dedicated inference infra", ("trellis", "slat", "structured latent")),
            ),
            vocab=("sdf", "signed distance", "marching cubes", "vecset", "voxel latent", "sparse voxel", "triplane diffusion", "implicit field", "surface extraction", "image-to-3d", "text-to-3d", "isosurface"),
        ),
        SubArea(
            key="native_topology",
            name="Native 3D Generation - Topology-aware (vertices + faces) generation",
            why="直接生成顶点与连接关系，把 Topology 纳入生成，AR / Diffusion / FlowMatching 三种范式都有代表工作。",
            seeds=(
                SeedWork("MeshGPT", "Autoregressive mesh sequence generation with learned tokenization", ("meshgpt", "mesh gpt")),
                SeedWork("Nexus", "Diffusion over mesh tokens topologically", ("nexus",)),
                SeedWork("LATO.2", "Flow-matching route into native mesh generation", ("lato",)),
            ),
            vocab=("mesh generation", "mesh token", "triangles", "polygon", "faces", "autoregressive mesh", "topology-aware", "mesh sequence", "face sequence", "quad mesh"),
        ),
        SubArea(
            key="quality_efficiency",
            name="Precision / efficiency of native 3D generation",
            why="提高精度与效率的工作（含表示压缩、稀疏化、推理加速）直接影响可用性。",
            seeds=(SeedWork("Block3D", "Block-wise / efficiency-oriented native 3D generation", ("block3d",)),),
            vocab=("efficiency", "fast generation", "high-resolution 3d", "detail enhancement", "compression", "acceleration", "inference speed", "memory footprint", "scaling law"),
        ),
        SubArea(
            key="recon_hybrid",
            name="Generation fused with reconstruction for better instruction following",
            why="与 Reconstruction 结合以提升指令遵循度/保真度是一个明确的方向。",
            seeds=(SeedWork("Pixal3D", "Reconstruction-grounded generation for instruction following", ("pixal3d", "pixal 3d")),),
            vocab=("reference-conditioned", "image-conditioned generation", "instruction following", "controllability", "identity preservation", "conditioned generation", "photorealistic 3d"),
        ),
        SubArea(
            key="rigging_parts",
            name="Native rigging / part decomposition / interaction-ready assets",
            why="原生实现绑骨、分割场景物体或分部件生成，尝试原生可交互，是走向可用资产的关键。",
            seeds=(
                SeedWork("SAM3D", "Segment anything in 3D to decompose scenes", ("sam3d", "sam 3d")),
                SeedWork("PartCrafter", "Part-level / compositional generation of 3D assets", ("partcrafter", "part crafter")),
            ),
            vocab=("rigging", "skeleton", "skinning", "articulation", "rig", "part-level", "compositional 3d", "part segmentation", "interactive scene", "scene decomposition", "object-centric"),
        ),
        SubArea(
            key="agentic_3d",
            name="Agentic 3D Generation (3D + LLM/VLM agents)",
            why="用户看到 GPT-6 Astra 的 3D 能力后认为这是重要方向：优点是便于关节交互与仿真，缺点是精度暂时不及 Native Generation。",
            seeds=(
                SeedWork("PhysX-Anything", "Simulation/physical-plausibility driven agentic 3D", ("physx-anything", "physx anything")),
                SeedWork("SAGE", "Agentic 3D scene/asset strategy", ("sage",)),
                SeedWork("Procedure", "Procedural / program-based agentic 3D generation", ("procedure",)),
                SeedWork("Lucida", "Agent-driven 3D authoring", ("lucida",)),
                SeedWork("Articraft", "Agentic articulated object authoring (project)", ("articraft",)),
                SeedWork("img2threejs", "Image to Three.js scene generation (project)", ("img2threejs", "img2three", "three.js")),
            ),
            vocab=("agentic", "llm agent", "vlm agent", "multimodal agent", "tool use", "program synthesis", "simulation", "physics-aware", "articulated object", "scene graph", "code generation", "three.js", "blender", "unreal", "godot"),
        ),
        SubArea(
            key="3d_editing",
            name="3D Editing",
            why="用户认为编辑与生成不可分开讲，近期如 Hunyuan-Buffalo。",
            seeds=(SeedWork("Hunyuan-Buffalo", "Recent 3D editing work from the Hunyuan line", ("hunyuan-buffalo", "buffalo")),),
            vocab=("3d editing", "shape editing", "texture editing", "geometry editing", "local edit", "inverse rendering", "relighting", "appearance editing", "attribute editing", "deformation"),
        ),
        SubArea(
            key="generative_core",
            name="Core generative modelling paradigms transferable to 3D/Video (AR/Flow/Diffusion/VLM/RL)",
            why="用户明确希望把 DreamDPO、FlowGRPO、DiffusionNFT、Diffusion-OPSD 一类可迁移的后训练/对齐范式，以及对应的 Infra（含 RL Infra）纳入视野，可能与 World Model 结合。",
            seeds=(
                SeedWork("DreamDPO", "Direct preference optimization style RL for diffusion", ("dreamdpo",)),
                SeedWork("FlowGRPO", "GRPO-style RL for flow matching models", ("flowgrpo",)),
                SeedWork("DiffusionNFT", "Negative-aware fine-tuning style objectives for 3D/visual diffusion", ("diffusionnft",)),
                SeedWork("Diffusion-OPSD", "Sampling/denoising schedule design with RL/search flavours", ("diffusion-opsd", "opsd")),
            ),
            vocab=("reinforcement learning", "dpo", "grpo", "rlhf", "preference optimization", "policy gradient", "post-training", "reward model", "flow matching", "rectified flow", "diffusion transformer", "consistency model", "autoregressive generation", "next-token", "test-time scaling", "world model", "inference-time scaling"),
        ),
    ),
    vocab=("3d generation", "3d asset", "text-to-3d", "image-to-3d", "3d object", "3d shape", "3d content", "3d aware", "3d diffusion", "3d flow", "3d native", "3d synthes", "3d llm", "3d vlm", "3d agent"),
)

AREA_3D_RECONSTRUCTION = ResearchArea(
    key="3d_reconstruction",
    name="3D Reconstruction",
    priority=0.8,
    quota_weight=0.25,
    posture="用户清楚这一领域从逐场景优化走向 Feed Forward 的脉络； efficiency、3D Scaling Law、以及 3D 升维到 4D 的动态重建都被认为与 Reconstruction 不可分割。",
    subareas=(
        SubArea(
            key="per_scene_optim",
            name="Per-scene optimization pipelines (SfM/MVS, NeRF, 3DGS)",
            why="Feed Forward 之前的主流做法，理解这些 baseline 是判断新工作的前提。",
            seeds=(
                SeedWork("COLMAP", "SfM + MVS reference pipeline", ("colmap",)),
                SeedWork("MVSNet", "Learning-based multi-view stereo depth", ("mvsnet",)),
                SeedWork("NeRF", "Neural radiance fields", ("nerf", "neural radiance field")),
                SeedWork("Triplane NeRF", "Hybrid explicit-implicit NeRF variant", ("triplane", "tri-plane")),
                SeedWork("3DGS", "3D Gaussian Splatting", ("3dgs", "gaussian splatting", "3d gaussian")),
                SeedWork("ProxyGS", "Proxy-guided gaussian splatting variant", ("proxygs",)),
            ),
            vocab=("sfm", "structure from motion", "mvs", "multi-view stereo", "radiance field", "novel view synthesis", "gaussian splatting", "point cloud reconstruction", "bundle adjustment", "inverse rendering"),
        ),
        SubArea(
            key="feed_forward",
            name="Feed-forward reconstruction (object-level and scene-level)",
            why="LRM/TripoSR 代表物体级，DUSt3R/MASt3R/VGGT 代表场景级；还有大量与 GS 结合的工作。",
            seeds=(
                SeedWork("LRM", "Large reconstruction model, transformer triplane feed-forward", ("lrm", "large reconstruction model")),
                SeedWork("TripoSR", "Feed-forward object reconstruction", ("triposr",)),
                SeedWork("DUSt3R", "Dense unconstrained stereo 3D reconstruction", ("dust3r", "du st3r")),
                SeedWork("MASt3R", "Matching-aware DUSt3R successor", ("mast3r",)),
                SeedWork("VGGT", "集大成者：visual geometry grounded transformer over multiple views", ("vggt",)),
            ),
            vocab=("feed-forward reconstruction", "pose estimation", "camera calibration", "multi-view transformer", "depth estimation", "pointmap", "view synthesis", "gaussian head", "3d prior", "pose-free"),
        ),
        SubArea(
            key="recon_efficiency_scaling",
            name="Reconstruction efficiency and 3D scaling laws",
            why="用户点名希望看到提高 Efficiency 与探索 3D Scaling Law（如 VGGT-Omega）的工作。",
            seeds=(SeedWork("VGGT-Omega", "Explores scaling behaviour of feed-forward reconstruction", ("vggt-omega", "vggt omega")),),
            vocab=("scaling law", "efficiency", "real-time reconstruction", "fast feed-forward", "memory efficient", "long sequence", "benchmark suite", "data scaling"),
        ),
        SubArea(
            key="dynamic_4d",
            name="4D / dynamic scene reconstruction",
            why="把 3D 升维到 4D 以重建动态场景，被视为 Reconstruction 的一部分（如 CVPR 2026 Best Paper 相关工作 D4RT）。",
            seeds=(SeedWork("D4RT", "Dynamic 4D reconstruction transformer", ("d4rt",)),),
            vocab=("4d reconstruction", "dynamic scene", "dynamic view synthesis", "time-varying", "deformable", "scene flow", "occupancy flow", "monocular dynamic"),
        ),
    ),
    vocab=("3d reconstruction", "reconstruction", "stereo reconstruction", "multi-view reconstruction", "camera pose estimation", "scene reconstruction"),
)

AREA_VIDEO_GENERATION = ResearchArea(
    key="video_generation",
    name="Video Generation (and image generation as its degenerate form)",
    priority=0.62,
    quota_weight=0.2,
    posture="用户不太熟悉但很感兴趣，认为与 3D Generation 有许多相似之处；基座模型之外，Video Editing、RL、质量 Benchmark 都算，也可能与 World Model 结合。用户同时把 Image Generation 视为 Video 的降维形态，有趣/重要的 Image 工作也可以给。",
    subareas=(
        SubArea(
            key="video_base",
            name="Video base models and architectures",
            why="基座模型（如 Wan-2.1、Minimax 系列）决定整个领域的上限。",
            seeds=(
                SeedWork("Wan-2.1", "Open large-scale video foundation model", ("wan 2.1", "wan2.1", "wan-2.1", "wan model")),
                SeedWork("Minimax-H3", "Minimax video base line the user follows", ("minimax", "hailuo", "minimax-h3", "h3")),
            ),
            vocab=("text-to-video", "video generation", "video diffusion", "video transformer", "video synthesis", "image-to-video", "controllable video", "long video", "camera control", "video foundation model"),
        ),
        SubArea(
            key="video_edit_rl",
            name="Video editing, RL alignment and benchmarks",
            why="与 3D 相同，编辑与 RL 对齐/质量评测是不可分割的部分。",
            seeds=(),
            vocab=("video editing", "video restoration", "video inpainting", "rlhf video", "reward model", "preference optimization", "video benchmark", "evaluation protocol", "world model", "consistency", "temporal coherence"),
        ),
        SubArea(
            key="image_gen",
            name="Important or interesting image generation work",
            why="用户把 Image 视为 Video 的降维形态，重要的 image generation 工作同样有价值。",
            seeds=(),
            vocab=("text-to-image", "image generation", "image editing", "rectified flow", "latent diffusion", "image synthesis", "personalization", "subject-driven generation", "controlnet"),
        ),
    ),
    vocab=("video generation", "video model", "video editing", "video diffusion", "temporal consistency", "multimodal generation"),
)

AREA_EMBODIED_AI = ResearchArea(
    key="embodied_ai",
    name="Embodied AI",
    priority=0.35,
    quota_weight=0.1,
    posture="用户不太熟悉但略感兴趣，路线繁多。只有当 3D Generation / 3D Reconstruction / Video Generation 三个领域当天确实找不到值得读的工作时，才从这里补足。",
    subareas=(
        SubArea(
            key="vla_policies",
            name="Vision-language-action models and robot policies",
            why="用户了解过 OpenVLA、pi_0、pi_0.5 等重要工作。",
            seeds=(
                SeedWork("OpenVLA", "Open vision-language-action model", ("openvla",)),
                SeedWork("pi_0", "Flow-based generalist robot policy", ("pi_0", "pi 0", "pi-zero", "pi0")),
                SeedWork("pi_0.5", "Open-world generalization successor of pi_0", ("pi_0.5", "pi0.5", "pi 0.5")),
            ),
            vocab=("vision-language-action", "vla", "robot policy", "manipulation", "imitation learning", "embodied ai", "robot learning", "dexterous", "locomotion", "sim-to-real", "teleoperation"),
        ),
        SubArea(
            key="world_model_sim",
            name="Embodied world models, simulation and data engines",
            why="若 Embodied AI 方向需要补选论文，与 3D/视频生成交叉的仿真、世界模型、数据合成最有价值。",
            seeds=(),
            vocab=("world model", "embodied simulation", "simulator", "scene synthesis", "data engine", "policy transfer", "digital twin", "interactive environment"),
        ),
    ),
    vocab=("embodied ai", "embodied agent", "robotics", "robot learning", "vision-language-action"),
)

AREAS: tuple[ResearchArea, ...] = (AREA_3D_GENERATION, AREA_3D_RECONSTRUCTION, AREA_VIDEO_GENERATION, AREA_EMBODIED_AI)
AREA_BY_KEY: dict[str, ResearchArea] = {area.key: area for area in AREAS}
SUBAREA_BY_KEY: dict[str, SubArea] = {f"{a.key}/{s.key}": s for a in AREAS for s in a.subareas}
AREA_NAMES: dict[str, str] = {a.key: a.name for a in AREAS}


# --------------------------------------------------------------------------- #
# Credibility signals: institutions, product lines and venues.
# Deliberately treated as *weak* evidence only - the model does the judging.
# --------------------------------------------------------------------------- #

TOP_INSTITUTIONS: tuple[str, ...] = (
    # Companies with track records in the user's exact lineages.
    "Google DeepMind", "Google Research", "Google Brain", "Meta", "FAIR", "NVIDIA", "Microsoft",
    "Microsoft Research Asia", "Adobe Research", "OpenAI", "ByteDance", "Seed", "Bytedance Seed",
    "Alibaba", "Alibaba Group", "Qwen", "Ant Group", "Tencent", "Tencent Hunyuan", "Hunyuan",
    "Baidu", "Kuaishou", "Kwai", "快手", "Shopee", "Netflix", "Snap Research", "Stability AI",
    "Luma AI", "Tripo", "Deemos", "Meshy", "Rodin", "Ubisoft", "Epic Games", "Sony AI", "Samsung",
    "Toyota Research", "Huawei", "Noah's Ark", "Zhipu", "Moonshot AI", "MiniMax", "Shengshu",
    # Academic groups that reliably publish in these areas.
    "Peking University", "Tsinghua University", "Shanghai Jiao Tong University", "Zhejiang University",
    "The Chinese University of Hong Kong", "Hong Kong University", "HKUST", "Nanjing University",
    "Fudan University", "University of Science and Technology of China", "Beihang University",
    "Stanford University", "MIT", "Massachusetts Institute of Technology", "UC Berkeley", "Berkeley",
    "Carnegie Mellon University", "University of Washington", "Cornell University", "Princeton University",
    "University of Illinois Urbana-Champaign", "Georgia Institute of Technology", "University of Toronto",
    "Oxford University", "University of Oxford", "Cambridge University", "ETH Zurich", "ETH Zürich",
    "Max Planck Institute", "MPI-INF", "Weizmann Institute", "Tel Aviv University", "Technion",
    "KAUST", "National University of Singapore", "Nanyang Technological University", "KAIST",
    "University of Adelaide", "University of Sydney", "Technical University of Munich", "TU Munich",
    "INRIA", "Inria", "Ecole Polytechnique",
)

VENUE_TERMS: tuple[str, ...] = (
    "CVPR", "ICCV", "ECCV", "NeurIPS", "ICML", "ICLR", "SIGGRAPH", "SIGGRAPH Asia", "AAAI", "3DV", "TPAMI", "ACM TOG",
)

# Topics whose mere presence should not block a paper, but should strongly lower
# the prior - the user does not work on them.
COLD_TOPICS: tuple[str, ...] = (
    "medical image", "radiology", "histopatholog", "CT reconstruction", "MRI", "fMRI", "EEG", "brain-computer",
    "agricultur", "remote sensing", "hyperspectral", "astronom", "galaxy", "protein", "drug discovery",
    "speech recognition", "machine translation", "sentiment analysis", "recommender", "traffic forecasting",
    "financial", "pedestrian detection", "face anti-spoofing", "palmprint", "underwater",
)


def all_seed_terms() -> dict[str, tuple[str, ...]]:
    """Map every seed-work alias to the subarea key that owns it."""
    mapping: dict[str, list[str]] = {}
    for area in AREAS:
        for sub in area.subareas:
            for seed in sub.seeds:
                names = {seed.name.lower(), *[a.lower() for a in seed.aliases]}
                for name in names:
                    mapping.setdefault(name, []).append(f"{area.key}/{sub.key}")
    return {k: tuple(sorted(set(v))) for k, v in mapping.items()}


LINEAGE_INDEX: dict[str, tuple[str, ...]] = all_seed_terms()


def _word_re(term: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-zA-Z0-9])" + re.escape(term.lower()) + r"(?![a-zA-Z0-9])")


def paper_text(paper: Paper) -> str:
    return " ".join([paper.title, paper.abstract, paper.comment]).lower()


def screen_paper(paper: Paper) -> dict[str, object]:
    """Deterministic evidence extraction: which parts of the map this paper touches.

    Returns conservative signals only. A missing hit never proves irrelevance -
    the LLM stage can still rescue a paper whose authors never named the obvious
    keyword - but a hit is a cheap reason to keep it in the candidate pool.
    """
    text = paper_text(paper)
    keyword_hits: list[str] = []
    lineage_hits: list[str] = []
    area_candidates: list[str] = []
    area_scores: dict[str, float] = {}

    for area in AREAS:
        score = 0.0
        for term in area.vocab:
            if term.lower() in text:
                keyword_hits.append(term)
                score += 1.0
        for sub in area.subareas:
            sub_score = 0.0
            for term in sub.vocab:
                if term.lower() in text:
                    keyword_hits.append(f"{sub.key}:{term}")
                    sub_score += 1.0
            for seed in sub.seeds:
                for name in {seed.name.lower(), *[a.lower() for a in seed.aliases]}:
                    if _word_re(name).search(text):
                        lineage_hits.append(seed.name)
                        sub_score += 2.0
            if sub_score:
                score += sub_score
        if score:
            area_scores[area.key] = round(score, 2)
            area_candidates.append(area.key)

    # Rank proposals: explicit subarea vocabulary plus the user's own prior work
    # list is the cheapest available proxy for "this is written for us".
    ordered = sorted(area_scores.items(), key=lambda kv: (-kv[1], AREA_INDEX.get(kv[0], 99)))
    institutions = sorted({name for name in TOP_INSTITUTIONS if name.lower() in text})
    venues = sorted({name for name in VENUE_TERMS if name.lower() in text})
    cold = sorted({name for name in COLD_TOPICS if name.lower() in text})

    return {
        "keyword_hits": keyword_hits,
        "lineage_hits": sorted(set(lineage_hits)),
        "area_candidates": [k for k, _ in ordered],
        "area_scores": area_scores,
        "institutions": institutions,
        "venues": venues,
        "cold_topics": cold,
        "screen_score": round(sum(area_scores.values()), 2),
    }


AREA_INDEX: dict[str, int] = {area.key: i for i, area in enumerate(AREAS)}


def profile_brief(style: str = "triage") -> str:
    """Render the map for model prompts. Chinese, dense, and grounded in the user's words."""
    lines: list[str] = [
        "# 用户研究画像（按相关性从高到低）",
        "",
        "筛选时请把“用户会不会真的想明天早上读它”放在第一位；机构名气只是辅助信号，不能替代判断。",
        "",
    ]
    for area in AREAS:
        lines.append(f"## {area.name} [{area.key}]  优先级={area.priority}  目标份额≈{int(area.quota_weight * 100)}%")
        lines.append(f"- 用户立场：{area.posture}")
        for sub in area.subareas:
            lines.append(f"### {sub.name} [{sub.key}]")
            lines.append(f"- 为什么重要：{sub.why}")
            if sub.seeds:
                seed_desc = "; ".join(f"{s.name}（{s.route}）" for s in sub.seeds)
                lines.append(f"- 已知代表工作：{seed_desc}")
                lines.append("- 若新工作在这些已知工作的路线上延续/对照/改进，请判为高相关（这是“谱系命中”）。")
        lines.append("")
    lines.append("## 相关性之外的可信度信号（仅作弱证据）")
    lines.append("- 作者/单位出现在 arXiv comment 或摘要中的知名团队：" + "、".join(TOP_INSTITUTIONS[:18]) + " 等。")
    lines.append("- 已有 arXiv 版本版本迭代、带 Venue 接受信息、开源仓库有星有活跃提交，都是加分但不是质量保证。")
    lines.append("- 出现下列主题时，除非它确实以上述领域为核心贡献，否则应降权：" + "、".join(COLD_TOPICS[:10]) + " 等。")
    if style == "triage":
        lines.append("")
        lines.append("## 评分口径")
        lines.append("- relevance：对用户上述研究地图的实际相关程度（看清标题目—哪怕只在相邻领域擦边也不给高分）。")
        lines.append("- credibility：方法/实验/证据链看起来扎实程度，结合单位与谱系，但不得因单位名气单独给高分。")
        lines.append("- novelty：相对上述已知代表工作是否带来新东西，纯工程堆叠或换数据集的低分。")
    return "\n".join(lines)


def area_of(subarea_key_or_empty: str) -> str:
    return subarea_key_or_empty.split("/")[0] if subarea_key_or_empty else ""


def quota_plan(total: int) -> dict[str, int]:
    """Split the digest into per-area slots using the configured priorities."""
    if total <= 0:
        return {}
    raw = {area.key: total * area.quota_weight for area in AREAS}
    base = {k: int(v) for k, v in raw.items()}
    assigned = sum(base.values())
    order = sorted(AREAS, key=lambda a: (-area_priority_rank(a), AREA_INDEX[a.key]))
    i = 0
    while assigned < total:
        area = order[i % len(order)]
        base[area.key] += 1
        assigned += 1
        i += 1
    return base


def area_priority_rank(area: ResearchArea) -> float:
    return area.priority


def default_categories() -> list[str]:
    """Categories that plausibly carry papers in the four areas.

    Deliberately excludes cs.CL/cs.NE bulk, which mostly adds irrelevant noise
    while eating triage budget.
    """
    return ["cs.CV", "cs.GR", "cs.RO", "cs.MM", "cs.AI", "cs.LG"]


def iter_seed_names() -> Iterable[str]:
    yield from LINEAGE_INDEX
