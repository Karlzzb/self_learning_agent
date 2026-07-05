# 单轮内自动级联 teach 路径(图内条件边)

teach 在一段连续对话里,使命确立后会紧接着采集资源、交付第一课,一气呵成。为忠实承接这一**使用流程**,本智能体在**同一次 `graph.invoke()`(即一个 Turn,见 `CONTEXT.md`)内自动级联** teach 路径 `mission_establish → research → zpd → lesson → reference`,并用**图内条件边**表达。

## 背景与理由

改造前,图每条消息只跑一个能力节点(`mission→finalize`、`research→finalize`),导致「教我 X」到拿到第一课要学习者手动发约 3 条消息,偏离 teach 的连续体验。

取舍:

- **图内条件边(选定)**:控制流住在单张图里,忠于 ADR-0001/0005;一次 invoke = 一条 Langfuse trace(ADR-0016),可逐节点回放;**interrupt 边界"免费"获得**——mission 提问时 `interrupt()` 停在节点内、到不了 research,只有最后一问答完的那次 `resume` 才顺着下游边把 research→zpd→lesson 一路跑完。
- **驱动层循环(否决)**:runner 反复 invoke 直到无新产物,控制流泄到图外,不易 trace,偏离单一图原则。
- **新增 planner 调度节点(否决)**:近似 supervisor,与 ADR-0005 冲突。

## 级联边界(与 teach「一轮一课」对齐)

- **interrupt**(mission 访谈提问)暂停本轮,等学习者作答。
- **开局首课 interrupt**(见 ADR-0011):一个 topic 的**首课**(`lessons/` 尚无编号课时)在 ZPD 处 `interrupt()` 呈现 2–4 个候选首课,等学习者选定;`resume` 后才顺 `zpd→lesson→reference` 边生成「恰好一课」。「一轮一课」不变,只是在**首课**前插入一次选择 interrupt;**继续**(已有编号课)不出菜单、直出下一课。
- **research 找不到可信资源** → 停在诚实暂缓,不继续 zpd/lesson(承接 ADR-0009,不用 parametric knowledge 硬编一课)。
- **mission_establish 后一路到「恰好一课」**(lesson + reference)就 finalize,不连出多课(teach 一轮一个 tangible win,配合间隔/交错设计)。
- **mission_change 只确认**、更新使命 + 追加学习记录,**不**自动出新课(改使命是反思时刻)。
- **`new_topic` 跨主题交接边界**(见 ADR-0011):学习者请求**超出当前 mission 领域**的新主题时,cascade **不**在旧主题内继续;经确认 `interrupt()` 后本轮返回 `spawn_topic`、路由 finalize,由 driver 用新 `topic` 另起一次 invoke(新 `thread_id` / 新记忆目录)。这是继「research 暂缓」「mission_change 只确认」之后的第三类停止边界。

## 影响

- 实现是外科式的:把 `mission→finalize`、`research→finalize` 两条固定边换成条件边(据 `intent == "mission_establish"` 且资源状态 / research 是否成功,决定继续 teach 路径还是 finalize);Router 与既有 `zpd→lesson→reference` 链不动。
- API 语义不变:一次 invoke = 一个 Turn,返回至多一课的产物引用;interrupt 时返回提问、`awaiting_input=True`。
- CLI **不**新增自动开浏览器手势——本智能体 API-first,课程产物由调用方渲染呈现(承接 ADR-0004)。未来读者若想「顺手加个 open」,请注意这是刻意不做。
