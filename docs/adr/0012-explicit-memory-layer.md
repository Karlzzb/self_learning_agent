# 显式记忆层:补偿宿主智能体的 ambient 对话记忆

Status: accepted

`teach` 寄居在 Claude Code,靠**整段对话上下文 + Claude 自身的推理记忆**记住学习者卡在哪、偏好什么、问过什么,从而让每一课贴合——它甚至不需要显式记录"疑问/卡点",因为一切都在 context 里。
移植成离散 LangGraph 节点后,真正生成课程的节点(`zpd` / `lesson` / `reference`)基本是**失忆**地工作:只拿到工作区文件 + 最后一句 human,拿不到对话历史。
为忠实承接 teach 的**课程质量**(连续、承接、个性化)而不依赖宿主的 ambient memory,本智能体**显式区分三层记忆**并把它们喂进生成节点。

## 背景与理由

问题①("后续课程不连续 / 重复")的最深根因不是"少了某个字段",而是**移植版的记忆架构比 Claude Code 弱得多,却没有刻意补偿**(承接「架构第一,模型是旋钮」:记忆管理本身就是架构)。三层记忆各司其职:

- **Coverage Ledger**(`lessons/manifest.json`,#015):**教过什么**。每次 Lesson commit 必写,与是否评估无关。防重复只依赖这一层——因此"一直只说下一课"也不会重复。
- **Learning Record**(`learning-records/`):**学会什么**。证据级,忠实 teach 的四类证据(understanding / prior_knowledge / misconception_corrected / mission_shift)。补回 `teach/LEARNING-RECORD-FORMAT.md` 的可选段 **Implications / Evidence / Status**(前瞻信号 + supersession),但**触发纪律不变**(覆盖≠学会)。
- **Learner Notes**(`NOTES.md`):**偏好 / 节奏 / 反复卡点 / 未解决疑问 / 系统背景**。teach 里它只是"可有可无的 scratchpad"(和 Claude ambient memory 双保险);移植版两样都没有,故它在此**升级为承重记忆层**,是 ambient memory 的**显式替身**。学习者"哪些有疑问"落在这里,而**不**往 learning-records 硬塞第五类证据。

## 取舍

- **显式三层记忆 + 喂进生成节点(选定)**:可持久、可审计、跨会话;不破坏 teach 的证据级纪律。
- **往 learning-records 加"疑问/卡点"第五类证据(否决)**:把软信号硬塞进决策级记录,破坏 P6「证据级、非流水账」纪律。
- **每次 commit 自动写一条 learning-record(否决)**:把"教过"当成"学会",直接违背 P6(覆盖≠学会)。
- **只靠把完整对话历史喂给节点(部分采纳,不够)**:最贴近 Claude ambient memory,但每轮 token 成本高、且无跨会话持久性。可作为补充,但真正的沉淀靠显式 Learner Notes。

## 影响

- `NOTES.md` 从 teach 的"可选 scratchpad"升级为移植版的**承重记忆层**;缺它,生成节点失忆、课程质量退化。它需要一个滚动更新的写入缝(何时写由教学判断,怎么写是确定性原语,承接 ADR-0003)。
- `zpd` / `lesson` / `mission` 的 prompt 新增 **Learner Notes 注入**(连同已有的 Coverage Ledger 与 Learning Records)。
- learning-records 的格式与 prompt 补 **Implications / Evidence / Status**,承接 `teach/LEARNING-RECORD-FORMAT.md:17-46` 的可选段与 supersession;触发条件与确定性证据闸门不动。
- "评估被意图路由边缘化"(学习者很少走 `assess`,故 learning-records 常空)由本层结构缓解:Coverage Ledger 与 Learner Notes 都**不**依赖 `assess` 意图,故生成节点始终有承接信号,不必为"让记录被写"而降低证据门。
- **间隔复习(spacing)靠同一记忆层落地**:teach 的 desirable difficulty 含 spacing,原本靠 Claude 的 ambient memory 判断"该复习什么"。移植版用 **Coverage Ledger + 每条的时间信息**派生一个"该复习什么"的信号喂给 ZPD/draft,把 spacing 从隐性判断变成显式机制。这是"用显式记忆层补偿 ambient memory"在 spacing 上的具体应用,不是新教学法(retrieval 已由课内 quiz 落地,interleave 已在 draft prompt)。
