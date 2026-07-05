# 项目概览(exploration 入口)

> 新会话请**先读本文件**,再按需跳转到下面的权威文档,避免重复扫读全仓。
> 本文件只做「导航 + 现状」,不重复各文档的内容细节。

## 这是什么

Self-Learning Agent:把已验证成功的 `teach` Claude Code skill **忠实移植**为一个基于 **LangGraph + Qwen** 的独立、可被 API 调用的教学智能体。教学法(Mission 驱动、ZPD、Knowledge/Skills/Wisdom、课程/参考文档/词汇表/学习记录)原封不动;开放的只有「独立化增量」(API、模型/工具、多租户、运行时)。

## 当前进度(2026-07-03)

- **移植 MVP + 流程/质量/记忆/语言对齐已完成**:教学图 + Lesson 创作子图、CLI 与 HTTP API 两个薄驱动、rubric 评分缝、Turn 级联(ADR-0010)、选题时刻/防重复/课程质量/资源充足/领域外新主题(ADR-0011)、三层记忆 + spacing(ADR-0012)、Workspace Language(ADR-0013)全部落地。
- **测试布局重组中**:旧测试目录与独立 eval 套件已移除(相关 eval ADR 已随之删除),新的测试布局待定。

## 权威文档地图(该读哪份)

| 想了解 | 读这份 |
|---|---|
| 产品规格 / 用户故事 / 范围 | `PRD.md` |
| 课程与 agent 质量 rubric(L1–L17 / P1–P7,LLM-facing) | `RUBRIC.md` |
| 领域词汇表(Mission/Lesson/ZPD/Turn…,canonical 语言) | `CONTEXT.md` |
| 架构决策(流程/质量见 0010/0011;记忆层/语言见 0012/0013;可观测见 0016) | `docs/adr/` |
| 代码级开发指南 | `CODE.md` |
| 运行 / 部署 / 运维 | `OPERATIONS.md` |
| 配置项 | `docs/config.md` |
| 仓内 agent 约定(issue 追踪 / triage / 领域) | `docs/agents/` |
| 移植源(只读参照,勿改) | `teach/`(SKILL.md + 4 个 FORMAT 文件) |

> 移植 MVP 的工作项已全部 done 并清档,现状以本文件「当前进度」为准。

## 架构一览

- **单张 LangGraph 教学图**(ADR-0001/0005,无 supervisor):
  `START → load_workspace → router → {mission | research | zpd | assessment | wisdom | new_topic} → finalize → END`,其中 `zpd → lesson → reference` 串联。Lesson 是 `起草→机器校验→自审→重写` 子图(ADR-0006)。开局 ZPD 出首课菜单 interrupt(#016);`new_topic` 确认后经 `spawn_topic` 由 driver 交接新主题(#014)。
- **状态三层**(ADR-0003):会话/图状态 → checkpointer(SQLite MVP);长期记忆 + 学习产物 → `workspaces/{user_id}/{topic_slug}/` 下的**普通文件(单一事实源)**。
- **模型可换旋钮**:`models.get_model(node)` 是唯一触模型点;`config.py` 里 per-node 档位路由(qwen-max/plus/turbo,可整体切 Claude)。
- **驱动**:`runner.invoke_turn` 是内核;`cli.py`(本地 REPL)与 `api.py`(FastAPI)是两个薄驱动(ADR-0004,API-first,agent 不管账号/鉴权/计费)。
- **代码位置**:`src/self_learning_agent/`。

## ⚠️ 安全提示

早期 scratch 文件 `llm-cif.md`(DashScope key)、`langsmith.md`(LangSmith key)曾以明文存放密钥,现已删除。这两个密钥**必须轮换**,并只经环境变量 / `.env`(已 gitignore)注入。
