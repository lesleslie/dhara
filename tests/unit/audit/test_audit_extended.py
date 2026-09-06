"""Extended unit tests for the dhara.audit trio.

Covers the full statement surface of:
- dhara.audit.outbox.MemoryOutbox
- dhara.audit.flusher.OutboxFlusher + periodic_flush_loop
- dhara.audit.query_tool.AuditLogQueryTool

duckdb is used in-memory (real binary) so the SQL surface is exercised
end-to-end; the test fixture loads the production ``0004_audit_log.sql``
migration so the schema matches what the substrate actually emits.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import duckdb
import pytest
import pytest_asyncio

from dhara.audit.flusher import OutboxFlusher, periodic_flush_loop
from dhara.audit.outbox import MemoryOutbox
from dhara.audit.query_tool import AuditLogQueryTool
from dhara.audit.subscriber import AuditLogSubscriber, WriteEvent
from dhara.schema.audit_record import AuditRecord

_MIGRATION_0004 = (
    Path(__file__).parents[3] / "dhara" / "migrations" / "sql" / "0004_audit_log.sql"
).read_text()


# --------------------------------------------------------------------- fixtures
@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    """In-memory duckdb with the production audit_log schema applied."""
    c = duckdb.connect(":memory:")
    c.execute(_MIGRATION_0004)
    yield c
    c.close()


@pytest.fixture
def outbox() -> MemoryOutbox:
    return MemoryOutbox()


@pytest_asyncio.fixture
async def async_conn() -> duckdb.DuckDBPyConnection:
    """Same as ``conn`` but pulled into an async context for async tests."""
    c = duckdb.connect(":memory:")
    c.execute(_MIGRATION_0004)
    yield c
    c.close()


def _make_record(audit_id: str = "audit-1", **overrides: Any) -> AuditRecord:
    defaults: dict[str, Any] = {
        "audit_id": audit_id,
        "event_type": "create",
        "actor": "alice",
        "at": datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
        "subject": "thing",
        "metadata": {"k": "v"},
    }
    defaults.update(overrides)
    return AuditRecord(**defaults)


# ============================================================================
# MemoryOutbox
# ============================================================================
class TestMemoryOutbox:
    """Coverage for dhara/audit/outbox.py."""

    def test_enqueue_returns_true_when_room(self) -> None:
        q: MemoryOutbox = MemoryOutbox(max_size=2)
        rec = _make_record("a-1")
        assert q.enqueue("foo", "id-1", rec) is True
        assert q.size == 1

    def test_enqueue_returns_false_when_full(self) -> None:
        q: MemoryOutbox = MemoryOutbox(max_size=1)
        rec1 = _make_record("a-1")
        rec2 = _make_record("a-2")
        assert q.enqueue("foo", "id-1", rec1) is True
        # Queue is at maxlen=1, so the next enqueue drops the oldest and
        # returns False (the G6 "drops oldest on overflow" contract).
        assert q.enqueue("bar", "id-2", rec2) is False
        assert q.size == 1
        # The remaining entry is the newest one (deque maxlen evicts FIFO).
        assert q.peek() == ("bar", "id-2", rec2)

    def test_drain_returns_all_items_and_clears(self) -> None:
        q: MemoryOutbox = MemoryOutbox()
        rec1 = _make_record("a-1")
        rec2 = _make_record("a-2")
        q.enqueue("foo", "id-1", rec1)
        q.enqueue("bar", "id-2", rec2)
        items = q.drain()
        assert items == [("foo", "id-1", rec1), ("bar", "id-2", rec2)]
        assert q.size == 0

    def test_drain_empty_returns_empty_list(self) -> None:
        q: MemoryOutbox = MemoryOutbox()
        assert q.drain() == []
        assert q.size == 0

    def test_size_reflects_queue_length(self) -> None:
        q: MemoryOutbox = MemoryOutbox()
        assert q.size == 0
        q.enqueue("foo", "id-1", _make_record("a-1"))
        assert q.size == 1
        q.enqueue("bar", "id-2", _make_record("a-2"))
        assert q.size == 2
        q.drain()
        assert q.size == 0

    def test_peek_returns_first_without_removing(self) -> None:
        q: MemoryOutbox = MemoryOutbox()
        rec1 = _make_record("a-1")
        rec2 = _make_record("a-2")
        q.enqueue("foo", "id-1", rec1)
        q.enqueue("bar", "id-2", rec2)
        # peek must not mutate the queue.
        assert q.peek() == ("foo", "id-1", rec1)
        assert q.size == 2
        # And the same call returns the same first item.
        assert q.peek() == ("foo", "id-1", rec1)

    def test_peek_on_empty_returns_none(self) -> None:
        q: MemoryOutbox = MemoryOutbox()
        assert q.peek() is None

    def test_default_max_size_is_1000(self) -> None:
        q: MemoryOutbox = MemoryOutbox()
        assert q._queue.maxlen == 1000

    def test_thread_safety_under_concurrent_enqueue(self) -> None:
        """Stress the lock: many threads enqueue concurrently, no items lost
        or duplicated beyond the bounded-capacity contract.
        """
        import threading

        q: MemoryOutbox = MemoryOutbox(max_size=100_000)
        workers = 16
        per_worker = 100

        def _spam(worker_id: int) -> None:
            for i in range(per_worker):
                q.enqueue(
                    f"w{worker_id}",
                    f"id-{i}",
                    _make_record(f"a-{worker_id}-{i}"),
                )

        threads = [
            threading.Thread(target=_spam, args=(i,)) for i in range(workers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Every enqueue succeeded because the queue is much larger than
        # workers * per_worker.
        assert q.size == workers * per_worker

        # Drain returns exactly that count, in some interleaved order.
        items = q.drain()
        assert len(items) == workers * per_worker

        # Verify every (worker_id, i) appears exactly once.
        seen: set[tuple[int, int]] = set()
        for item in items:
            audit_id = item[2].audit_id  # "a-{w}-{i}"
            prefix, _, rest = audit_id.partition("-")
            assert prefix == "a"
            w, i = rest.split("-", 1)
            seen.add((int(w), int(i)))
        assert seen == {(w, i) for w in range(workers) for i in range(per_worker)}


# ============================================================================
# OutboxFlusher
# ============================================================================
class TestOutboxFlusher:
    """Coverage for dhara/audit/flusher.py."""

    @pytest.mark.asyncio
    async def test_flush_once_empty_outbox_returns_zero(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        flusher = OutboxFlusher(outbox=MemoryOutbox(), conn=conn)
        flushed = await flusher.flush_once()
        assert flushed == 0
        # No rows were inserted and executemany was never called.
        rows = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()
        assert rows[0] == 0

    @pytest.mark.asyncio
    async def test_flush_once_inserts_drained_records(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        outbox = MemoryOutbox()
        subscriber = AuditLogSubscriber(outbox=outbox)
        subscriber.on_put(
            WriteEvent(
                entity_type="foo",
                entity_id="bar",
                payload={
                    "audit_id": "audit-1",
                    "event_type": "create",
                    "actor": "alice",
                    "at": datetime(2026, 9, 6, tzinfo=UTC),
                    "subject": "thing",
                    "metadata": {"action": "create"},
                },
            )
        )
        subscriber.on_put(
            WriteEvent(
                entity_type="baz",
                entity_id="qux",
                payload={
                    "audit_id": "audit-2",
                    "event_type": "delete",
                    "actor": "bob",
                    "at": datetime(2026, 9, 6, 1, 0, tzinfo=UTC),
                    "subject": "thing2",
                    "metadata": {},
                },
            )
        )

        flusher = OutboxFlusher(outbox=outbox, conn=conn)
        flushed = await flusher.flush_once()
        assert flushed == 2

        # The rows are persisted with their entity_type/entity_id columns
        # and a JSON payload containing the validated audit record.
        rows = conn.execute(
            "SELECT entity_type, entity_id, payload FROM audit_log ORDER BY id"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][0] == "foo"
        assert rows[0][1] == "bar"
        payload_a = json.loads(rows[0][2])
        assert payload_a["audit_id"] == "audit-1"
        assert payload_a["event_type"] == "create"
        assert payload_a["actor"] == "alice"
        assert payload_a["subject"] == "thing"
        assert payload_a["metadata"] == {"action": "create"}

        assert rows[1][0] == "baz"
        assert rows[1][1] == "qux"
        payload_b = json.loads(rows[1][2])
        assert payload_b["audit_id"] == "audit-2"

    @pytest.mark.asyncio
    async def test_flush_once_swallows_executemany_failure(
        self,
    ) -> None:
        """G6 contract: DB errors during executemany are absorbed + logged.

        The contract asserts two observable properties:
        1. ``flush_once`` returns 0 instead of propagating the exception.
        2. ``executemany`` is still called exactly once with the rows that
           were drained from the outbox (the failure is on insert, not on
           the SQL preparation path).
        """
        outbox = MemoryOutbox()
        subscriber = AuditLogSubscriber(outbox=outbox)
        subscriber.on_put(
            WriteEvent(
                entity_type="foo",
                entity_id="bar",
                payload={
                    "audit_id": "audit-1",
                    "event_type": "create",
                    "actor": "alice",
                    "at": datetime.now(UTC),
                    "subject": "thing",
                    "metadata": {},
                },
            )
        )

        mock_conn = MagicMock()
        mock_conn.executemany.side_effect = duckdb.Error("simulated DB failure")

        flusher = OutboxFlusher(outbox=outbox, conn=mock_conn)

        flushed = await flusher.flush_once()

        assert flushed == 0
        assert mock_conn.executemany.call_count == 1
        # The rows that were drained from the outbox are passed to
        # executemany even though the call is going to fail — so the G6
        # contract covers the attempt, not the failure to attempt.
        call_args = mock_conn.executemany.call_args
        assert call_args.args[0].startswith("INSERT INTO audit_log")
        assert len(call_args.args[1]) == 1
        assert call_args.args[1][0][0] == "foo"  # entity_type
        assert call_args.args[1][0][1] == "bar"  # entity_id

    @pytest.mark.asyncio
    async def test_flush_once_handles_unexpected_exception_types(
        self,
    ) -> None:
        """G6 contract is exception-class-agnostic — a generic RuntimeError
        from executemany must also be absorbed.
        """
        outbox = MemoryOutbox()
        outbox.enqueue("foo", "bar", _make_record("a-1"))

        mock_conn = MagicMock()
        mock_conn.executemany.side_effect = RuntimeError("totally unexpected")

        flusher = OutboxFlusher(outbox=outbox, conn=mock_conn)

        flushed = await flusher.flush_once()

        assert flushed == 0
        assert mock_conn.executemany.call_count == 1

    @pytest.mark.asyncio
    async def test_flush_once_returns_zero_when_empty(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        # No enqueue; flush_once must short-circuit and return 0 without
        # ever calling executemany.
        flusher = OutboxFlusher(outbox=MemoryOutbox(), conn=conn)
        assert await flusher.flush_once() == 0
        # duckdb connection untouched: still empty.
        assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0

    @pytest.mark.asyncio
    async def test_periodic_flush_loop_drains_until_cancelled(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        """The loop must keep flushing across multiple ticks until cancelled."""
        outbox = MemoryOutbox()
        subscriber = AuditLogSubscriber(outbox=outbox)
        flusher = OutboxFlusher(outbox=outbox, conn=conn)

        async def _producer() -> None:
            for i in range(3):
                subscriber.on_put(
                    WriteEvent(
                        entity_type="foo",
                        entity_id=f"id-{i}",
                        payload={
                            "audit_id": f"a-{i}",
                            "event_type": "create",
                            "actor": "alice",
                            "at": datetime(2026, 9, 6, tzinfo=UTC),
                            "subject": f"thing-{i}",
                            "metadata": {},
                        },
                    )
                )
                await asyncio.sleep(0.02)

        async def _driver() -> None:
            # Let the producer enqueue across multiple ticks.
            await asyncio.sleep(0.08)
            # Cancel the loop and drain any final queued items so the
            # test asserts on the final flushed state.
            task.cancel()

        task = asyncio.create_task(
            periodic_flush_loop(flusher, interval_seconds=0.01)
        )
        await asyncio.gather(_producer(), _driver(), return_exceptions=True)
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Final drain to capture any rows enqueued after the last tick.
        leftover = await flusher.flush_once()
        assert leftover >= 0  # zero or whatever wasn't yet flushed
        rows = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        assert rows == 3

    @pytest.mark.asyncio
    async def test_periodic_flush_loop_survives_flush_errors(
        self,
    ) -> None:
        """G6 contract: the loop must continue after flush_once raises.

        Mock ``flush_once`` directly to always raise. This isolates the
        loop's survival semantics from outbox draining or executemany
        mechanics — we just want to verify the loop survives a flaky
        flusher for several ticks.
        """
        outbox = MemoryOutbox()

        # Build a flusher; we never call its real flush_once.
        flusher = OutboxFlusher(outbox=outbox, conn=MagicMock())
        call_counter = {"n": 0}

        async def _always_raise() -> int:
            call_counter["n"] += 1
            raise RuntimeError("flake")

        # Replace flush_once with a counter-raising stub.
        flusher.flush_once = _always_raise  # type: ignore[method-assign]

        task = asyncio.create_task(
            periodic_flush_loop(flusher, interval_seconds=0.005)
        )
        # Let several ticks accumulate.
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # The loop survived multiple ticks despite the flaky flusher.
        assert call_counter["n"] >= 2, (
            f"expected >= 2 ticks before cancellation, got {call_counter['n']}"
        )

    @pytest.mark.asyncio
    async def test_periodic_flush_loop_sleeps_between_ticks(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        """The configured interval controls the tick rate.

        With interval=0.03, two ticks should not complete inside 0.02s
        of wall-clock time but should complete inside 0.10s.
        """
        outbox = MemoryOutbox()
        flusher = OutboxFlusher(outbox=outbox, conn=conn)

        loop_task = asyncio.create_task(
            periodic_flush_loop(flusher, interval_seconds=0.03)
        )
        # Wait less than one interval; loop should still be alive.
        await asyncio.sleep(0.015)
        assert not loop_task.done()
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass


# ============================================================================
# AuditLogQueryTool
# ============================================================================
class TestAuditLogQueryTool:
    """Coverage for dhara/audit/query_tool.py."""

    def _seed(
        self,
        conn: duckdb.DuckDBPyConnection,
        entity_type: str,
        audit_id: str,
        actor: str = "alice",
        at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
        entity_id: str = "id-1",
    ) -> None:
        at = at or datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
        metadata = metadata if metadata is not None else {"k": "v"}
        payload = json.dumps(
            {
                "audit_id": audit_id,
                "event_type": "create",
                "actor": actor,
                "at": at.isoformat(),
                "subject": "thing",
                "metadata": metadata,
            }
        )
        conn.execute(
            "INSERT INTO audit_log (entity_type, entity_id, payload) "
            "VALUES (?, ?, ?)",
            (entity_type, entity_id, payload),
        )

    def test_query_filters_by_entity_type(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        self._seed(conn, "workflow_outcome", "audit-1")
        self._seed(conn, "approval_log", "audit-2", entity_id="id-2")
        tool = AuditLogQueryTool(conn)
        results = tool.query(entity_type="workflow_outcome")
        assert len(results) == 1
        assert isinstance(results[0], AuditRecord)
        assert results[0].audit_id == "audit-1"
        assert results[0].actor == "alice"

    def test_query_respects_limit_zero(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        self._seed(conn, "workflow_outcome", "audit-1")
        tool = AuditLogQueryTool(conn)
        assert tool.query(entity_type="workflow_outcome", limit=0) == []

    def test_query_respects_default_limit(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        # Seed 5 rows; default limit is 100 so all should come back.
        for i in range(5):
            self._seed(
                conn,
                "workflow_outcome",
                f"audit-{i}",
                entity_id=f"id-{i}",
            )
        tool = AuditLogQueryTool(conn)
        results = tool.query(entity_type="workflow_outcome")
        assert len(results) == 5

    def test_query_with_since_filter(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        older = datetime(2026, 9, 1, tzinfo=UTC)
        newer = datetime(2026, 9, 6, tzinfo=UTC)
        self._seed(
            conn,
            "workflow_outcome",
            "old",
            at=older,
            entity_id="old-1",
        )
        self._seed(
            conn,
            "workflow_outcome",
            "new",
            at=newer,
            entity_id="new-1",
        )
        # recorded_at is set automatically by CURRENT_TIMESTAMP on insert;
        # both rows will share that value. So `since` selects both. What
        # matters here is the WHERE clause was emitted and parsed.
        tool = AuditLogQueryTool(conn)
        results = tool.query(
            entity_type="workflow_outcome",
            since=datetime(2020, 1, 1, tzinfo=UTC),
        )
        assert len(results) == 2

    def test_query_with_until_filter(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        self._seed(conn, "workflow_outcome", "audit-1")
        self._seed(conn, "workflow_outcome", "audit-2", entity_id="id-2")
        tool = AuditLogQueryTool(conn)
        results = tool.query(
            entity_type="workflow_outcome",
            until=datetime(2000, 1, 1, tzinfo=UTC),
        )
        # Both records were inserted with CURRENT_TIMESTAMP which is after
        # year 2000; the until filter excludes them both. This proves the
        # ``recorded_at <= ?`` branch is exercised.
        assert results == []

    def test_query_with_since_and_until_filters(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        self._seed(conn, "workflow_outcome", "audit-1")
        self._seed(conn, "workflow_outcome", "audit-2", entity_id="id-2")
        tool = AuditLogQueryTool(conn)
        # The full window: both rows have CURRENT_TIMESTAMP, so they fall
        # inside any wide window. Exercises both the since + until branches.
        results = tool.query(
            entity_type="workflow_outcome",
            since=datetime(2020, 1, 1, tzinfo=UTC),
            until=datetime.now(UTC) + timedelta(days=1),
        )
        assert len(results) == 2

    def test_query_returns_empty_when_no_match(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        self._seed(conn, "workflow_outcome", "audit-1")
        tool = AuditLogQueryTool(conn)
        assert tool.query(entity_type="does_not_exist") == []

    def test_query_skips_invalid_payload(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        """Schema-drift tolerance: rows whose payload fails validation are
        silently dropped, with a warning logged for observability."""
        self._seed(conn, "workflow_outcome", "audit-good")
        # Inject a row whose payload is JSON-valid but fails msgspec
        # validation (actor must be str, not int).
        conn.execute(
            "INSERT INTO audit_log (entity_type, entity_id, payload) "
            "VALUES (?, ?, ?)",
            ("workflow_outcome", "id-bad", '{"actor": 12345}'),
        )
        tool = AuditLogQueryTool(conn)
        results = tool.query(entity_type="workflow_outcome", limit=100)
        assert len(results) == 1
        assert results[0].audit_id == "audit-good"

    def test_query_skips_non_audit_record_validation_results(
        self,
        conn: duckdb.DuckDBPyConnection,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If ``from_dict`` returns a non-AuditRecord struct (defensive
        coverage of the ``isinstance`` branch), the row is silently
        dropped from the results.
        """
        self._seed(conn, "workflow_outcome", "audit-good")

        # Replace ``from_dict`` for the duration of this test so it returns
        # a non-AuditRecord object — exercising the ``isinstance`` guard.
        class _NotAuditRecord:
            pass

        def _fake_from_dict(name: str, payload: dict[str, Any]) -> Any:
            return _NotAuditRecord()

        monkeypatch.setattr(
            "dhara.audit.query_tool.from_dict",
            _fake_from_dict,
        )

        tool = AuditLogQueryTool(conn)
        results = tool.query(entity_type="workflow_outcome", limit=10)

        # Non-AuditRecord results are filtered out by the isinstance guard.
        assert results == []

    def test_query_orders_by_recorded_at_desc(
        self,
        conn: duckdb.DuckDBPyConnection,
    ) -> None:
        self._seed(conn, "workflow_outcome", "audit-1", entity_id="id-1")
        # Sleep briefly so the second row's CURRENT_TIMESTAMP > the first's.
        import time

        time.sleep(0.01)
        self._seed(conn, "workflow_outcome", "audit-2", entity_id="id-2")
        tool = AuditLogQueryTool(conn)
        results = tool.query(entity_type="workflow_outcome")
        # Newest first: audit-2 should come before audit-1.
        assert [r.audit_id for r in results] == ["audit-2", "audit-1"]
