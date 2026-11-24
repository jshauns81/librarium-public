"""Deterministic scheduling tests for the shared image-admission slots. No network, no clock."""

import threading
import uuid
from collections import deque
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from librarium import cover_admission
from librarium import cover_sources as sources


def order(slots, grants):
    """Keys in the order their tickets were granted, given (key, ticket) pairs."""
    return [key for key, ticket in grants if ticket.granted]


def test_total_ceiling_is_unchanged_and_excess_waits():
    slots = cover_admission.Slots(3)
    tickets = [slots.enqueue("a") for _ in range(4)]
    assert [t.granted for t in tickets] == [True, True, True, False]
    assert slots.waiting() == 1
    slots.release("a")
    assert tickets[3].granted and slots.waiting() == 0


def test_freed_slot_goes_to_a_waiting_small_source_before_the_big_sources_next_image():
    slots = cover_admission.Slots(3)
    big = [slots.enqueue("big") for _ in range(6)]
    small = [slots.enqueue("small") for _ in range(2)]
    assert [t.granted for t in big] == [True] * 3 + [False] * 3
    assert not any(t.granted for t in small)
    slots.release("big")
    assert small[0].granted and not big[3].granted


def test_each_waiting_source_gets_a_turn_before_any_gets_a_second():
    slots = cover_admission.Slots(1)
    holder = slots.enqueue("holder")
    waiting = [(k, slots.enqueue(k)) for k in ["a", "a", "a", "b", "b", "c"]]
    granted = []
    slots.release("holder")
    for _ in range(len(waiting)):
        newly = next((k, t) for k, t in waiting if t.granted and (k, t) not in granted)
        granted.append(newly)
        slots.release(newly[0])
    assert holder.granted
    assert [k for k, _ in granted] == ["a", "b", "c", "a", "b", "a"]


def test_images_of_one_source_keep_their_order():
    slots = cover_admission.Slots(1)
    slots.enqueue("busy")
    first, second = slots.enqueue("a"), slots.enqueue("a")
    slots.release("busy")
    assert first.granted and not second.granted


def test_timed_out_waiter_is_withdrawn_and_never_leaks_a_slot():
    slots = cover_admission.Slots(1)
    slots.enqueue("a")
    assert slots.acquire("b", timeout=0) is False
    assert slots.waiting() == 0
    slots.release("a")
    assert slots.acquire("c", timeout=0) is True
    slots.release("c")


def test_release_without_a_grant_is_refused():
    with pytest.raises(ValueError):
        cover_admission.Slots(2).release("a")


def replay(sources_spec, hold, grant):
    """Virtual-time replay of per-source worker pools contending for 3 slots.

    Model, not live latency. Assumptions: each image holds a slot for `hold` seconds;
    a source's three workers each request a slot when its metadata arrives and again
    whenever one of its images finishes. `grant` decides who gets a freed slot.
    Returns each source's finish time and the peak number of slots in use.
    """
    events, now, seq = [], 0.0, 0
    state = {name: {"backlog": n, "left": n} for name, (_, n) in sources_spec.items()}
    finish, peak, held = {}, 0, 0
    pending = []

    def request(name):
        state[name]["backlog"] -= 1
        pending.append((name, grant.request(name)))

    def dispatch():
        nonlocal held, peak
        for name, ticket in list(pending):
            if ticket.granted:
                pending.remove((name, ticket))
                held += 1
                peak = max(peak, held)
                events.append((now + hold, seq_next(), "done", name))

    def seq_next():
        nonlocal seq
        seq += 1
        return seq

    for name, (arrives, _) in sources_spec.items():
        events.append((arrives, seq_next(), "arrive", name))
    while events:
        events.sort()
        now, _, kind, name = events.pop(0)
        if kind == "arrive":
            for _ in range(min(3, state[name]["backlog"])):
                request(name)
        else:
            held -= 1
            state[name]["left"] -= 1
            grant.release(name)
            if state[name]["left"] == 0:
                finish[name] = now
            if state[name]["backlog"]:
                request(name)
        dispatch()
    return finish, peak


class ArrivalOrder:
    """Reference model of the old plain semaphore: free slots go to the oldest request."""

    def __init__(self, total):
        self.free, self.queue = total, deque()

    def request(self, name):
        ticket = SimpleNamespace(granted=False)
        self.queue.append(ticket)
        self._grant()
        return ticket

    def release(self, name):
        self.free += 1
        self._grant()

    def _grant(self):
        while self.free and self.queue:
            self.queue.popleft().granted = True
            self.free -= 1


class RoundRobin:
    def __init__(self, total):
        self.slots = cover_admission.Slots(total)

    def request(self, name):
        return self.slots.enqueue(name)

    def release(self, name):
        self.slots.release(name)


WORKLOAD = {"large-1": (2.0, 6), "large-2": (3.0, 6), "large-3": (3.5, 6), "small": (4.1, 4)}


def test_small_source_that_arrives_last_finishes_last_under_arrival_order():
    finish, peak = replay(WORKLOAD, 5.0, ArrivalOrder(3))
    assert peak == 3
    assert max(finish, key=finish.get) == "small"
    assert finish["small"] == 42.0


def test_round_robin_lets_the_small_source_finish_before_the_large_ones_it_queued_behind():
    before, _ = replay(WORKLOAD, 5.0, ArrivalOrder(3))
    after, peak = replay(WORKLOAD, 5.0, RoundRobin(3))
    assert peak == 3
    assert after["small"] == 32.0 < before["small"]
    assert after["small"] < after["large-2"] and after["small"] < after["large-3"]
    # Fairness moves finish times between sources; it does not add or remove work.
    assert max(after.values()) == max(before.values()) == 42.0


@pytest.fixture
def lease(monkeypatch):
    manager = Mock()
    manager.filter.return_value.exists.return_value = True
    monkeypatch.setattr(sources, "CoverSearch", SimpleNamespace(objects=manager))


def test_real_workers_give_a_waiting_small_source_the_next_free_slot(lease, monkeypatch):
    """The production path: one source holds all slots with more queued, another arrives."""
    slots = cover_admission.Slots(3)
    monkeypatch.setattr(sources, "_admission_slots", slots)
    cond, started, gates = threading.Condition(), [], {}

    def admit(item, *args):
        gate = threading.Event()
        with cond:
            gates[item["n"]] = gate
            started.append(item["n"])
            cond.notify_all()
        assert gate.wait(10)

    def until(predicate):
        # `Slots` does not notify this test's condition, so poll with the lock released.
        for _ in range(2000):
            with cond:
                if predicate():
                    return
            threading.Event().wait(0.005)
        pytest.fail("condition not reached")

    def search(query, source, *args):
        count, base = (6, 0) if source == "apple" else (2, 100)
        return {
            "state": "results",
            "candidates": [
                {
                    "src": sources.SOURCES[source],
                    "title": "Synthetic One",
                    "author": "Example Writer",
                    "urls": ["https://assets.hardcover.app/cover.jpg"],
                    "n": base + n,
                }
                for n in range(count)
            ],
        }

    monkeypatch.setattr(sources, "admit", admit)
    monkeypatch.setattr(sources, "source_search", search)
    row = SimpleNamespace(
        pk=uuid.uuid4(),
        entry=SimpleNamespace(title="Synthetic One", facts={}),
        request={},
        query={"title": "Synthetic One", "author": "Example Writer", "isbn": ""},
        candidates=[],
    )
    threads = [
        threading.Thread(target=sources._run_source, args=(row, uuid.uuid4(), source))
        for source in ("apple", "hardcover")
    ]
    threads[0].start()
    until(lambda: len(started) == 3)
    threads[1].start()
    until(lambda: slots.waiting() == 2)
    gates[0].set()
    until(lambda: len(started) == 4)
    assert started[3] >= 100, "the freed slot went to the large source's next image"
    while len(started) < 8 or len(gates) < 8 or not all(g.is_set() for g in gates.values()):
        with cond:
            for gate in gates.values():
                gate.set()
            cond.wait(0.01)
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()
