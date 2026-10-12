# app/notifier.py
"""Escalation channel. Slack is already in BetterUp's stack, so humans are
paged there rather than through a new tool."""

from typing import Protocol


class Notifier(Protocol):
    def notify(self, channel: str, text: str) -> None: ...


class MockSlackNotifier:
    """Records messages instead of posting them.

    A real implementation would POST to a Slack incoming webhook
    (or chat.postMessage) with the same arguments.
    """

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def notify(self, channel: str, text: str) -> None:
        self.messages.append((channel, text))
