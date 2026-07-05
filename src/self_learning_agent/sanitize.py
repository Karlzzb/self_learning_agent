"""孤立代理项(lone surrogate)清洗:系统边界的确定性护栏。

上游模型(Qwen/百炼)偶发在返回文本里夹带一个**孤立 UTF-8 代理项**(如
``\\udce5``——某个多字节字符的字节序列被上游截断/错误解码后遗留下来的单个代理
码位)。这种码位能存在于 Python ``str``,但一旦做 **strict UTF-8 编码**就抛
``UnicodeEncodeError: surrogates not allowed``。本项目里有两个这样的编码边界:

- **产物落盘**:``workspace.write_text``(``encoding="utf-8"``)写课程/参考 HTML、
  ``MISSION.md`` 等。
- **请求体**:节点把对话历史发回模型时,HTTP 客户端对 body 做 strict UTF-8 编码。

这两个边界各有一道确定性护栏:

- 落盘边界由 ``workspace.write_text`` 收口。
- 请求体边界由 ``models._sanitize_outgoing`` 收口——在「唯一碰具体模型的地方」对**每个
  出站请求**的 messages 清洗。``state._sanitizing_add_messages`` 另在「消息进入 A 层会话
  状态」时清洗(护住 checkpointer 持久化与下一轮历史),但它**覆盖不到**节点在单轮内本地
  拼装、绕过 reducer 的 transcript(如 ``mission._establish`` 把模型产出的追问直接 append
  再发回模型)——那条路径只有请求体边界的护栏能拦住。

只要坏码位进了产物或某个请求体,对应边界就会崩,且往往在下一轮、在累积负载的深处才现
(故表现为偶发)。上述护栏把孤立代理项替换成 U+FFFD(``�``),从根上消除该崩溃——
faithfully 承接 ADR-0009「在系统边界用确定性护栏坦白处理坏数据,而非静默传播」的姿态。
"""

from __future__ import annotations

import re

# 代理码位区间 U+D800–U+DFFF。合法的非 BMP 字符(如 emoji)在 Python ``str`` 里是
# **单个**码位(内部 UTF-32 表示),绝不会落进这个区间;因此这个正则只命中「孤立
# 代理项」,不会误伤任何正常字符(含中文、emoji)。
_LONE_SURROGATE = re.compile("[\ud800-\udfff]")

# U+FFFD REPLACEMENT CHARACTER(``�``):被替换的坏码位在产物/历史里仍可见,便于
# 事后定位「是哪一处模型输出吐了坏字节」,而不是被静默抹掉。
_REPLACEMENT = "\ufffd"


def sanitize_surrogates(text: str) -> str:
    """把 ``text`` 里的孤立代理项替换成 U+FFFD(``�``);非 ``str`` 原样返回。

    幂等:对已经干净的文本返回相等的字符串,可安全重复调用。
    """
    if not isinstance(text, str):
        return text
    return _LONE_SURROGATE.sub(_REPLACEMENT, text)


__all__ = ["sanitize_surrogates"]
