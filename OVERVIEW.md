# 项目概览(exploration 入口)

> 新会话请**先读本文件**,再按需跳转到下面的权威文档,避免重复扫读全仓。
> 本文件只做「导航 + 现状」,不重复各文档的内容细节。

## 这是什么

Self-Learning Agent:把已验证成功的 `teach` Claude Code skill **忠实移植**为一个基于 **LangGraph + Qwen** 的独立、可被 API 调用的教学智能体。
教学法(Mission 驱动、ZPD、Knowledge/Skills/Wisdom、课程/参考文档/词汇表/学习记录)原封不动;开放的只有「独立化增量」(API、模型/工具、多租户、运行时)。

## 当前进度(2026-07-05)—— 重大重构中

**结论:此前的图编排过度复杂,是教学质量退化的根因。项目正重构为「单一通用 ReAct 智能体」。**

- **诊断**:同样的免费模型(Qwen/MiMo/MiniMax)在 Claude Code 里跑 `teach` prose 就能产出优质教学。
  Claude Code 本身就是一个通用 reason–act 循环,`teach` 只是注入其中的 prose。
  瓶颈**不是模型**,而是本移植把这个单一循环拆成了 16 个节点的状态机(11 节点教学图 + 5 节点 lesson 子图 + 确定性 router + 556 行 `validators.py` + 4 个 interrupt),刚性导致模型被约束得更差,且难以维护、eval 无法挂载。
- **目标架构**:一个 `create_react_agent`(system prompt = 忠实移植的 `teach` prose;工具 = 文件读写/列举/glob + web 搜索 + open-file)。
  mission/research/zpd/lesson/reference/assessment/wisdom 不再是节点,而是 prose 指挥同一个 agent 去做的事。
- **保留的外壳**:`runner.invoke_turn`(内核 + 唯一测试缝)、Workspace 即文件(记忆)、多租户、Langfuse、`spawn_topic`、turn 末产物 diff。
- **删除**:整张图 / lesson 子图 / `validators.py` / critique / Pydantic lesson schemas / 4 个 interrupt。运行时**不再有质量闸**。
- **质量搬到线下**:一个与运行时零耦合的黑盒 eval,经 `invoke_turn` 驱动、读产物文件、按 `RUBRIC.md` 用 LLM 评审、结果进 Langfuse。两个评测单元:课程产物 + 询问(interview)轮。
- **询问能力是唯一 `[ours]` 扩展**:`teach` 对询问质量沉默(优质询问是 Claude 即兴发挥),故显式补 prose(收集 目的→水平→约束;以「给具体选项」为战术)+ 一条**以结果为准**的 rubric。

**权威规格见 `PRD.md`(独立、可据以新开会话)。落地工单见 `.scratch/issues/001-*.md`。**

## 权威文档地图(该读哪份)

| 想了解 | 读这份 |
|---|---|
| 产品规格 / 用户故事 / 范围 / 删除清单(**新设计**) | `PRD.md` |
| 落地工单(ready-for-agent) | `.scratch/issues/001-collapse-to-single-agent.md` |
| 课程与 agent 质量 rubric(L1–L17 / P1–P7,LLM-facing;待补 interview 项) | `RUBRIC.md` |
| 领域词汇表(Mission/Lesson/ZPD/Turn…,canonical 语言) | `CONTEXT.md` |
| 仍然有效的架构决策 | `docs/adr/0002, 0003, 0004, 0007, 0012, 0016` |
| 仓内 agent 约定(issue 追踪 / triage / 领域) | `docs/agents/` |
| 移植源(只读参照,勿改) | `teach/`(SKILL.md + 4 个 FORMAT 文件) |

> 🗑️ **已删除**(描述被移除的图架构,勿在 git 历史里复活):
> ADR-0001 / 0005 / 0006 / 0010 / 0011(图 / lesson 子图 / cascade / interrupt)、ADR-0008(被 0016 取代)、
> ADR-0009(失败姿态,依赖已删的质量门)、ADR-0013(workspace 语言,前提是节点碎片化——单 agent 已消解)、
> `CODE.md`、`docs/config.md`。新的代码指南 / 配置说明随 `.scratch/issues/001` 落地时重写。

## ⚠️ 安全提示

早期 scratch 文件 `llm-cif.md`(DashScope key)、`langsmith.md`(LangSmith key)曾以明文存放密钥,现已删除。
这两个密钥**必须轮换**,并只经环境变量 / `.env`(已 gitignore)注入。
