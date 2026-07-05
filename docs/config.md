# 配置指南

本智能体把「身份/密钥」与「模型选择」都做成外部可配置项:密钥由调用方/运营提供,
智能体永不自管;模型是一个可换的旋钮。本文档说明每一处需要密钥或可换模型的地方如何配置。

## 1. 准备 `.env`

```bash
cp .env.example .env
# 然后填入真实密钥
```

`.env` 已被 `.gitignore` 忽略,永不入库。源码中不含任何明文密钥。

## 2. 密钥一览

| 变量 | 用途 | 谁提供 |
| --- | --- | --- |
| `DASHSCOPE_API_KEY` | Qwen via DashScope/百炼 | 调用方/运营 |
| `ANTHROPIC_API_KEY` | 切到 Claude 时才需要 | 调用方/运营 |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Langfuse 逐节点链路追踪(self-hosted) | 运营/开发者 |

> 安全提醒:历史 scratch 文件 `llm-cif.md`(DashScope)、`langsmith.md`(LangSmith)曾以明文存放密钥,现已删除。
> **落地前请轮换这些密钥**,并只通过 `.env`(已 gitignore)注入。

## 3. 切换默认模型(一处生效)

默认走 Qwen。切换到另一个 provider 只需改 **一处**——环境变量 `LLM_PROVIDER`:

```bash
# .env
LLM_PROVIDER=qwen        # 默认
# 或
LLM_PROVIDER=anthropic   # 切到 Claude(需配置 ANTHROPIC_API_KEY)
```

任何业务节点代码都不需要改动。provider → 档位 → 模型名的映射集中在
`src/self_learning_agent/config.py` 的 `PROVIDER_TIER_MODELS`。

## 4. 逐节点模型档位(per-node routing)

每个图节点绑定一个档位(`STRONG` / `MID` / `LIGHT`),由
`src/self_learning_agent/config.py` 的 `NODE_TIERS` 决定。原则:重认知节点用最强档,
轻节点用便宜档。

| 节点 | 档位 | 说明 |
| --- | --- | --- |
| `router` | LIGHT | 意图分类,轻 |
| `mission_interview` | STRONG | 使命访谈(共情 + 追问) |
| `research` | MID | 资料检索与甄别 |
| `zpd` | STRONG | ZPD / 下一课规划 |
| `lesson` | STRONG | 课程创作(子图起草 + 自审) |
| `reference` | MID | 参考文档压缩(从已写好的课程蒸馏) |
| `assessment` | STRONG | 对话式评估 / 追问误解 |
| `wisdom` | STRONG | 实战智慧:尝试回答 + 甄别高声望社区 |
| `judge` | STRONG | LLM-as-judge 回归评分 |

未登记的节点回退到 `DEFAULT_TIER`(MID)。要给某节点换档,只改 `NODE_TIERS` 一行。
(学习记录写入是确定性动作,不调 LLM,故此表无 `records` 档。)

代码里取模型的唯一入口:

```python
from self_learning_agent.models import get_model

model = get_model("lesson")        # 用 lesson 节点对应的档位(默认 STRONG → qwen-max)
reply = model.invoke("ping")
```

## 5. 搜索层(可换搜索源)

搜索是教学图唯一的外部信息工具,藏在 `search(query) -> candidates` 接口后
(ADR-0007 极简工具面:不上 MCP、不上 RAG/向量库、不上 reranker)。

| 变量 | 用途 | 默认 |
| --- | --- | --- |
| `SEARCH_PROVIDER` | 选择搜索提供方 | `dashscope` |
| `SEARCH_MAX_RESULTS` | 单次检索候选条数上限 | `8` |

MVP 默认 `dashscope` = 百炼内置 `enable_search`,**不需要独立密钥**,复用
`DASHSCOPE_API_KEY`。唯一硬约束是**可达性**(查询面向全球,无数据出境限制;
Tavily 国内够不着,故不作默认)。

换搜索源有两种方式,业务节点都零改动:

```python
# 1) 运营态:改 env / config.SEARCH_PROVIDER,在 search._build_default_provider 登记新源
# 2) 进程内 / 测试:直接注入 provider
from self_learning_agent import search
search.set_provider(my_provider)   # 任意实现 SearchProvider.search 的对象
search.set_provider(None)          # 复位回默认
```

> 失败姿态(ADR-0009):搜索够不着时 provider **返回空列表**(或抛异常),Research
> 节点据此暂缓该课、坦白告知,**绝不**降级用脑补知识。

## 6. Langfuse 链路追踪(self-hosted)

观测后端是 self-hosted **Langfuse**(ADR-0016 取代 ADR-0008 的 LangSmith)。与 LangSmith
「纯环境变量、代码零接线」不同,Langfuse 走 LangChain 的**回调机制**——需要把一个
`CallbackHandler` 传进每次 `graph.invoke`。这处接线被收敛进 `observability.get_callbacks()`
一个缝,由唯一的图驱动内核 `runner.invoke_turn` 调用,业务节点零改动。

```bash
# .env
LANGFUSE_TRACING=true
LANGFUSE_HOST=http://10.15.231.165:13000
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
```

配好后,任意一轮 `/chat`(或 CLI 输入)都会在 Langfuse 里生成一条 trace,可逐节点看
prompt / 模型 / token / 耗时。把 `LANGFUSE_TRACING` 置空或 `false` 即关闭——此时
`get_callbacks()` 返回空列表且**完全不 import langfuse**,无依赖 / 未配置的环境零影响。
观测是旁路:缺依赖或初始化失败**不致命**,降级为「关闭 tracing + 一次告警」,不拖垮教学主流程。

## 7. 添加新 provider

1. 在 `config.PROVIDER_TIER_MODELS` 增加 `"<provider>": {STRONG/MID/LIGHT: 模型名}`。
2. 在 `models._build` 增加该 provider 的构造分支(读对应 `*_API_KEY`)。
3. `.env.example` 补上对应密钥占位。
