"""搜索层:``search(query) -> candidates``(ADR-0007 极简工具面)。

搜索是教学图里**唯一的外部信息工具**,被藏在一个可换接口后。Research 节点只说
「我要检索这个 query」,由本模块的当前 provider 决定怎么触网。换搜索提供方 =
改 ``config.SEARCH_PROVIDER`` / 调 ``set_provider``;业务节点一行不动(与「模型是
可换旋钮」同构)。

PRD「模型与工具」与 ADR-0007 的硬约束:
- 唯一硬约束是**可达性**(查询面向全球,无数据出境限制;Tavily 国内够不着,故
  MVP 默认走百炼内置 ``enable_search``)。
- **不上 MCP、不上 RAG/向量库、不上 reranker**。本模块只做「query 进、候选出」。

测试缝(见 ``conftest.search_director``):``search`` 是模块级函数,测试通过替换
provider 注入 mock 候选,**不打真实网络**——这让 Research 节点的甄别逻辑与失败
姿态都能离线、确定性地被验证。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from . import config


@dataclass(frozen=True)
class Candidate:
    """一条搜索候选(甄别前的**原始**结果,尚未判定是否高信任)。

    刻意做成贫血结构:只承载「让 Research 节点能甄别」所需的最小信息。是否高信任、
    归 Knowledge 还是 Wisdom、如何标注——都由 Research 节点(LLM + 确定性代码)决定,
    不在搜索层下判断。
    """

    title: str
    url: str
    snippet: str = ""


class SearchProvider(Protocol):
    """搜索提供方接口。换提供方只要实现这一个方法。"""

    def search(self, query: str, *, max_results: int) -> list[Candidate]:
        """对 ``query`` 检索,返回至多 ``max_results`` 条候选。

        约定:**够不着可信资料时返回空列表**(而非抛错或编造)。网络/服务级硬
        故障可以抛异常,由 Research 节点捕获后走「坦白告知、暂缓该课」的失败姿态
        (ADR-0009);两种情况 Research 都**绝不**降级用脑补知识。
        """
        ...


class DashScopeSearchProvider:
    """MVP 默认 provider:百炼内置 ``enable_search``(复用 DASHSCOPE_API_KEY)。

    实现策略:用 research 档模型 + ``enable_search=True`` 让模型**真的去联网检索**,
    并以结构化输出把检索到的候选(标题/链接/摘要)吐回来。这是把「百炼内置搜索」
    收敛进 ``search()`` 接口的最薄实现;甄别与高信任筛选不在这里做(归 Research 节点)。

    本 provider 是会触网的部分,故**不进单测套件**(与 ``models.get_model`` 的真实
    Qwen 调用一样,属人工/集成验收);单测通过替换 provider 注入 mock 候选。
    """

    def search(self, query: str, *, max_results: int) -> list[Candidate]:
        # 延迟导入:避免在纯离线单测(已替换 provider)里拉起模型层依赖。
        from langchain_core.messages import HumanMessage, SystemMessage
        from pydantic import BaseModel, Field

        from . import models

        class _Candidate(BaseModel):
            title: str = Field(description="Resource title, prefixed with its type, e.g. 'Book: ...'.")
            url: str = Field(description="The canonical URL of the source. Never invent one.")
            snippet: str = Field(default="", description="One line on what the source covers.")

        class _Candidates(BaseModel):
            candidates: list[_Candidate] = Field(default_factory=list)

        # enable_search 是 DashScope/百炼的请求级开关:让模型联网检索再作答。
        model = models.get_model("research").bind(extra_body={"enable_search": True})
        system = SystemMessage(
            "You are a search tool. Use web search to find real, high-quality sources "
            f"for the query. Return up to {max_results} candidates as structured output. "
            "Only include results you actually found via search; never fabricate URLs. "
            "If you cannot find trustworthy sources, return an empty list."
        )
        result: _Candidates = model.with_structured_output(_Candidates).invoke(
            [system, HumanMessage(query)]
        )
        return [
            Candidate(title=c.title, url=c.url, snippet=c.snippet)
            for c in result.candidates[:max_results]
        ]


def _build_default_provider() -> SearchProvider:
    """按 ``config.SEARCH_PROVIDER`` 构造默认 provider(系统边界 fail-fast)。"""
    if config.SEARCH_PROVIDER == "dashscope":
        return DashScopeSearchProvider()
    raise ValueError(
        f"未知 SEARCH_PROVIDER:{config.SEARCH_PROVIDER!r}。"
        f"请在 search._build_default_provider 中登记对应 provider。"
    )


# 模块级当前 provider(惰性构造)。测试用 set_provider 注入 mock。
_provider: SearchProvider | None = None


def get_provider() -> SearchProvider:
    """返回当前搜索 provider(首次调用时按 config 惰性构造)。"""
    global _provider
    if _provider is None:
        _provider = _build_default_provider()
    return _provider


def set_provider(provider: SearchProvider | None) -> None:
    """替换当前搜索 provider(传 ``None`` 恢复默认)。测试与运营换源都走这里。"""
    global _provider
    _provider = provider


def search(query: str, *, max_results: int | None = None) -> list[Candidate]:
    """对 ``query`` 检索候选——教学图里取搜索结果的**唯一入口**。"""
    if max_results is None:
        max_results = config.SEARCH_MAX_RESULTS
    return get_provider().search(query, max_results=max_results)


__all__ = [
    "Candidate",
    "SearchProvider",
    "DashScopeSearchProvider",
    "get_provider",
    "set_provider",
    "search",
]
