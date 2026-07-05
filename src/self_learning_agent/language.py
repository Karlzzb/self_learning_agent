"""Workspace Language:检测一次的语言码 + 确定性 chrome 常量表(承接 ADR-0013)。

`teach` 寄居 Claude Code 时,目录语言天然一致——一个连贯的 Claude 把学习者的语言
镜像到它写的每个文件。移植成离散节点后,语言从「隐性 ambient 能力」退化为「每节点
各自重猜」。ADR-0013 的对策:**在 Mission 确立时检测一次**学习者语言,持久化为工作区
事实(``CONTEXT.md`` 的 **Workspace Language**),作为一个参数贯穿所有节点与渲染器。

本模块提供该决策的两块纯确定性原语,均**不触模型**(ADR-0013 明确否决 i18n 翻译管线):

- ``detect_language``:据学习者文本判语言码(先支持 zh/en 的有限集;未命中回退英文)。
  它是「检测一次」的确定性兜底——正常路径由 Mission 模型在写 MISSION.md 时顺带报出
  语言码(它本就在用该语言写作,报码零额外调用),此处兜住模型未给码的情形。
- chrome 常量表:结构性模板文案(「动手练习」「参考资料」「← 返回全部课程」等)按持久化
  语言码从 ``CHROME`` 取,而**不是**翻译——这些文案本就该以该语言产出,额外翻译步是
  多余复杂度。支持语言是**刻意有限集**(未来读者勿「顺手加 i18n 翻译管线」——那是被
  否决的路);未预置语言的 chrome 回退英文,正文仍随语言。
"""

from __future__ import annotations

import re

# 支持语言集**刻意有限**(ADR-0013):先 zh/en,按需扩表。未预置语言的 chrome 回退英文。
DEFAULT_LANGUAGE = "en"

# 语言码 → 英文语言名(供 prompt 里向模型点名目标语言;#021 / ADR-0013)。未预置语言
# 直接回退用语言码本身作名字(模型仍能据 ISO 码写作),不引入翻译步。
LANGUAGE_NAMES: dict[str, str] = {"en": "English", "zh": "Chinese"}


def language_name(lang: str | None) -> str:
    """把语言码渲染成给模型看的语言名(有限集;未预置回退语言码本身)。

    仅用于**发给 LLM 的英文 prompt**里点名「用哪种语言写学习者可见文本」——它把持久化的
    Workspace Language 显式交给生成节点,取代「每节点从最后一句 human 重新猜」(ADR-0013)。
    """
    code = lang or DEFAULT_LANGUAGE
    return LANGUAGE_NAMES.get(code, code)

# CJK 表意文字区间(含扩展 A 与兼容区):命中即判中文。检测器是「据学习者输入语言检测
# 一次」的确定性兜底,不求覆盖所有语言——只需在有限集内稳定区分 zh 与其余(回退英文)。
_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def detect_language(text: str) -> str:
    """据一段学习者文本返回 Workspace Language 码(有限集;未命中回退英文)。

    纯确定性、无模型调用:含 CJK 表意文字 → ``"zh"``,否则 ``DEFAULT_LANGUAGE``。
    这是「检测一次」的兜底路径(模型通常在写 MISSION.md 时顺带报出语言码);两条路径
    都收敛到同一个持久化的 Workspace Language 事实,下游不再逐节点重猜。
    """
    if text and _CJK.search(text):
        return "zh"
    return DEFAULT_LANGUAGE


# === chrome 常量表(结构性模板文案,按语言码取,不翻译)========================
# 每种语言一张扁平表;键是渲染器引用的 chrome 槽位,值是该语言的文案。新增语言只需
# 加一张同键表(缺失语言由 ``chrome`` 回退英文)。这些是课程/索引 HTML 的确定性骨架
# 文案(非模型产内容),与「正文随语言由模型产出」分工:内容走模型、chrome 走此表。
CHROME: dict[str, dict[str, str]] = {
    "en": {
        "worked_example_heading": "Worked example",
        "takeaway_label": "Takeaway:",
        "practice_heading": "Try it yourself",
        "expected_result_label": "Expected result:",
        "hint_summary": "Hint",
        "primary_source_label": "Primary source:",
        "references_heading": "References",
        "source_link": "[source]",
        "all_lessons_nav": "\u2190 All lessons",
        "quiz_correct": "\u2713 Correct.",
        "quiz_wrong": "\u2717 Not quite \u2014 try again.",
        "lessons_title": "Lessons",
        "no_lessons": "No lessons yet.",
        # 参考文档索引 / 卡片的结构性 chrome(#021:reference 渲染器不再硬编中英)。
        "references_index_title": "References",
        "no_references": "No reference documents yet.",
        "all_references_nav": "\u2190 All references",
        "lessons_nav": "Lessons",
        # 开局首课菜单(#021:菜单 chrome 由持久化语言码取,不再硬编中文)。
        "menu_intro": "Here are a few directions we could start your first lesson with \u2014 which would you like to learn first?",
        "menu_recommended": " (recommended)",
        "menu_objective_label": "Goal:",
        "menu_why_label": "Why:",
        "menu_mission_label": "Ties to your mission:",
        "menu_choose_hint": "Reply with a number (1-{count}) to choose, or just tell me what you'd rather start with.",
        # 确定性的智能体可见回复 / 兜底(#021:模型给了 reply 时优先用模型的;此表是
        # 「怎么都不为空」的语言一致兜底,以及纯确定性回复如 commit / 首课菜单的骨架)。
        "lesson_commit_reply": "I've written this lesson for you: {title}. It passed the quality gate (deterministic checks + self-review against the rubric) \u2014 you can open it and start learning.",
        "lesson_defer_reply": "I haven't polished this lesson to a standard I'm comfortable delivering yet, so I won't hand over a sub-par version. I'll keep improving it \u2014 please come back a little later. Your progress is saved and won't be lost.",
        "research_done_reply": "I've curated the high-trust learning resources for this topic and written them into RESOURCES.md.",
        "research_defer_unreachable_reply": "I can't reach any trustworthy learning material online right now, so I'll hold off on starting the lesson \u2014 I'd rather wait until I find high-quality primary sources than hand you unverified content. Please check back later.",
        "research_defer_no_trust_reply": "I found some material, but none of it met the trust bar I need to teach from, so I'm holding this lesson. I'll keep looking for more authoritative primary sources \u2014 please check back later.",
        "mission_fallback_question": "Why do you want to learn this? Tell me what would change in your work or life once you have this skill.",
        "mission_establish_reply": "I've recorded your learning mission. Let's begin.",
        "mission_change_reply": "Done \u2014 I've updated your learning mission.",
        "mission_decline_reply": "No problem \u2014 we'll keep your current learning mission.",
        "assessment_fallback_reply": "Thanks for sharing that. Let's keep going.",
        "wisdom_fallback_reply": "This one is best tested in the real world. I'll give you my take, and I'd also suggest taking it to a high-reputation community to verify \u2014 I'll keep looking for a good one for you.",
        "new_topic_decline_reply": "No problem \u2014 let's stay with your current topic.",
        "new_topic_confirm_question": "This looks like a new topic, \u201c{topic}\u201d, different from your current direction. Would you like me to start a separate learning workspace for it?",
        "new_topic_accept_reply": "Great \u2014 let's start a separate learning workspace for \u201c{topic}\u201d. Beginning now.",
    },
    "zh": {
        "worked_example_heading": "\u793a\u4f8b\u8bb2\u89e3",
        "takeaway_label": "\u8981\u70b9\uff1a",
        "practice_heading": "\u52a8\u624b\u7ec3\u4e60",
        "expected_result_label": "\u9884\u671f\u7ed3\u679c\uff1a",
        "hint_summary": "\u63d0\u793a",
        "primary_source_label": "\u4e00\u624b\u8d44\u6e90\uff1a",
        "references_heading": "\u53c2\u8003\u8d44\u6599",
        "source_link": "[\u6765\u6e90]",
        "all_lessons_nav": "\u2190 \u8fd4\u56de\u5168\u90e8\u8bfe\u7a0b",
        "quiz_correct": "\u2713 \u56de\u7b54\u6b63\u786e\u3002",
        "quiz_wrong": "\u2717 \u8fd8\u5dee\u4e00\u70b9 \u2014 \u518d\u8bd5\u4e00\u6b21\u3002",
        "lessons_title": "\u8bfe\u7a0b",
        "no_lessons": "\u8fd8\u6ca1\u6709\u8bfe\u7a0b\u3002",
        # 参考文档索引 / 卡片的结构性 chrome(#021)。
        "references_index_title": "\u53c2\u8003\u6587\u6863",
        "no_references": "\u8fd8\u6ca1\u6709\u53c2\u8003\u6587\u6863\u3002",
        "all_references_nav": "\u2190 \u8fd4\u56de\u5168\u90e8\u53c2\u8003",
        "lessons_nav": "\u8bfe\u7a0b",
        # 开局首课菜单(#021)。
        "menu_intro": "\u6211\u4eec\u53ef\u4ee5\u4ece\u4e0b\u9762\u51e0\u4e2a\u65b9\u5411\u5f00\u59cb\u4f60\u7684\u7b2c\u4e00\u8bfe\uff0c\u4f60\u60f3\u5148\u5b66\u54ea\u4e00\u4e2a\uff1f",
        "menu_recommended": " \uff08\u63a8\u8350\uff09",
        "menu_objective_label": "\u76ee\u6807\uff1a",
        "menu_why_label": "\u4e3a\u4ec0\u4e48\uff1a",
        "menu_mission_label": "\u4e0e\u4f60\u7684\u4f7f\u547d\uff1a",
        "menu_choose_hint": "\u56de\u590d\u5e8f\u53f7\uff081-{count}\uff09\u6765\u9009\u62e9\uff0c\u6216\u76f4\u63a5\u8bf4\u4f60\u66f4\u60f3\u5148\u5b66\u4ec0\u4e48\u3002",
        # 确定性的智能体可见回复 / 兜底(#021)。
        "lesson_commit_reply": "\u6211\u5df2\u7ecf\u4e3a\u4f60\u5199\u597d\u8fd9\u8282\u8bfe\uff1a{title}\u3002\u8bfe\u7a0b\u5df2\u901a\u8fc7\u8d28\u91cf\u95e8\uff08\u673a\u5668\u6821\u9a8c + \u5bf9\u7167\u8bc4\u5206\u6807\u51c6\u81ea\u5ba1\uff09\uff0c\u4f60\u53ef\u4ee5\u6253\u5f00\u5b66\u4e60\u4e86\u3002",
        "lesson_defer_reply": "\u8fd9\u8282\u8bfe\u6211\u8fd8\u6ca1\u6253\u78e8\u5230\u53ef\u4ee5\u653e\u5fc3\u4ea4\u4ed8\u7684\u7a0b\u5ea6\uff0c\u5148\u4e0d\u4ea4\u4ed8\u672a\u8fbe\u6807\u7684\u7248\u672c\u2014\u2014\u6211\u4f1a\u518d\u6539\u8fdb\uff0c\u4f60\u53ef\u4ee5\u7a0d\u540e\u518d\u6765\u3002\u4f60\u7684\u5b66\u4e60\u8fdb\u5ea6\u5df2\u7ecf\u4fdd\u5b58\uff0c\u4e0d\u4f1a\u4e22\u5931\u3002",
        "research_done_reply": "\u6211\u5df2\u7ecf\u6574\u7406\u597d\u8fd9\u4e2a\u4e3b\u9898\u7684\u9ad8\u4fe1\u4efb\u5b66\u4e60\u8d44\u6e90\uff0c\u5199\u8fdb\u4e86 RESOURCES.md\u3002",
        "research_defer_unreachable_reply": "\u6211\u6682\u65f6\u8054\u7f51\u67e5\u4e0d\u5230\u53ef\u4fe1\u7684\u5b66\u4e60\u8d44\u6599\uff0c\u5148\u4e0d\u6025\u7740\u5f00\u8bfe\u2014\u2014\u7b49\u6211\u627e\u5230\u9ad8\u8d28\u91cf\u7684\u4e00\u624b\u8d44\u6e90\u518d\u7ee7\u7eed\uff0c\u514d\u5f97\u7ed9\u4f60\u672a\u7ecf\u6838\u5b9e\u7684\u5185\u5bb9\u3002\u4f60\u53ef\u4ee5\u7a0d\u540e\u518d\u6765\u3002",
        "research_defer_no_trust_reply": "\u6211\u641c\u5230\u4e86\u4e00\u4e9b\u8d44\u6599\uff0c\u4f46\u6ca1\u6709\u4e00\u6761\u8fbe\u5230\u53ef\u4ee5\u653e\u5fc3\u6559\u5b66\u7684\u53ef\u4fe1\u6807\u51c6\uff0c\u6240\u4ee5\u5148\u6682\u7f13\u8fd9\u8282\u8bfe\u3002\u6211\u4f1a\u7ee7\u7eed\u627e\u66f4\u6743\u5a01\u7684\u4e00\u624b\u8d44\u6e90\uff0c\u4f60\u53ef\u4ee5\u7a0d\u540e\u518d\u6765\u3002",
        "mission_fallback_question": "\u4f60\u4e3a\u4ec0\u4e48\u60f3\u5b66\u8fd9\u4e2a\uff1f\u8bf4\u8bf4\u5b83\u4f1a\u6539\u53d8\u4f60\u5de5\u4f5c\u6216\u751f\u6d3b\u91cc\u7684\u4ec0\u4e48\u3002",
        "mission_establish_reply": "\u5df2\u8bb0\u5f55\u4f60\u7684\u5b66\u4e60\u4f7f\u547d\u3002\u6211\u4eec\u6b63\u5f0f\u5f00\u59cb\u3002",
        "mission_change_reply": "\u597d\u7684\uff0c\u6211\u5df2\u7ecf\u66f4\u65b0\u4e86\u4f60\u7684\u5b66\u4e60\u4f7f\u547d\u3002",
        "mission_decline_reply": "\u597d\u7684\uff0c\u6211\u4eec\u4fdd\u7559\u5f53\u524d\u7684\u5b66\u4e60\u4f7f\u547d\u3002",
        "assessment_fallback_reply": "\u8c22\u8c22\u4f60\u7684\u53cd\u9988\u3002\u6211\u4eec\u7ee7\u7eed\u5f80\u4e0b\u5b66\u5427\u3002",
        "wisdom_fallback_reply": "\u8fd9\u4e2a\u95ee\u9898\u66f4\u9700\u8981\u5728\u771f\u5b9e\u4e16\u754c\u91cc\u68c0\u9a8c\u3002\u6211\u5148\u8bf4\u8bf4\u6211\u7684\u770b\u6cd5\uff0c\u4e5f\u5efa\u8bae\u4f60\u62ff\u5230\u4e00\u4e2a\u9ad8\u58f0\u671b\u7684\u793e\u533a\u53bb\u9a8c\u8bc1\u2014\u2014\u6211\u4f1a\u7ee7\u7eed\u5e2e\u4f60\u7269\u8272\u5408\u9002\u7684\u793e\u533a\u3002",
        "new_topic_decline_reply": "\u597d\u7684\uff0c\u6211\u4eec\u7ee7\u7eed\u5f53\u524d\u7684\u5b66\u4e60\u4e3b\u9898\u3002",
        "new_topic_confirm_question": "\u8fd9\u770b\u8d77\u6765\u662f\u4e00\u4e2a\u65b0\u4e3b\u9898\u300c{topic}\u300d\uff0c\u548c\u4f60\u5f53\u524d\u7684\u5b66\u4e60\u65b9\u5411\u4e0d\u540c\u3002\u8981\u4e3a\u5b83\u5355\u72ec\u5efa\u7acb\u4e00\u4e2a\u5b66\u4e60\u6863\u6848\u5417\uff1f",
        "new_topic_accept_reply": "\u597d\u7684\uff0c\u6211\u4eec\u4e3a\u300c{topic}\u300d\u5355\u72ec\u5efa\u7acb\u4e00\u4e2a\u5b66\u4e60\u6863\u6848\uff0c\u73b0\u5728\u5f00\u59cb\u3002",
    },
}


def chrome(lang: str | None) -> dict[str, str]:
    """返回某语言码的 chrome 文案表;未预置语言回退英文(ADR-0013:有限集 + 英文兜底)。"""
    return CHROME.get(lang or DEFAULT_LANGUAGE, CHROME[DEFAULT_LANGUAGE])


__all__ = [
    "DEFAULT_LANGUAGE",
    "LANGUAGE_NAMES",
    "detect_language",
    "language_name",
    "chrome",
    "CHROME",
]
