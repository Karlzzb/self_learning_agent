# 验证 rubric:把质量 rubric 投影到评价四象限,机械生成 promptfoo 用例

> **Status: 已弃用(2026-07-03)。** 独立 eval 套件(`eval/`、promptfoo 编排、`docs/validation-rubric.md`)已整体移除,本 ADR 描述的子系统不再存在。保留此文件仅作历史决策记录;勿据它重建 promptfoo 回归而不先另立新决策。

我们把课程质量的**回归测试**建成 `RUBRIC.md` 的一个**投影层**,而非另起一套评价标准。
每个 L 条目按「是否有逐样本标准答案 × 代码客观 vs LLM 判官」落进一个评价象限,并附上机械生成 promptfoo 用例所需的元数据。
被测对象是**课程产物**(一节生成出来的 Lesson);promptfoo 只做编排与报告,断言全部**复用**现有的 `validators.py` 与 `scoring.py`,不重写评分逻辑,`RUBRIC.md` 一字不动。

## 背景与理由

`RUBRIC.md`(L1–L17 / P1–P7)已经沿一条轴——**确定性(代码)vs 判断性(LLM)**——审计并归类了每条标准,并配了阈值(每项≥3、均值≥4.0)、逐字 judge 提示(`lesson_critique_system()`)、确定性校验器(`validators.py`)、以及一个人评校准语料(`scoring/samples/`)。我们采用的「智能体评价体系」多出**第二条轴**——**是否存在逐样本标准答案(GT)**——把评价面切成 2×2 四象限。设计取舍如下:

- **投影而非新建。** 若另立一套评价维度,会与 `RUBRIC.md` 分叉,违反仓库「一处定义、三处复用」原则(课内自审 / 人评 / LLM-judge)。故验证 rubric 只**决定每条 L 如何被行使**(落哪个象限、复用哪个检查、样本从哪来),不重定义任何分数。
- **被测对象 = 课程产物,provider 生成式。** promptfoo 的 python provider 直连 `runner.invoke_turn`,喂 **Gold Scenario**(固定 mission+scope)现场生成新课,再从 `new_artifacts` 读回 Lesson HTML。这测的是**活体 agent 的教学质量漂移**,而非固定夹具。
- **四象限落位:**
  - **Q3(无GT·代码)** 通用规则 → promptfoo `python` 断言直接 import `validators.py` 的 `check_*`(L6/L7/L9/L12/L13/L17 + HTML/链接/结构),全部 100% 通过为硬门。
  - **Q4(无GT·LLM)** 通用 rubric → promptfoo `python` 断言包裹 `scoring.judge_lesson`,复用逐字 `RUBRIC.md`,套 `passes_threshold`(每项≥3 且均值≥4.0)。
  - **Q2(有GT·LLM)** 每 Gold Scenario 预设 2–4 个 **Core Point**(单课不可省的定义性要件),LLM 数命中,阈值=全命中。GT 来自**场景**而非样本输出,因此对生成式仍适用。
  - **Q1(有GT·代码)** 精确逐样本比对**对生成内容不适用**(生成天生有变异,且 L7「最高质量一手源」是判断而非唯一解),故对生成式 SUT 显式标 **N/A**;该象限改由一个 **fixture 回归**小套件承载——把 `scoring/samples/`(strong/medium/weak)与 validators 夹具当作带已知 pass/fail 标签的样本,断言 `check_*` 复现已知结果。
- **确定性策略:** 生成与评分都用低温/确定档,每 Gold Scenario 单跑,直接套上述硬门;残余抖动靠判断项 ±1 容差(沿用 `within_one` 校准思路)吸收,不做 N 跑取多数(太贵)。
- **不塞进 RUBRIC.md。** `scoring.judgement_item_ids()` 用正则解析 `RUBRIC.md` 决定哪些项被 judge 打分,且有测试钉死这 11 项集合。任何测试元数据若写进 `RUBRIC.md` 会干扰该解析,故元数据落在独立侧车 `eval/validation-cases.yaml`,由生成脚本消费。
- **v1 范围:** 只做 L 层(课程产物 SUT)。P1–P7 是 Turn/节点级行为标准,属第二 SUT,列入后续 roadmap。

## 影响

- 这是**刻意的「promptfoo 包裹自家检查器/judge、而非用其原生 `llm-rubric`/`python` 重写标准」**:未来读者若看到断言只是薄薄地转调 `validators.py`/`scoring.py`,不要将其当作冗余去改成原生 promptfoo 断言——那会把 rubric 文本复制进 YAML,和单一事实源分叉。
- **Q1 对生成式标 N/A 是刻意的**,不是遗漏:精确比对被移到 fixture 回归套件,那里逐样本标签才成立。
- **Core Point 只防漏、不奖广度**,与 L4/L5/L14 的极简教学法一致;编写 Gold Scenario 时若把 Core Point 列成一份子主题清单,就走偏了。
- `eval/validation-cases.yaml`(机读侧车)+ `docs/validation-rubric.md`(人读映射表)+ 生成脚本三者需与 `RUBRIC.md` 的 L 条目集合保持同步;`RUBRIC.md` 增删条目或改判断/确定性标注时,侧车与 `docs/validation-rubric.md` 要一并更新。
