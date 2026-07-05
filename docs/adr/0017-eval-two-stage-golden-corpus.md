# Eval 回归改两段式:live 生成与打分解耦,promptfoo 只对提交进仓库的 golden 语料打分

> **Status: 已弃用(2026-07-03)。** 独立 eval 套件(`eval/`、Golden Corpus、promptfoo)已整体移除,本 ADR 描述的两段式流水不再存在。保留此文件仅作历史决策记录;勿据它重建而不先另立新决策。

我们把生成式课程回归从「promptfoo 每条断言都直驱一次 live 多轮生成」改成**两段式**:
**Stage 1「刷新语料」**(live、偶发、容忍模型抖动)把每个 Gold Scenario 驱动到终局,把**整个课件工作区子树**快照成提交进仓库的 **Golden Corpus**;
**Stage 2「打分」**(快、确定、CI 常跑)让 promptfoo 只对 golden 快照跑断言,不再现场调模型生成。
本 ADR 精化 ADR-0015 的 provider 假设,并修掉 2026-07-03 那次「0 passed」全红跑暴露的一组接线与语义缺陷。

## 背景与理由

2026-07-03 的 `npx promptfoo eval` 三条用例全败(0 passed / 2 failed / 1 error,8m28s)。
复盘发现:**唯一真正生效的断言 `assert_rubric`(Q4 判断门)其实两节课都过了(均值 4.36 / 4.09)——活体 agent 产的课质量达标,失败全部来自 harness 的设计与接线缺陷。**
三类根因:

- **live 直驱把 harness 与模型抖动、与 agent bug 硬绑。**
  Row 0 报 ERROR 的直接原因是 agent **自己的** `_critique` 里 Qwen 返回的 `LessonCritique` 缺 `justification` 字段、pydantic 抛错冒泡,把整条 promptfoo 用例 crash 成 ERROR。
  一次坏的模型 turn = 一条用例报错而非记分;而且每条断言都各自重跑一遍完整 live 生成,3 条 test 因此耗时 8 分钟。

- **promptfoo 数组变量展开陷阱,叠加断言无类型守卫,把 Core Point 判成单字。**
  promptfoo 会把**数组型 var 自动展开成测试矩阵**:`core_points: [a,b,c]` 被展开成 3 条 test、每条 `core_points = 一个字符串`;
  `assert_core_points` 无 `isinstance(list)` 守卫,`for c in "字符串"` 遍历成单个汉字,再逐字送 judge → 纯噪声(reason 里“漏:['较','低','通',…]”)。
  “一节课是否命中全部 Core Point”的语义被彻底打碎。

- **工作区上下文被丢,确定性硬门结构性必挂。**
  `links_reachable` 与 `L6_citations` 挂,但产物(RESOURCES.md、assets/lesson.css、lessons/index.html)在盘上都真实存在。
  挂的原因是接线断:provider 把 `lesson_path` 放进 **metadata**,而 `assert_deterministic` 从 **`context["vars"]`** 读,永不相接 → 回退到占位路径 → 相对链接全不可达;`resources_md`/`glossary_md` 从头没人从工作区读出来塞进 vars → 恒为 `""` → 任何引用都判“不在 RESOURCES.md”。
  `validators.validate_lesson` 本是为**整个课件工作区**设计的,harness 只把单个 lesson HTML 穿过去,把其余上下文丢了。

这些缺陷共同说明:让 promptfoo 直驱 live 生成,把「生成」的不确定性/成本/脆弱性和「打分」的确定性诉求塞进同一次运行,是根问题。

## 决策

- **两段式:生成与打分解耦。**
  Stage 1 `refresh_corpus`(live)沿用 ADR-0015 的 Eval Transport + scripted Gold Scenario 机制,把每个场景驱动到声明终局,把交付课件的**整个工作区子树**快照到 `eval/corpus/<scenario_id>/`。
  Stage 2 `promptfoo eval` 的 provider 改为**读快照目录**(不调模型),把真实盘上 `lesson_path` + 从快照读回的 `RESOURCES.md`/`glossary` 交给断言。
  **ADR-0015 的 live-agent 覆盖没有丢——它移到了 Stage 1;只是把「live 运行」相对「打分」的时机挪开了。**

- **Golden Corpus:快照提交进仓库,刷新是一次被 review 的刻意动作。**
  `eval/corpus/` checked into repo。
  刷新流程:手动跑 `refresh_corpus` → `git diff` → 人评课件变化 → commit。
  于是 Stage 2 红灯只意味着两件事之一:**代码回归**,或 **judge 漂移**;绝不是模型随机。
  教学质量漂移以 **corpus diff** 的形式在 PR 里可见。CI 只跑 Stage 2,**无需模型密钥做生成**(judge 仍需模型,但不生成)。

- **Core Point 从场景文件按 id 加载,不走 promptfoo vars。**
  断言按 `scenario_id`(即快照目录名)从场景文件读回 `core_points` 整条 list(场景文件本就是单一事实源),vars 里删掉 `core_points` 与死变量 `is_skill_lesson`。
  这从根上绕开数组展开陷阱;再加 `isinstance(list)` 守卫兜底。

- **隔离与 teardown 各归其位。**
  Stage 2 只读语料、不调模型、不碰 live 工作区 → 并发竞态与陈旧残留自动消失。
  Stage 1 refresh **串行**跑、每场景独立工作区、跑完 teardown;单场景 error 用 try/except 报告并跳过,不中止整批刷新。

- **报告口径修正。**
  `run_regression.sh` 串起 Stage 2 + Q1 fixture 回归,区分「未跑 / 失败」,不再把「promptfoo 0 passed」当孤立头条——那会把「Q1 根本没跑」误报成「Q1 全败」。

## 考虑过的其它选项

- **保持 live 直驱、只修 bug(修数组展开+接线+加重试/隔离)。**
  否决:能修红,但把 8 分钟成本、每次 CI 要模型密钥、跨 run 抖动、以及「agent 一次坏 turn 崩掉整个 gate」这几件事全留着——它们是 live 直驱的固有代价,不是 bug。

- **live 直驱 + 结果缓存 + 坏 turn 重试。**
  否决:把 live 抖动压住,但没有 committed golden,就没有「drift 以 diff 形式被 review」这一层,红灯含义仍混着模型随机。

- **golden + nightly live 刷新告警。**
  保留为**后续可选增强**:PR 门用 committed golden(确定、阻断),另设 nightly 跑 `refresh_corpus` 与 golden 对比、把漂移当**告警而非阻断**、人工决定是否 update golden。本 ADR 先落 committed golden;nightly 雷达列入 roadmap。

## 影响

- **ADR-0015 的机制被复用而非推翻。** Eval Transport(in-process ↔ HTTP)、scripted Gold Scenario、response policies、声明终局全部保留:它们现在是 **Stage 1 的驱动器**。
  QA 的**部署验收**用例(把 transport 指向已部署服务、只跑 model-free 确定性门)与本 ADR 的**回归**用例是**两件不同的活**,共用 transport + 断言:验收天然是「对活体部署现产物打确定性门」,回归是「对 committed golden 确定性复现」。二者不要互相简化。
- **未来读者**若看到 promptfoo 的 provider 只读磁盘快照、不调模型,不要把它「改回」直驱 live 生成:那会把模型不确定性重新塞进打分阶段,正是本 ADR 要消除的。
- **Row 0 的 agent 侧脆弱性是独立发现,不属本 eval 设计**:建议 agent 侧让 `LessonCritique.justification` 容错(Optional/repair-on-parse),使自审在弱模型下 degrade 而非 crash(与 ADR-0009 一致——crash 不是优雅拒绝)。两段式后它只在手动 refresh 时咬人、不再阻断 CI。
- **同步纪律**沿用 ADR-0014/0015:`RUBRIC.md` 增删 L/P 或改判断/确定性标注时,`validation-cases.yaml`、`docs/validation-rubric.md`、场景语料一并更新;新增一条——**改 Gold Scenario 或 agent 生成逻辑后需重跑 `refresh_corpus` 并 review corpus diff**,否则 golden 会与活体 agent 分叉。
