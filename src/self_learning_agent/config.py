"""集中配置 + 逐节点模型档位路由表。

模型层是「一个可换的旋钮」(见 PRD「模型与工具」与记忆中的 ADR 原则):

- 默认 provider = Qwen via DashScope(走 OpenAI 兼容端点)。
- **切换默认模型只需改一处**:环境变量 ``LLM_PROVIDER``(或本文件 ``DEFAULT_PROVIDER``),
  任何业务节点代码都不需要改动。
- 每个图节点绑定一个**档位**(``Tier``):重认知节点 → 最强档,轻节点 → 便宜档。
- **绝不为模型能力限制而修改业务架构**:换模型只换这张表,图结构不动。

本文件只做「读配置 + 维护路由表」,不构造模型实例(那是 ``models.py`` 的职责),
以便单测路由逻辑时无需触网。
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

# 读取 .env。Langfuse 的标准环境变量(LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY /
# LANGFUSE_HOST)在此一并加载,由 ``observability.get_callbacks()`` 在图驱动内核处
# 接线成 LangChain 回调(ADR-0016 取代 ADR-0008 的 LangSmith:换 self-hosted 后端,
# 观测收敛进 ``observability`` 这一个缝,业务节点零改动)。
load_dotenv()


class Tier(str, Enum):
    """模型档位。重认知 → STRONG,中等 → MID,轻量 → LIGHT。"""

    STRONG = "strong"
    MID = "mid"
    LIGHT = "light"


# provider -> 档位 -> 具体模型名。
# 换 provider / 换档位映射只动这张表,业务节点零改动。
PROVIDER_TIER_MODELS: dict[str, dict[Tier, str]] = {
    # 默认:通义千问(DashScope/百炼)
    "qwen": {
        Tier.STRONG: "qwen-max",
        Tier.MID: "qwen-plus",
        Tier.LIGHT: "qwen-turbo",
    },
    # 切到 Claude 的口子(承接原则:模型可换,架构不动)。
    "anthropic": {
        Tier.STRONG: "claude-opus-4-6",
        Tier.MID: "claude-sonnet-4-6",
        Tier.LIGHT: "claude-haiku-4-5-20251001",
    },
}

# 节点名 -> 档位 路由表。键为 ``models.get_model(node_name)`` 的实际传参名(与图节点 /
# 子图步骤对应);重认知节点(创作/规划/评估/访谈)用最强档,轻节点(意图路由)用便宜档。
# 注:学习记录写入是**确定性**动作(``workspace.append_learning_record``,不调 LLM),
# 故此表无 records 档——「何时写记录」是节点的教学判断,「怎么写」是确定性原语。
NODE_TIERS: dict[str, Tier] = {
    "router": Tier.LIGHT,            # 意图分类,轻
    "mission_interview": Tier.STRONG,  # 使命访谈,重(共情 + 追问)
    "research": Tier.MID,           # 资料检索甄别,中
    "zpd": Tier.STRONG,             # ZPD/下一课规划,重
    "lesson": Tier.STRONG,          # 课程创作,重(子图起草 + 自审档)
    "reference": Tier.MID,          # 参考文档压缩,中(从已写好的课程蒸馏,非从零创作)
    "assessment": Tier.STRONG,      # 对话式评估/追问误解,重
    "wisdom": Tier.STRONG,          # 实战智慧:尝试回答 + 甄别高声望社区,重
    "judge": Tier.STRONG,           # LLM-as-judge 回归评分(#012),重(与课程创作同档,严格打分)
}

# 未登记的节点回退到此档位(永不因缺表项而崩)。
DEFAULT_TIER: Tier = Tier.MID

# 默认 provider:一处切换全局生效。
DEFAULT_PROVIDER: str = os.getenv("LLM_PROVIDER", "qwen")

# 所有节点默认温度(单节点差异化温度后续按需添加,此处保持极简)。
DEFAULT_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.7"))

# DashScope(Qwen)OpenAI 兼容端点。
DASHSCOPE_BASE_URL: str = os.getenv(
    "DASHSCOPE_BASE_URL",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# 搜索层(ADR-0007:极简工具面)。搜索藏在 search(query)->candidates 接口后,
# 唯一硬约束是可达性。换搜索提供方只改这一处 env / search.set_provider,
# 业务节点零改动(与「模型是可换旋钮」同构)。
# - dashscope:MVP 默认,百炼内置 enable_search,不需要独立密钥(复用
#   DASHSCOPE_API_KEY)。不上 MCP、不上 RAG/向量库、不上 reranker。
SEARCH_PROVIDER: str = os.getenv("SEARCH_PROVIDER", "dashscope")

# 单次检索返回的候选条数上限(甄别前的原始候选)。
SEARCH_MAX_RESULTS: int = int(os.getenv("SEARCH_MAX_RESULTS", "8"))

# Research 多查询采集(#018 / §D7):一轮 research 对「关键子主题」各发一条查询,汇总
# 去重成更厚的候选池,让下游 draft 有足量可引用源。上限有界,防止查询数发散烧配额;
# 仍不用 RAG/向量库/reranker(ADR-0007),只是把「单趟搜索」换成「有界的多趟覆盖」。
RESEARCH_MAX_QUERIES: int = int(os.getenv("RESEARCH_MAX_QUERIES", "5"))

# --- Spacing 间隔复习(#024 / ADR-0012)----------------------------------------
# teach 的 desirable difficulty 含 spacing,原本靠 Claude 的 ambient memory 判断「该复习
# 什么」;移植版用 Coverage Ledger(lessons/manifest.json 的 committed_at 时间戳)+ 当前时间
# 显式派生「该复习什么」信号喂给 ZPD。此常量是「教过多久算到期该复习」的间隔阈值(天):
# 一节课 committed 超过此天数即被列为间隔复习候选。有界、可配置;retrieval / interleave
# 不受影响(它们已分别由课内 quiz 与 draft prompt 落地)。
SPACING_REVIEW_DAYS: float = float(os.getenv("TEACH_SPACING_REVIEW_DAYS", "7"))

# 多租户工作区根目录(ADR-0003:文件是 B/C 层的单一事实源,按
# workspaces/{user_id}/{topic_slug}/ 命名空间隔离)。在调用时读取本值,
# 便于测试用 monkeypatch 指向临时目录做隔离。
WORKSPACES_ROOT: str = os.getenv("TEACH_WORKSPACES_ROOT", "./workspaces")

# 会话/图状态的 checkpointer 落盘位置(MVP = SQLite;生产换 Postgres)。
CHECKPOINT_DB: str = os.getenv("TEACH_CHECKPOINT_DB", "./checkpoints/teach.sqlite")

# --- Lesson 创作子图(#007 / ADR-0006)------------------------------------------
# 「质量由架构保证,不寄望模型一次写好」:起草 → 机器校验(#006)→ LLM 自审 →
# 不达标则重写,直到通过或达上限。达上限仍不达标 → 不交付(ADR-0009 失败姿态)。
# 重试上限有界:防止无限重写烧 token,且兜底保证「状态不丢、请稍后再来」。
LESSON_MAX_ATTEMPTS: int = int(os.getenv("LESSON_MAX_ATTEMPTS", "3"))

# 自审阈值(RUBRIC.md「Pass threshold」逐字承接):每个判断条目 ≥ 3,且均值 ≥ 4.0。
# 确定性条目由 #006 机器校验把关(必须 100% 通过),不在自审里打分。
CRITIQUE_MIN_ITEM: int = int(os.getenv("LESSON_CRITIQUE_MIN_ITEM", "3"))
CRITIQUE_MIN_MEAN: float = float(os.getenv("LESSON_CRITIQUE_MIN_MEAN", "4.0"))

# 权威评分依据 RUBRIC.md 的位置(仓库根)。自审 / 人评 / LLM-judge「一处定义,三处
# 复用」,故由代码加载这一份文件喂给自审模型,而非把 rubric 文字散抄进 prompt。
# 相对包根定位:src/self_learning_agent/config.py → parents[2] = 仓库根。
RUBRIC_PATH: str = os.getenv(
    "TEACH_RUBRIC_PATH",
    str(Path(__file__).resolve().parents[2] / "RUBRIC.md"),
)

# --- RUBRIC 评分缝(#012:LLM-as-judge + 人评校准)-------------------------------
# 「一处定义,三处复用」的第二、三处:LLM-as-judge 与人评。两者都复用 RUBRIC.md 的
# **判断条目**与同一组阈值(``CRITIQUE_MIN_ITEM`` / ``CRITIQUE_MIN_MEAN``)——与课内
# 自审(ADR-0006)同源。确定性条目由 #006 机器校验把关,不在此打分。
#
# 人评校准达标线([ours] 脚手架,原 skill 无):先用人评(权威)校准 LLM-judge,使其
# 成为可自动化的代理指标。逐项打分要足够贴近人评、且通过/不通过的判定要足够一致,才算
# 校准成功;达不到则该 judge 不可作回归指标(需调 prompt / 换档)。
JUDGE_CALIBRATION_WITHIN_ONE: float = float(
    os.getenv("JUDGE_CALIBRATION_WITHIN_ONE", "0.8")
)
JUDGE_CALIBRATION_DECISION_AGREEMENT: float = float(
    os.getenv("JUDGE_CALIBRATION_DECISION_AGREEMENT", "0.8")
)

# 固定课程样本集(样本 HTML + 人评标注)位置(仓库根的 scoring/samples)。
# 回归监控:课程教学质量随时间/改动的变化,跑 judge over 这组样本观察。
JUDGE_SAMPLES_DIR: str = os.getenv(
    "TEACH_JUDGE_SAMPLES_DIR",
    str(Path(__file__).resolve().parents[2] / "scoring" / "samples"),
)


# --- 可观测性:逐节点链路追踪(ADR-0016,取代 ADR-0008 的 LangSmith)-------------
# self-hosted Langfuse。开关一处生效:置空 / false 即完全关闭(``get_callbacks()``
# 返回空列表、不 import langfuse),开发与生产皆可用。密钥与地址由 .env 注入
# (``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` / ``LANGFUSE_HOST``),
# ``CallbackHandler()`` 自动读取——智能体不经手明文密钥。


def _env_flag(name: str, default: str = "false") -> bool:
    """把 ``true/1/yes/on``(大小写不敏感)解读为真,其余为假。"""
    return os.getenv(name, default).strip().lower() in {"true", "1", "yes", "on"}


LANGFUSE_TRACING: bool = _env_flag("LANGFUSE_TRACING")

# self-hosted 部署地址。CallbackHandler() 直接读环境的 LANGFUSE_HOST;此处仅为
# 集中登记默认值,便于文档与排障时一眼看到当前后端。
LANGFUSE_HOST: str = os.getenv("LANGFUSE_HOST", "http://10.15.231.165:13000")
