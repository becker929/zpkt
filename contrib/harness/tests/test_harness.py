import asyncio
import json

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock

from harness import jobs as J
from harness.config import Config
from harness.rpc import Methods
from harness.service import handle


def result(text="all done", error=False):
    return ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=error, num_turns=3,
                         session_id="sess-1", total_cost_usd=0.5, result=text)


def fake_query(messages):
    async def q(prompt, options):
        q.seen = (prompt, options)
        for m in messages:
            yield m
    return q


@pytest.fixture
def cfg(tmp_path):
    return Config(jobs_dir=tmp_path / "jobs", workdir=tmp_path)


async def test_job_runs_and_keeps_its_record(cfg):
    store = J.JobStore(cfg.jobs_dir)
    started, finished = [], []
    msgs = [AssistantMessage(content=[TextBlock("reading"), ToolUseBlock(id="t", name="Bash", input={"command": "ls"})],
                             model="m"), result()]
    runner = J.Runner(cfg, store, on_start=started.append, on_finish=finished.append, run_query=fake_query(msgs))
    job = await runner.run_one(runner.submit("job", "t", "do it"))
    assert job.status == "done" and job.result == "all done" and job.session_id == "sess-1"
    assert [j.id for j in started] == [job.id] == [j.id for j in finished]
    assert store.load(job.id).status == "done"
    assert [e.get("tool") or e.get("text") for e in store.events(job.id)] == ["reading", "Bash"]


async def test_failed_and_crashed_jobs(cfg):
    store = J.JobStore(cfg.jobs_dir)
    job = await J.Runner(cfg, store, run_query=fake_query([result("boom", error=True)])).run_one(
        J.Runner(cfg, store).submit("job", "t", "x"))
    assert job.status == "failed" and job.error == "boom"

    async def crash(prompt, options):
        raise RuntimeError("no login")
        yield
    job = await J.Runner(cfg, store, run_query=crash).run_one(J.Runner(cfg, store).submit("job", "t", "x"))
    assert job.status == "failed" and "no login" in job.error


async def test_restart_marks_running_failed_and_requeues_waiting(cfg):
    store = J.JobStore(cfg.jobs_dir)
    r = J.Runner(cfg, store)
    a, b = r.submit("job", "a", "x"), r.submit("job", "b", "y")
    a.status = "running"
    store.save(a)
    r2 = J.Runner(cfg, store)
    r2.recover()
    assert store.load(a.id).status == "failed"
    assert r2.queue.get_nowait() == b.id


async def test_feedback_queues_one_job_per_batch(cfg):
    store = J.JobStore(cfg.jobs_dir)
    m = Methods(cfg, J.Runner(cfg, store), store)
    first = await m.call("feedback", {"batch": 4.2, "session": "s1"})
    again = await m.call("feedback", {"batch": 4.2, "session": "s2"})
    assert again == {"job_id": first["job_id"], "status": "queued", "deduplicated": True}
    job = store.load(first["job_id"])
    assert "\"batch\" is 4.2" in job.prompt and job.title == "Feedback on batch 4.2"
    with pytest.raises(ValueError):
        await m.call("feedback", {"batch": "4.2; rm -rf /"})
    with pytest.raises(ValueError):
        await m.call("shell", {})


async def test_ask_is_read_only(cfg):
    opts = J.options(cfg, ask=True)
    assert "Bash" not in opts.allowed_tools and "Bash" in opts.disallowed_tools
    assert J.options(cfg).permission_mode == "acceptEdits"


class Socket:
    def __init__(self):
        self.sent = []

    async def send(self, m):
        self.sent.append(json.loads(m))


async def test_socket_replies_with_result_or_error(cfg):
    store = J.JobStore(cfg.jobs_dir)
    m = Methods(cfg, J.Runner(cfg, store), store)
    ws = Socket()
    await handle(ws, m, json.dumps({"id": "1", "method": "ping"}))
    await handle(ws, m, json.dumps({"id": "2", "method": "job_status", "params": {"id": "nope"}}))
    await handle(ws, m, "not json")
    assert ws.sent[0]["id"] == "1" and ws.sent[0]["result"]["ok"] is True
    assert ws.sent[1] == {"id": "2", "error": "no such job"}
    assert len(ws.sent) == 2
