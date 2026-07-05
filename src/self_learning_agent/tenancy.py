"""多租户键的推导:``topic`` → ``topic_slug``、``(user_id, topic_slug)`` → ``thread_id``。

ADR-0003/0004:智能体**不**自管账号/鉴权;多租户仅靠调用方传入的 ``user_id``
与 ``topic``。这里把这两者收敛成两类键:

- ``topic_slug``:把自由文本主题归一成稳定、可做目录名的 slug,用于
  ``workspaces/{user_id}/{topic_slug}/`` 的文件隔离(单一事实源)。
- ``thread_id``:LangGraph checkpointer 的会话键(ADR-0001 控制流:
  每条学习者消息调用一次图,以 ``thread_id = f(user_id, topic_slug)`` 为键)。

两者都是纯函数、确定性、无副作用,便于在图层缝测试里直接断言隔离与续接。
"""

from __future__ import annotations

import re
import unicodedata

# slug 里允许保留的字符;其余统一折叠成连字符。
_NON_SLUG = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")
_EDGE_DASH = re.compile(r"^-+|-+$")

# slug 兜底值:主题为空/全是分隔符时,仍给出一个稳定的合法目录名。
_EMPTY_SLUG = "topic"

# 目录名长度上限(防止超长主题撑爆文件系统路径)。
_MAX_SLUG_LEN = 80


def topic_slug(topic: str) -> str:
    """把自由文本主题归一成稳定、文件系统安全的 slug(保留中文)。

    设计取舍:保留中文字符(本产品面向中文学习者,主题常为中文),只折叠
    空白与标点;ASCII 统一小写。同一主题永远映射到同一 slug,保证续接;
    不同主题映射到不同 slug,保证隔离。
    """
    normalized = unicodedata.normalize("NFKC", topic).strip().lower()
    slug = _NON_SLUG.sub("-", normalized)
    slug = _EDGE_DASH.sub("", slug)
    slug = slug[:_MAX_SLUG_LEN]
    slug = _EDGE_DASH.sub("", slug)  # 截断后可能又在边缘留下连字符
    return slug or _EMPTY_SLUG


def thread_id(user_id: str, topic_slug_value: str) -> str:
    """checkpointer 会话键。``::`` 作分隔符(不与 slug 字符集冲突)。"""
    return f"{user_id}::{topic_slug_value}"
