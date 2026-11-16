"""delegate() must wait for subagents whether Task runs them in the foreground or background."""
import asyncio

from claude_agent_sdk import ResultMessage, TaskNotificationMessage, TaskStartedMessage, TaskUpdatedMessage

from lit_orchestrator.coordinator import coordinator


def started(task_id):
    return TaskStartedMessage(subtype="task_started", data={}, task_id=task_id, description="d",
                              uuid="u", session_id="s")


def finished(task_id):
    return TaskNotificationMessage(subtype="task_notification", data={}, task_id=task_id,
                                   status="completed", output_file="", summary="ok", uuid="u", session_id="s")


def result(origin=None, is_error=False, cost=None):
    return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=is_error,
                         num_turns=1, session_id="s", origin=origin, total_cost_usd=cost)


class FakeClient:
    """Yields scripted messages, running a side effect when one is consumed."""

    def __init__(self, script):
        self.script = list(script)
        self.consumed = 0

    async def query(self, directive):
        pass

    async def receive_messages(self):
        for item in self.script:
            self.consumed += 1
            if callable(item):
                item()
            else:
                yield item


def run(client, done=lambda: False):
    asyncio.run(coordinator.delegate(client, "go", done=done))


def test_foreground_task_returns_at_end_of_turn():
    client = FakeClient([started("t1"), finished("t1"), result(), started("never-read")])
    run(client)
    assert client.consumed == 3


def test_background_task_is_waited_for_after_the_turn_ends():
    work = []
    client = FakeClient([started("t1"), result(), lambda: work.append("subagent ran"), finished("t1"),
                         started("never-read")])
    run(client)
    assert work == ["subagent ran"] and client.consumed == 4


def test_terminal_status_via_task_update_counts():
    update = TaskUpdatedMessage(subtype="task_updated", data={}, task_id="t1", patch={"status": "failed"})
    client = FakeClient([started("t1"), result(), update, started("never-read")])
    run(client)
    assert client.consumed == 3


def test_turn_started_by_a_task_notification_is_not_our_turn_ending():
    # A stale session-initiated turn from the previous delegation arrives first.
    client = FakeClient([result(origin={"kind": "task-notification"}), started("t1"),
                         result(), finished("t1"), started("never-read")])
    run(client)
    assert client.consumed == 4


def test_results_arriving_is_enough_when_no_terminal_event_comes():
    arrived = []
    client = FakeClient([started("t1"), result(), lambda: arrived.append(1), started("t2"), started("never-read")])
    run(client, done=lambda: bool(arrived))
    assert client.consumed == 4


def test_error_turn_raises():
    try:
        run(FakeClient([result(is_error=True)]))
    except RuntimeError as exc:
        assert "coordinator turn failed" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_returns_latest_cost_from_any_turn():
    client = FakeClient([started("t1"), result(cost=0.10),
                         result(origin={"kind": "task-notification"}, cost=0.25), finished("t1")])
    assert asyncio.run(coordinator.delegate(client, "go", done=lambda: False)) == 0.25
