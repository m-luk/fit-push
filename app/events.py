"""Tiny synchronous event bus: the core announces changes, modules react.

A failing handler is logged and recorded against its owner; it never breaks
the core operation that emitted the event.

Events (payload keyword arguments):
    activity.imported   activity_id        new activity stored (upload or clip)
    activity.updated    activity_id, fields  name / sport / tags changed
    activity.deleted    activity_id
    settings.changed    settings
    segment.changed     segment_id         created, renamed, rescanned
    segment.deleted     segment_id
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable

log = logging.getLogger("fitpush.events")

EVENTS = (
    "activity.imported",
    "activity.updated",
    "activity.deleted",
    "settings.changed",
    "segment.changed",
    "segment.deleted",
)


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[tuple[str, Callable]]] = defaultdict(list)
        self.errors: dict[str, list[str]] = defaultdict(list)  # owner -> recent errors

    def on(self, event: str, handler: Callable, owner: str = "core") -> None:
        if event not in EVENTS:
            raise ValueError(f"unknown event {event!r}; known: {', '.join(EVENTS)}")
        self._handlers[event].append((owner, handler))

    def off_owner(self, owner: str) -> None:
        """Drop every handler of ``owner`` (used when a module fails to load)."""
        for event, handlers in self._handlers.items():
            self._handlers[event] = [(o, h) for o, h in handlers if o != owner]

    def emit(self, event: str, **payload) -> None:
        for owner, handler in list(self._handlers[event]):
            try:
                handler(**payload)
            except Exception as exc:
                log.exception("handler of %s from %s failed", event, owner)
                self.errors[owner] = (self.errors[owner] + [f"{event}: {exc}"])[-10:]
