"""TTL cache for processed command IDs."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict


class CommandCache:
    """Tracks recently processed commands for deduplication/replay protection."""

    def __init__(self, ttl_ms: int) -> None:
        self.ttl_ms = max(1, int(ttl_ms))
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, int] = OrderedDict()

    def _now_ms(self) -> int:
        return int(time.time() * 1000)

    def _prune_locked(self, now_ms: int) -> None:
        while self._entries:
            command_id, expires_at_ms = next(iter(self._entries.items()))
            if expires_at_ms > now_ms:
                break
            self._entries.pop(command_id, None)

    def contains(self, command_id: str) -> bool:
        now_ms = self._now_ms()
        with self._lock:
            self._prune_locked(now_ms)
            return command_id in self._entries

    def remember(self, command_id: str) -> None:
        now_ms = self._now_ms()
        expires_at_ms = now_ms + self.ttl_ms # store a commandId for TTL milliseconds
        with self._lock:
            self._prune_locked(now_ms)
            # Refresh entry TTL if command already exists.
            self._entries.pop(command_id, None)         # remove old commandId entry
            self._entries[command_id] = expires_at_ms   # insert new, fresh commandId entry

