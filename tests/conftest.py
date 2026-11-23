"""Shared test setup.

The agent tests run the real graph, real tools and a real Postgres database.
Only the model is replaced, by a scripted stand-in, so the tests cost nothing
and always behave the same way.

They need a throwaway database: set TEST_DATABASE_URL. They never touch
DATABASE_URL, because they wipe all customer activity before they start.
"""
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "")
os.environ["ADMIN_PASSWORD"] = "test-admin"
os.environ["RATE_LIMIT_PER_MIN"] = "100000"   # the rate-limit test lowers this itself
os.environ.pop("LANGSMITH_TRACING", None)

ADMIN = {"x-admin-token": "test-admin", "x-forwarded-for": "10.0.0.1"}


class FakeLLM:
    """Stands in for Claude. It picks tool calls with simple rules, so every
    node, edge and tool of the real graph is exercised without an API key."""

    def __init__(self):
        self.calls = []

    def invoke(self, messages):
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        self.calls.append(messages)
        system, last = messages[0].content, messages[-1]
        self.last_agent = "support" if "the support agent" in system else "sales"
        usage = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        if isinstance(last, ToolMessage):
            return AIMessage(content=f"[after tool] {last.content}", usage_metadata=usage)
        text = last.content.lower()

        def call(name, **args):
            return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "t1"}], usage_metadata=usage)

        if "boom" in text:
            raise RuntimeError("model is down")
        if "sneaky" in text:  # tries to prepare and confirm an order in the same turn
            return AIMessage(content="", usage_metadata=usage, tool_calls=[
                {"name": "place_order", "args": {"product_id": 1, "quantity": 2}, "id": "a"},
                {"name": "confirm_action", "args": {}, "id": "b"}])
        if text.startswith("kb:"):
            return call("search_knowledge", query=last.content[3:])
        if "order 2 mugs" in text:
            return call("place_order", product_id=1, quantity=2)
        if "mug" in text:
            return call("search_products", query="mug")
        if text.strip() in ("yes", "yes please"):
            return call("confirm_action")
        if "my orders" in text:
            return call("my_orders")
        found = re.search(r"cancel order (\d+)", text)
        if found:
            return call("cancel_order", order_id=int(found.group(1)))
        if text.startswith("note:") or "i like" in text:
            return call("remember", fact=last.content)
        if "what do you know" in text or "what did i say" in text:
            humans = [m.content for m in messages if isinstance(m, HumanMessage)]
            memory = system.split("Keep replies")[1]
            return AIMessage(content=f"MEMORY<{memory}> HISTORY<{humans}>", usage_metadata=usage)
        return AIMessage(content="plain reply", usage_metadata=usage)


@pytest.fixture(scope="session")
def llm():
    return FakeLLM()


@pytest.fixture(scope="session")
def client(llm):
    if not os.environ["DATABASE_URL"]:
        pytest.skip("set TEST_DATABASE_URL to a throwaway Postgres database to run the agent tests")
    from fastapi.testclient import TestClient

    from app import graph
    from app.main import app

    graph.get_llm = lambda role="sales": llm
    c = TestClient(app)
    c.post("/admin/reset", headers=ADMIN)   # start from zero
    return c


@pytest.fixture(scope="session")
def chat(client):
    def send(user, thread, message, headers=None):
        r = client.post("/chat", json={"user_id": user, "thread_id": thread, "message": message}, headers=headers or {})
        assert r.status_code == 200, r.text
        body = r.json()
        assert {"reply", "tool_calls", "tokens"} <= set(body) and set(body["tokens"]) == {"in", "out"}, body
        return body
    return send
