"""可观测层:``get_callbacks()`` 返回喂给一次图调用的 tracing 回调列表。

承接 ADR-0008 预留的「换后端」口子:观测后端从 LangSmith 换成 self-hosted
**Langfuse**(见 ADR-0016)。与 LangSmith「纯环境变量、LangChain 自动识别、代码零
接线」不同,Langfuse 走 LangChain 的**回调机制**——需要把一个 ``CallbackHandler``
通过 ``config={"callbacks": [...]}`` 显式传进每次 ``graph.invoke``。为不让这处接线
渗进业务节点,把它收敛进本模块这一个缝(与「搜索藏在 ``search()`` 后」「模型藏在
``get_model()`` 后」同构):唯一的图驱动内核 ``runner.invoke_turn`` 调 ``get_callbacks()``
取回调,业务节点一行不动。换观测后端 = 改本模块;图结构与节点都不动。

密钥与地址由 ``.env`` 注入(``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY`` /
``LANGFUSE_HOST``),``CallbackHandler()`` 从环境自动读取——承接「密钥由运营/调用方
提供,智能体永不自管」。开关是 ``config.LANGFUSE_TRACING``:置 false / 留空即关闭,
此时 ``get_callbacks()`` 返回空列表且**完全不 import langfuse**,故无 langfuse 依赖
或未配置的环境(如 hermetic 测试)零影响、零触网。
"""

from __future__ import annotations

import warnings
from functools import lru_cache
from typing import Any

from . import config


@lru_cache(maxsize=1)
def _build_handler() -> Any | None:
    """构造并缓存 Langfuse 回调处理器;不可用时告警一次并返回 ``None``。

    lazy import:仅当 tracing 开启时才碰 langfuse,让未装该依赖 / 未配置的环境
    (含测试)不受影响。缺依赖或初始化失败**不致命**——观测是旁路,不该拖垮教学
    主流程,故降级为「关闭 tracing + 一次告警」。
    """
    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:  # pragma: no cover - 依赖缺失时的降级路径
        warnings.warn(
            "LANGFUSE_TRACING 已开启,但未安装 langfuse。tracing 将被跳过;"
            "请 `pip install langfuse`(见 pyproject 依赖)。",
            RuntimeWarning,
            stacklevel=2,
        )
        return None

    try:
        # 密钥 / 地址由环境注入:LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY /
        # LANGFUSE_HOST。CallbackHandler() 自动读取,本层不经手明文密钥。
        return CallbackHandler()
    except Exception as exc:  # pragma: no cover - 初始化失败时的降级路径
        warnings.warn(
            f"初始化 Langfuse CallbackHandler 失败,tracing 将被跳过:{exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return None


def get_callbacks() -> list:
    """返回喂给一次图调用的回调列表。tracing 关闭 / 不可用时为空列表。

    空列表对 ``graph.invoke(config={"callbacks": []})`` 是无害的 no-op,故调用方
    无需分支判断——「关观测」与「开观测」在驱动侧走同一行代码。
    """
    if not config.LANGFUSE_TRACING:
        return []
    handler = _build_handler()
    return [handler] if handler is not None else []
