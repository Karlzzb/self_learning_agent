# 操作说明(部署 / 运行 / 运维)

本文档让你能**自行部署、运行、运维**这个独立教学智能体。
代码层面的「怎么改」见同目录的 `CODE.md`;配置细节另见 `docs/config.md`;产品决策见 `PRD.md` 与 `docs/adr/`。

> 一句话定位:这是一个承接 `teach` skill 的独立教学智能体,跑在 LangGraph + Qwen 上。
> 它**不**自管账号 / 鉴权 / 计费——身份由调用方传入的 `user_id` / `topic` 决定。

---

## 1. 环境要求

- Python ≥ 3.10。
- 一个 DashScope(百炼)API Key(默认模型与默认搜索都用它)。
- 可选:Anthropic Key(切到 Claude 时)、Langfuse Key(self-hosted 链路追踪)。
- 操作系统无特殊要求(纯 Python;数据落本地文件 + SQLite)。

本机已存在一个 conda 环境 `self_learning_agent`(Python 3.10)。

---

## 2. 安装

```bash
# 在仓库根目录
pip install -e .            # 安装运行时依赖
pip install -e ".[dev]"     # 额外装测试依赖(pytest / httpx)
```

依赖在 `pyproject.toml` 声明,核心是 `langgraph` / `langchain-core` / `langchain-openai`(走 Qwen 的 OpenAI 兼容端点)/ `fastapi` / `uvicorn`。

---

## 3. 配置密钥

```bash
cp .env.example .env
# 编辑 .env,至少填 DASHSCOPE_API_KEY
```

`.env` 已被 `.gitignore` 忽略,永不入库;源码中不含明文密钥。

最小可运行配置只需一行:

```bash
DASHSCOPE_API_KEY=sk-你的真实key
```

完整变量清单见 `.env.example` 与本文档第 7 节。

> **安全提醒(落地前必做)**:历史 scratch 文件 `llm-cif.md`、`langsmith.md` 曾以明文存放密钥,现已删除。
> 部署前请**轮换这些密钥**,并只通过 `.env`(已 gitignore)注入。

---

## 4. 运行方式 A:本地 CLI

CLI 是图的一个薄驱动器,适合单用户验证教学引擎。

```bash
python -m self_learning_agent.cli --user alice --topic "AI 通识"
```

每行输入当作一条学习者消息,跑一遍图,打印回复与本轮新产物。
同一 `(user, topic)` 退出后重进,会从 checkpointer **无损续接**(几天后回来也一样)。

---

## 5. 运行方式 B:HTTP API

API 与 CLI 是**同一张图**的两个薄驱动器(ADR-0004)。
生产形态 = 被其他系统调用的 API。

启动:

```bash
uvicorn self_learning_agent.api:app --host 0.0.0.0 --port 8000
```

交互式文档(FastAPI 自带):打开 `http://localhost:8000/docs`。

### 能力面

| 方法 & 路径 | 作用 |
| --- | --- |
| `POST /chat` | 发一条 `(user_id, topic)` 消息 → 取回复 + 本轮产物引用 |
| `GET /artifacts` | 列出某学习者某主题的全部产物(课程 / 参考 / 词汇表 / 使命 / 记录 / 资源 / 资产) |
| `GET /artifacts/content` | 下载单个产物的原始字节(如课程 HTML) |
| `GET /status` | 只读状态:当前 Mission、已有课程、学习记录 |
| `DELETE /workspace` | 删除 / 重置某工作区(严格限定在该 `(user_id, topic)` 命名空间) |
| `GET /export` | 把整个工作区打包成 zip(备份 / 迁移 / 让学习者带走数据) |

### 调用示例

```bash
# 对话
curl -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"alice","topic":"AI 通识","message":"我想学神经网络"}'

# 列产物
curl "http://localhost:8000/artifacts?user_id=alice&topic=AI%20通识"

# 下载一节课
curl "http://localhost:8000/artifacts/content?user_id=alice&topic=AI%20通识&path=lessons/0001-xxx.html"

# 查进度
curl "http://localhost:8000/status?user_id=alice&topic=AI%20通识"

# 重置工作区
curl -X DELETE "http://localhost:8000/workspace?user_id=alice&topic=AI%20通识"
```

`POST /chat` 的响应形如 `{"reply": "...", "new_artifacts": ["lessons/0001-...html", ...], "awaiting_input": false, "spawn_topic": null}`。
`awaiting_input=true` 表示图停在一道提问上(如使命访谈或开局首课菜单),调用方应把回复当问题展示,下一条 `/chat` 消息会被当作该问题的作答(自动 resume)。
`spawn_topic` 非空表示学习者被引导到一个**领域外新主题**(#014):服务端已自动用该新 `topic` 续接一次并返回其结果,调用方后续 `/chat` 都应改用这个新 `topic`。

> 鉴权由调用方负责:本服务直接信任传入的 `user_id`。
> 生产中务必在本服务前置你自己的鉴权 / 限流网关,不要把它直接暴露公网。

---

## 6. 数据落在哪里

三层状态(A / B / C)、两种持久化机制(ADR-0003):

| 层 | 内容 | 位置 | 配置项 |
| --- | --- | --- | --- |
| 会话 / 图状态(A) | 对话历史、interrupt、轮内中间态 | `./checkpoints/teach.sqlite` | `TEACH_CHECKPOINT_DB` |
| 长期记忆 + 学习产物(B/C) | `workspace.json`(工作区语言)/ `MISSION.md` / `RESOURCES.md` / `GLOSSARY.md` / `NOTES.md`(Learner Notes)/ `learning-records/` / `lessons/`(含 `manifest.json` 台账)/ `reference/` / `assets/` | `./workspaces/{user_id}/{topic_slug}/` | `TEACH_WORKSPACES_ROOT` |

**工作区文件是 B/C 层的单一事实源**;课程、词汇表、使命、学习记录都是普通文件,可直接查看、备份、迁移。
多租户隔离靠 `workspaces/{user_id}/{topic_slug}/` 命名空间(`topic_slug` 由 `tenancy.topic_slug` 从主题文本稳定推导,保留中文)。

备份 = 备份 `workspaces/` 与 `checkpoints/` 两个目录即可。

---

## 7. 配置速查(环境变量)

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `LLM_PROVIDER` | `qwen` | 默认模型 provider;改一处全局生效(`qwen` / `anthropic`) |
| `LLM_TEMPERATURE` | `0.7` | 所有节点默认温度 |
| `DASHSCOPE_API_KEY` | — | Qwen via DashScope(必填) |
| `DASHSCOPE_BASE_URL` | 百炼兼容端点 | OpenAI 兼容端点地址 |
| `ANTHROPIC_API_KEY` | — | 仅 `LLM_PROVIDER=anthropic` 时需要 |
| `SEARCH_PROVIDER` | `dashscope` | 搜索源(默认 = 百炼内置 `enable_search`,复用 DashScope key) |
| `SEARCH_MAX_RESULTS` | `8` | 单次检索候选上限 |
| `RESEARCH_MAX_QUERIES` | `5` | Research 多查询采集的查询数上限(#018,覆盖 mission 关键子主题) |
| `TEACH_SPACING_REVIEW_DAYS` | `7` | 间隔复习阈值:Coverage Ledger 里授课超过该天数的课列为「该复习」,派生信号喂 ZPD(ADR-0012) |
| `TEACH_WORKSPACES_ROOT` | `./workspaces` | 工作区根目录 |
| `TEACH_CHECKPOINT_DB` | `./checkpoints/teach.sqlite` | 会话状态库 |
| `LESSON_MAX_ATTEMPTS` | `3` | Lesson 子图重写上限(达上限不达标则不交付) |
| `LESSON_CRITIQUE_MIN_ITEM` | `3` | 自审 / judge:每个判断条目最低分 |
| `LESSON_CRITIQUE_MIN_MEAN` | `4.0` | 自审 / judge:判断条目均值阈值 |
| `JUDGE_CALIBRATION_WITHIN_ONE` | `0.8` | LLM-judge 对齐人评的逐项达标线 |
| `JUDGE_CALIBRATION_DECISION_AGREEMENT` | `0.8` | LLM-judge 对齐人评的判定达标线 |
| `TEACH_RUBRIC_PATH` | 仓库根 `RUBRIC.md` | 权威评分依据位置 |
| `TEACH_JUDGE_SAMPLES_DIR` | `scoring/samples` | 评分回归样本集位置 |
| `LANGFUSE_TRACING` | `false` | 开/关链路追踪(置 `true` 启用 Langfuse) |
| `LANGFUSE_HOST` | `http://10.15.231.165:13000` | self-hosted Langfuse 地址 |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | — | Langfuse 密钥(运营/开发者提供) |

切换默认模型只改 `LLM_PROVIDER` 一处,业务代码零改动;逐节点档位的权威来源是 `src/self_learning_agent/config.py` 的 `NODE_TIERS`(机制说明见 `docs/config.md`)。

---

## 8. 可观测性(self-hosted Langfuse)

观测后端是 self-hosted **Langfuse**(ADR-0016 取代 ADR-0008 的 LangSmith)。它走 LangChain 回调机制,由 `observability.get_callbacks()` 在唯一的图驱动内核 `runner.invoke_turn` 处接线,业务节点零改动。
在 `.env` 配好 `LANGFUSE_TRACING=true` + `LANGFUSE_HOST` + `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` 后,每一轮 `/chat`(或 CLI 输入)都会在 Langfuse 里生成一条 trace,可逐节点看 prompt / 模型 / token / 耗时。
置 `LANGFUSE_TRACING=false`(或留空)即关闭——此时 `get_callbacks()` 返回空列表且完全不 import langfuse,无依赖 / 未配置的环境零影响。观测是旁路:缺依赖或初始化失败不致命,降级为「关闭 tracing + 一次告警」(ADR-0009 姿态)。

---

## 9. 测试

测试布局重组中:旧测试目录已移除,新布局待定。
测试历来是 **hermetic** 的——模型调用与搜索都替换成确定性 fake,不触真实网络,故本地无密钥也能跑全套。
重建测试目录后在此登记跑法(`pytest`)。

---

## 10. 课程质量回归监控

课程质量由架构保证(机器校验 + 对照 RUBRIC 自审),并有一条独立的评分缝做回归监控:

```python
from self_learning_agent import scoring
cal = scoring.run_calibration()     # 跑 LLM-judge over 固定样本,与人评对齐
print(cal.within_one, cal.decision_agreement, cal.calibrated)
```

样本集与人评标注在 `scoring/samples/`(`manifest.json` + 各 HTML)。
判断条目阈值与课内自审同源(每项 ≥ `LESSON_CRITIQUE_MIN_ITEM`,均值 ≥ `LESSON_CRITIQUE_MIN_MEAN`)。
注意:真实跑 judge 会调模型(消耗 DashScope 额度)。

---

## 11. 生产化要点

- **会话状态从 SQLite 换 Postgres**:只改 `graph._default_checkpointer`(ADR-0003 已为此预留;图结构不动)。
- **工作区上对象存储**:MVP 用本地文件;逻辑模型不变,延后(见 PRD「Out of Scope」)。
- **多副本部署**:对话端点以 `thread_id = f(user_id, topic_slug)` 为键;若多副本共享同一 checkpointer / 工作区,需保证它们指向同一持久化后端(共享卷或共享 Postgres)。
- **前置网关**:鉴权 / 计费 / 限流由调用方在本服务之前完成(本服务永不自管)。
- **失败姿态(ADR-0009)**:搜索够不着或质量门兜底时,智能体**坦白告知、暂缓该课**,绝不脑补;一切硬故障先保证 checkpointer 已存档、可无损续学。

---

## 12. 故障排查

| 症状 | 可能原因 / 处理 |
| --- | --- |
| 启动即报 `缺少 DASHSCOPE_API_KEY` | `.env` 未配或未被加载;确认在仓库根运行,`.env` 存在 |
| 课程迟迟不交付、回复「请稍后再来」 | 质量门重试耗尽(`LESSON_MAX_ATTEMPTS`)或搜索够不着资源——这是**设计内的失败姿态**,非崩溃;查 Langfuse trace 看哪一步不达标 |
| 回复里 `awaiting_input=true` 但调用方没接住 | 这是 interrupt(如使命访谈提问);下一条 `/chat` 消息会被当作作答自动 resume |
| 中文主题目录名变成连字符串 | 正常:`topic_slug` 归一了空白 / 标点,保留中文;同一主题恒映射同一目录 |
| 想换搜索源 | 改 `SEARCH_PROVIDER` 并在 `search._build_default_provider` 登记,或进程内 `search.set_provider(...)`;业务节点零改动 |
