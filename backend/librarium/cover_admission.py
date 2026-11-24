"""Image-admission slots shared by every source in a worker process, granted round-robin.

A plain semaphore serves requests in whatever order threads reach it. A source whose workers
re-request first keeps the slots, and a source with a few images that reached the queue later
finishes last. `Slots` keeps the same total ceiling but gives each freed slot to the source
served least recently, so every waiting source takes a turn before any takes a second. Within
one source, images keep their order.
"""

import threading
import time
from collections import deque


class Ticket:
    __slots__ = ("granted",)

    def __init__(self):
        self.granted = False


class Slots:
    def __init__(self, total):
        self._cond = threading.Condition()
        self._free = total
        self._total = total
        self._waiting: dict = {}  # source key -> deque of tickets, oldest first
        self._holding: dict = {}  # source key -> slots in use
        self._served: dict = {}  # source key -> serial of its latest grant
        self._serial = 0

    def waiting(self):
        with self._cond:
            return sum(len(queue) for queue in self._waiting.values())

    def enqueue(self, key):
        """Request a slot without blocking; the ticket is granted when one is free."""
        ticket = Ticket()
        with self._cond:
            self._waiting.setdefault(key, deque()).append(ticket)
            self._dispatch()
        return ticket

    def acquire(self, key, timeout):
        """Wait up to `timeout` seconds for a slot; False if none was granted."""
        deadline = time.monotonic() + max(0.0, timeout)
        ticket = self.enqueue(key)
        with self._cond:
            while not ticket.granted:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    queue = self._waiting[key]
                    queue.remove(ticket)
                    self._forget(key)
                    return False
                self._cond.wait(remaining)
        return True

    def release(self, key):
        with self._cond:
            if self._holding.get(key, 0) < 1:
                raise ValueError("Released a slot that was not held.")
            self._holding[key] -= 1
            self._free += 1
            self._forget(key)
            self._dispatch()

    def _dispatch(self):
        while self._free and self._waiting:
            # Least recently served first; sources never served go in arrival order.
            key = min(self._waiting, key=lambda k: self._served.get(k, 0))
            ticket = self._waiting[key].popleft()
            self._serial += 1
            self._served[key] = self._serial
            self._holding[key] = self._holding.get(key, 0) + 1
            self._free -= 1
            ticket.granted = True
            if not self._waiting[key]:
                del self._waiting[key]
            self._cond.notify_all()

    def _forget(self, key):
        """Drop an idle source so a long-lived worker keeps no record of finished searches."""
        if not self._waiting.get(key):
            self._waiting.pop(key, None)
            if not self._holding.get(key):
                self._holding.pop(key, None)
                self._served.pop(key, None)
