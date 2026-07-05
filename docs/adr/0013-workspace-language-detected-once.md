# 工作区语言:检测一次、持久化、贯穿全局(不逐节点重猜、不加翻译步)

Status: accepted

`teach` 里目录语言天然一致,是因为它是一个连续的 Claude,把学习者的语言镜像到它写的每个文件——SKILL.md 从没写过"语言匹配"指令,一致性是 ambient 能力。
移植成离散节点后,每个节点各自从最后一句 human **重新猜**语言,且许多字段/产物(RESOURCES 条目、learning-record 标题正文、结构性 HTML chrome、索引、`<html lang>`、commit 回复)**压根没被交代**要跟随语言,于是"课程正文对、目录其余英文"。
本智能体改为:**在 Mission 确立时检测一次学习者语言,持久化为工作区事实(`Workspace Language`,见 `CONTEXT.md`),作为一个参数贯穿所有节点 prompt 与所有确定性渲染器。**

## 背景与理由

根因与 ADR-0012 同源:一个连贯 agent 被拆成碎片后,"语言"从隐性能力变成必须显式持久化 + 贯穿的参数(承接「架构第一,模型是旋钮」)。落地边界:

- **所有模型生成的内容**跟随工作区语言:课程正文、MISSION、learning-record 标题/正文(补上现缺的指令)、RESOURCES **注解**、glossary 词条、reference 字段。
- **RESOURCES 源的标题 + URL 原样保留**:它是资源的真实标识,翻译会失真;只有注解本地化。
- **结构性 chrome 文案**("Worked example""References""← All lessons"、索引标题、首课菜单、commit 回复)由**持久化语言码选一张 per-language 常量表**渲染,而**不是**翻译:内容本来就该以该语言产出,额外翻译步是多余复杂度。
- **`<html lang>`** 由持久化语言码设定,不再硬编 `"zh"`。
- **文件名 slug** 保持 native script(承接 `tenancy.topic_slug` 已有的"保留中文"决策);标题语言一致后,文件名自动一致(`0001-...中文` vs `0003-install-...` 的不一致本是标题语言不一致的症状,非 slug bug)。

## 取舍

- **检测一次 + 持久化 + 贯穿(选定)**:全目录一致、可审计、与 ADR-0003(文件即事实源)一致。
- **每节点各自重猜(否决)**:现状,节点间可能不一致,且遗漏字段无人管。
- **给 chrome 加一次性/每课翻译步(否决)**:多一个 LLM 动作,纯样板文案却要过模型,复杂且可漂移。chrome 用**有限语言集**的常量表(先 zh/en,按需加;未预置语言 chrome 回退英文,正文仍随语言)最省。

## 影响

- 新增"工作区语言"的检测 + 持久化缝(在 Mission 确立处),下游节点与渲染器读它。
- 确定性渲染器的硬编 chrome 文案抽成 per-language 常量表(有限集,英文兜底)。
- `research` / `assessment` / `reference` 等的 prompt 补齐"跟随工作区语言"的字段级指令(尤其现缺的 RESOURCES 条目注解与 learning-record 标题/正文)。
- 支持语言集是**刻意有限**的(未来读者勿"顺手加 i18n 翻译管线"——那是被否决的路)。
