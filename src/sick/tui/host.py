from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sick.agent import SickAgent
    from sick.tui.chat import ChatView


class TurnHost:
    """Drives the agent's turn loop from the TUI.

    One background dispatcher task races ``queue_manager.race()``; each
    wake groups queue items by channel and hands them to
    ``agent.handle()``, then races again (blocking until the next input).
    Event subscriptions feed busy state to the chat.
    """

    def __init__(self, agent: SickAgent, chat: ChatView) -> None:
        self.agent = agent
        self.chat = chat
        self.busy = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self.agent.event_manager.on("BeforeTurn", self._on_before_turn)
        self.agent.event_manager.on("AfterTurn", self._on_after_turn)
        self._task = asyncio.create_task(self._dispatcher())

    def stop(self) -> None:
        try:
            self.agent.event_manager.off("BeforeTurn", self._on_before_turn)
        except Exception:
            pass
        try:
            self.agent.event_manager.off("AfterTurn", self._on_after_turn)
        except Exception:
            pass
        if self._task:
            self._task.cancel()

    def _in_git_repo(self) -> bool:
        import subprocess

        try:
            r = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True, timeout=3, cwd=self.agent.workspace,
            )
            return r.returncode == 0
        except Exception:
            return False

    def _on_before_turn(self, event) -> None:
        self._set_busy(True)

    def _on_after_turn(self, event) -> None:
        if event.is_final is not None:
            self._set_busy(not event.is_final)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.chat.set_busy(busy)

    async def _dispatcher(self) -> None:
        # Session-start checkpoint only inside a git repo: in a non-git
        # workspace it always fails, and those failures polluted the audit
        # log (and therefore /learn's "checkpoint fails most" lessons) on
        # every single launch.
        if "checkpoint" in self.agent.registry and self._in_git_repo():
            self.agent._call("checkpoint", message="session start")
        while True:
            try:
                items = await self.agent.queue_manager.race()
            except ValueError:
                return
            if not items:
                continue
            notification: dict[str, list] = defaultdict(list)
            for name, item in items:
                notification[name].append(item)
            try:
                await self.agent.handle(dict(notification))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Concise: the first line carries the actionable message
                # (provider error, iteration limit, ...). A 4000-char
                # traceback dump in chat helps nobody mid-session.
                msg = str(exc).strip().splitlines()[0][:400] if str(exc).strip() else type(exc).__name__
                self.chat.add_error(f"turn failed: {msg}")
            finally:
                self._set_busy(False)

    async def submit(self, text: str) -> None:
        self.agent._user_messages_in.put(text)