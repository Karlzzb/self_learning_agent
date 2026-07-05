"""本地 CLI:MVP 的图驱动器(ADR-0004:CLI 是图的一个薄驱动器)。

用法::

    python -m self_learning_agent.cli --user alice --topic "AI 通识"

每行输入当作一条学习者消息,经 ``runner.invoke_turn`` 跑一遍图,打印回复与
本轮新产物引用。同一 ``(user, topic)`` 退出后重进可从 checkpointer 无损续接。

说明:这里的 ``print``/``input`` 是 REPL 的人机界面(产品功能),不是诊断日志。
"""

from __future__ import annotations

import argparse

from .runner import invoke_turn


def _print_result(result) -> None:
    print(f"\n智能体> {result.reply}")
    if result.new_artifacts:
        print("  本轮产物:")
        for relative in result.new_artifacts:
            print(f"    - {relative}")
    if result.awaiting_input:
        print("  (等待你的作答……)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Self-Learning Agent 本地 CLI")
    parser.add_argument("--user", required=True, help="学习者 ID(由调用方提供)")
    parser.add_argument("--topic", required=True, help="学习主题")
    args = parser.parse_args(argv)

    print(f"已进入会话:user={args.user} topic={args.topic!r}(输入空行或 Ctrl-D 退出)")
    current_topic = args.topic
    while True:
        try:
            message = input("\n你> ").strip()
        except EOFError:
            print()
            break
        if not message:
            break
        result = invoke_turn(args.user, current_topic, message)
        _print_result(result)
        # new_topic 交接(#014 / §D4):agent 确认领域外新主题后返回 spawn_topic;driver
        # 立即用新 topic 另起一次 invoke(新 thread / 新记忆),把学习者续到新主题的使命访谈,
        # 并把后续输入都切到这个新主题上。
        if result.spawn_topic:
            current_topic = result.spawn_topic
            print(f"\n（已切换到新主题:{current_topic!r}）")
            handoff = invoke_turn(args.user, current_topic, f"我想学{current_topic}")
            _print_result(handoff)


if __name__ == "__main__":
    main()
