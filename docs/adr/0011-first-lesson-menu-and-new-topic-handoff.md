# 开局首课菜单 + `new_topic` 跨主题交接

一个 topic **开局**时,ZPD 不再静默单选,而是产出 2–4 个候选首课 + 推荐,经 `interrupt()` 呈现给学习者选择;学习者请求**领域外新主题**时,由 **driver 代理交接**(agent 返回 `spawn_topic`、driver 用新 `topic` 重新 invoke)另起新档案,而非在旧 workspace 内硬切。

## 背景与理由

移植后出现两处相对 `/teach` 的流程回归:

1. **选题时刻消失**。`/teach` §ZPD 的做法是"学习者可指定确切要学的东西;不指定则由 agent 算 ZPD",且这套推理是**对话式呈现**给学习者的——学习者真实体验到的"opencv 那种丰富选项"正来自此。移植版的 ZPD 节点被指令"Scope exactly ONE tightly-scoped thing"(`prompts.py`),静默选一个 scope、`rationale`/`mission_link` 只进图状态学习者看不到,并被 ADR-0010 的 `zpd→lesson` 级联一口气吃掉。选题时刻因此丢失。
2. **记忆外新主题无路可走**。router 只有 mission_change / assess / wisdom / teach 四类,新领域请求落到 `teach` → zpd,被错误 scope 回旧 mission;且 `topic` 每次 invoke 固定,没有在会话内另起新主题的机制,表现为"创建失败、流程不自动"。

## 决策

- **开局首课菜单**:ZPD 在**开局**(`workspace.next_lesson_number(dir) == 1`,即尚无编号课)产出结构化 `FirstLessonMenu { candidates: list[NextLessonScope], recommended: int }`(2–4 项,按"解锁最多、最贴 mission 关键路径"排序),用 `interrupt()` 以学习者语言呈现候选(含推荐标记 + 每项 rationale/mission_link);`resume` 收到选择后设 `next_lesson_scope` 并顺边生成"恰好一课"。**继续**(已有编号课)仍单选、直出下一课,保留 ADR-0010 单轮体验。
  - 边界解析:开局若学习者**已点名一个紧凑的具体首课**,honour 之、跳过菜单(承接 §ZPD "may specify an exact thing");否则出菜单。
- **`new_topic` 交接**:router 增第五类 `new_topic`(请求明显超出当前 mission 领域,区别于"同主题换 why"的 mission_change 与"mission 内下一课"的 teach)。命中后进确认节点 `interrupt()` 与学习者确认新主题名;确认则本轮返回 `spawn_topic=X`、路由 finalize、**不**在旧 workspace 写入;`runner.invoke_turn` 把 `spawn_topic` 透出 `TurnResult`,`cli.py`/`api.py` 立即用 `topic=X` 再调一次,新主题走自己的 `mission→research→首课菜单`。

## 取舍

- **首课菜单用 ZPD 内 interrupt(选定)**:控制流住在单图内、承接 ADR-0001/0005;interrupt 边界"免费"获得(承接 ADR-0010),`resume` 才顺边出课。否决"驱动层循环选题"(控制流泄到图外)。
- **`new_topic` 用 driver 代理交接(选定)**:`thread_id = user::topic_slug`,新 slug 自动得到干净的新 checkpoint 线程 + 新 `workspaces/{user}/{slug}/` 记忆,一主题一线程不被污染;交接留在 driver 层,承接 ADR-0004(agent 不自管会话)。
  - **否决 图内直接切 `topic_slug`**:`thread_id` 本轮已按旧 topic 算好,checkpoint 会把两主题对话纠缠在同一线程,破坏一主题一线程模型。
  - **否决 仅提示学习者自开新会话**:不自动、体验差,违背"确认后直接开启"。

## 影响

- **实现**:ZPD 节点分开局/继续两路(判定为纯文件事实,不加新状态位);新增 `FirstLessonMenu` 结构化输出与 interrupt 呈现;router 五分类 + `_route` 增 `new_topic` 分支 + 确认节点;`TurnResult` 增 `spawn_topic` 字段;cli/api 增交接续调。`_ZPD_INSTRUCTION`、`_ROUTER_INTENT_INSTRUCTION` 的增补按 PRD §Prompt 架构规矩在代码注释标原文段落 + 原因。
- **API 语义**:一次 invoke 仍 = 一个 Turn;开局首课那轮返回菜单提问、`awaiting_input=True`;`new_topic` 确认轮返回确认提问,确认后由 driver 自动续上新主题(对调用方是一次逻辑交互、两次 invoke)。
- **忠实性**:两项都是把 `/teach` 已有、移植时丢失的对话行为补回,不改教学法。
- **ADR-0010** 已补入这两条级联/停止边界。
