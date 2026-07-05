"""模型层:``get_model(node_name)`` 返回一个已配置好的 chat model。

这是教学图里**唯一**碰具体模型的地方。每个能力节点只说「我是哪个节点」,
由本模块按 ``config`` 的路由表决定用哪个 provider 的哪个档位、哪个模型名。
换模型 = 改 ``config`` 的表;业务节点一行不动(承接「模型是可换旋钮」原则)。
"""

from __future__ import annotations

import os
from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from . import config
from .config import Tier
from .sanitize import sanitize_surrogates


def _sanitize_outgoing(messages) -> None:
    """请求边界护栏(ADR-0009):发往模型前,把每条消息内容里的孤立代理项就地替换成
    U+FFFD(见 ``sanitize.py``)。

    这是「消息离开进程、被 HTTP 客户端做 strict UTF-8 编码」这个**真正会崩的编码边界**。
    ``state._sanitizing_add_messages`` 只清洗**进入 A 层会话状态**的消息,覆盖不到节点在
    单轮内**本地拼装**的 transcript(如 ``mission._establish`` 把模型产出的追问
    ``AIMessage(question)`` 直接 append 进本地列表再发回模型)——那条路径绕过 reducer,
    坏码位会一路到请求体编码处才抛 ``UnicodeEncodeError``。模型层是「唯一碰具体模型的
    地方」,在此收口能一次性护住所有节点的所有出站请求(含结构化输出 / 本地 transcript),
    而不必在每处 transcript 拼装点零散设防。清洗幂等,已干净的消息原样通过。
    """
    for message in messages:
        content = getattr(message, "content", None)
        if isinstance(content, str):
            cleaned = sanitize_surrogates(content)
            if cleaned != content:
                message.content = cleaned
        elif isinstance(content, list):
            # 多模态 / 分块内容:清洗每个文本块的 ``text`` 字段(非文本块原样保留)。
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    cleaned = sanitize_surrogates(block["text"])
                    if cleaned != block["text"]:
                        block["text"] = cleaned


def tier_for(node_name: str) -> Tier:
    """节点 → 档位。未登记的节点回退到 ``DEFAULT_TIER``,永不崩。"""
    return config.NODE_TIERS.get(node_name, config.DEFAULT_TIER)


def model_name_for(node_name: str, provider: str | None = None) -> str:
    """节点(+ provider)→ 具体模型名。"""
    provider = provider or config.DEFAULT_PROVIDER
    tier = tier_for(node_name)
    try:
        return config.PROVIDER_TIER_MODELS[provider][tier]
    except KeyError as exc:
        raise ValueError(
            f"未知的 provider/档位组合:provider={provider!r} tier={tier.value!r}。"
            f"请在 config.PROVIDER_TIER_MODELS 中登记。"
        ) from exc


@lru_cache(maxsize=None)
def _build(provider: str, model_name: str, temperature: float) -> BaseChatModel:
    """按 provider 构造 chat model。结果按 (provider, model, temp) 缓存复用。

    在系统边界 fail-fast:缺密钥时给出清晰错误,而非静默走到调用才报。
    """
    if provider == "qwen":
        # Qwen 走 DashScope 的 OpenAI 兼容端点 → 复用 ChatOpenAI。
        from langchain_openai import ChatOpenAI

        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "缺少 DASHSCOPE_API_KEY。请在 .env 中配置(见 .env.example)。"
            )

        class _QwenChatOpenAI(ChatOpenAI):
            """DashScope 兼容层:结构化输出默认走 ``function_calling``(工具调用)。

            ``with_structured_output`` 在本版 langchain_openai 里默认走
            ``json_schema``,会向 DashScope 发 ``response_format`` 的 json 模式;
            而 Qwen 端点要求此时 messages 里必须出现 "json" 字样,否则报
            ``InvalidParameter``。Qwen 对工具调用支持良好,故在模型层把默认
            method 改为 ``function_calling``,业务节点无需感知此差异。
            """

            def with_structured_output(self, schema=None, *, method="function_calling", **kwargs):  # type: ignore[override]
                return super().with_structured_output(schema, method=method, **kwargs)

            def _generate(self, messages, *args, **kwargs):  # type: ignore[override]
                # 请求边界护栏:出站前清洗孤立代理项(见 ``_sanitize_outgoing``)。
                # 普通 invoke 与结构化输出都汇流经此,故在此收口即护住所有出站请求。
                _sanitize_outgoing(messages)
                return super()._generate(messages, *args, **kwargs)

        return _QwenChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=config.DASHSCOPE_BASE_URL,
            temperature=temperature,
        )

    if provider == "anthropic":
        # 切到 Claude 的口子。
        from langchain_anthropic import ChatAnthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "缺少 ANTHROPIC_API_KEY。请在 .env 中配置(见 .env.example)。"
            )

        class _GuardedChatAnthropic(ChatAnthropic):
            """与 Qwen 分支同构:出站前过请求边界护栏(见 ``_sanitize_outgoing``)。"""

            def _generate(self, messages, *args, **kwargs):  # type: ignore[override]
                _sanitize_outgoing(messages)
                return super()._generate(messages, *args, **kwargs)

        return _GuardedChatAnthropic(
            model=model_name,
            api_key=api_key,
            temperature=temperature,
        )

    raise ValueError(
        f"未知 provider:{provider!r}。请在 config.PROVIDER_TIER_MODELS 中登记,"
        f"并在 models._build 中添加对应构造分支。"
    )


def get_model(
    node_name: str,
    provider: str | None = None,
    temperature: float | None = None,
) -> BaseChatModel:
    """返回绑定到 ``node_name`` 对应档位的已配置 chat model。

    Args:
        node_name: 图节点名(见 ``config.NODE_TIERS``)。
        provider: 可选,覆盖默认 provider;不传则用 ``config.DEFAULT_PROVIDER``。
        temperature: 可选,覆盖默认温度;不传则用 ``config.DEFAULT_TEMPERATURE``。
            少数节点需要**确定性**输出:LangGraph 的 ``interrupt()`` 在 resume 时会
            从头重跑节点,被 interrupt 之前的 LLM 决策必须跨重跑保持一致,否则
            interrupt 的索引会错位。这类节点(如使命访谈的 ask/write 决策、Router
            的意图分类)传 ``temperature=0``。模型层仍是「唯一碰模型参数的地方」。
    """
    provider = provider or config.DEFAULT_PROVIDER
    if temperature is None:
        temperature = config.DEFAULT_TEMPERATURE
    model_name = model_name_for(node_name, provider)
    return _build(provider, model_name, temperature)
