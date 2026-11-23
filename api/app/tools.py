"""The agent's tools. All of them read or write the real database.

Security rule: user_id never comes from the model. It is taken from the
request (via config), so one user can never reach another user's data."""
import hashlib
import json
import re

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from . import db


def _ctx(config: RunnableConfig) -> tuple[str, str, str]:
    c = config["configurable"]
    return c["user_id"], c["thread_id"], c["request_id"]


@tool
def search_products(query: str = "", max_price: int | None = None) -> str:
    """Search the shop catalogue. query: keywords (empty = list everything). max_price: optional PKR limit."""
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2][:6]
    sql = "SELECT id, name, description, category, price, stock FROM products WHERE active"
    params: list = []
    if max_price is not None:
        sql += " AND price <= %s"
        params.append(max_price)
    rows = db.query(sql + " ORDER BY id", tuple(params))

    def score(r: dict) -> int:
        text = f"{r['name']} {r['description']} {r['category']}".lower()
        return sum(1 for w in words if w.rstrip("s") in text)

    if words:
        rows = sorted((r for r in rows if score(r) > 0), key=score, reverse=True)
    if not rows:
        return "No matching products."
    return "\n".join(
        f"#{r['id']} {r['name']} - Rs {r['price']} - "
        f"{'in stock: ' + str(r['stock']) if r['stock'] > 0 else 'OUT OF STOCK'} - {r['description']}"
        for r in rows[:6]
    )


@tool
def place_order(product_id: int, quantity: int = 1, *, config: RunnableConfig) -> str:
    """Prepare an order. Nothing is bought until the customer confirms."""
    user_id, thread_id, request_id = _ctx(config)
    if quantity < 1 or quantity > 20:
        return "Quantity must be between 1 and 20."
    rows = db.query("SELECT id, name, price, stock FROM products WHERE id = %s AND active", (product_id,))
    if not rows:
        return "No such product."
    p = rows[0]
    if p["stock"] < quantity:
        return f"Not enough stock: only {p['stock']} left of {p['name']}."
    total = p["price"] * quantity
    _set_pending(user_id, thread_id, request_id, "order",
                 {"product_id": p["id"], "name": p["name"], "quantity": quantity, "total": total})
    return (f"NOT PLACED YET. Ask the customer to confirm: {quantity} x {p['name']} = Rs {total}. "
            "Call confirm_action only after they say yes in their next message.")


@tool
def cancel_order(order_id: int, *, config: RunnableConfig) -> str:
    """Prepare cancelling one of this customer's orders. Nothing is cancelled until they confirm."""
    user_id, thread_id, request_id = _ctx(config)
    rows = db.query(
        "SELECT id, product_name, quantity, status FROM orders WHERE id = %s AND user_id = %s",
        (order_id, user_id),
    )
    if not rows:
        return "This customer has no order with that number."
    o = rows[0]
    if o["status"] == "cancelled":
        return "That order is already cancelled."
    _set_pending(user_id, thread_id, request_id, "cancel",
                 {"order_id": o["id"], "name": o["product_name"], "quantity": o["quantity"]})
    return (f"NOT CANCELLED YET. Ask the customer to confirm cancelling order #{o['id']} "
            f"({o['quantity']} x {o['product_name']}). Call confirm_action only after they say yes "
            "in their next message.")


@tool
def confirm_action(*, config: RunnableConfig) -> str:
    """Carry out the prepared order or cancellation. Only after the customer said yes."""
    user_id, thread_id, request_id = _ctx(config)
    rows = db.query(
        "SELECT kind, payload, request_id FROM pending_actions WHERE user_id = %s AND thread_key = %s",
        (user_id, thread_id),
    )
    if not rows:
        return "Nothing is waiting for confirmation."
    kind, payload = rows[0]["kind"], rows[0]["payload"]
    # Hard rule, enforced in code: the "yes" must come in a later message
    # than the one that prepared the action.
    if rows[0]["request_id"] == request_id:
        return "Refused: the customer has not confirmed yet. Ask them and wait for their reply."
    db.execute("DELETE FROM pending_actions WHERE user_id = %s AND thread_key = %s", (user_id, thread_id))
    if kind == "order":
        taken = db.execute(
            "UPDATE products SET stock = stock - %s WHERE id = %s AND stock >= %s",
            (payload["quantity"], payload["product_id"], payload["quantity"]),
        )
        if not taken:
            return "Sorry, that item just went out of stock. The order was not placed."
        order = db.query(
            "INSERT INTO orders (user_id, product_id, product_name, quantity, total) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (user_id, payload["product_id"], payload["name"], payload["quantity"], payload["total"]),
        )[0]
        return f"Order #{order['id']} placed: {payload['quantity']} x {payload['name']}, total Rs {payload['total']}."
    done = db.execute(
        "UPDATE orders SET status = 'cancelled' WHERE id = %s AND user_id = %s AND status <> 'cancelled'",
        (payload["order_id"], user_id),
    )
    if done:
        db.execute("UPDATE products SET stock = stock + %s WHERE id = "
                   "(SELECT product_id FROM orders WHERE id = %s)", (payload["quantity"], payload["order_id"]))
        return f"Order #{payload['order_id']} cancelled."
    return "That order could not be cancelled."


@tool
def my_orders(*, config: RunnableConfig) -> str:
    """List this customer's own orders (all conversations)."""
    user_id, _, _ = _ctx(config)
    rows = db.query(
        "SELECT id, product_name, quantity, total, status, created_at::date AS day FROM orders "
        "WHERE user_id = %s ORDER BY id DESC LIMIT 8",
        (user_id,),
    )
    if not rows:
        return "This customer has no orders yet."
    return "\n".join(
        f"#{r['id']} {r['quantity']} x {r['product_name']} - Rs {r['total']} - {r['status']} - {r['day']}"
        for r in rows
    )


@tool
def remember(fact: str, *, config: RunnableConfig) -> str:
    """Save one short lasting fact about this customer (name, size, taste, city) for future chats."""
    user_id, _, _ = _ctx(config)
    save_fact(user_id, fact)
    return "Saved."


TOOLS = [search_products, place_order, cancel_order, confirm_action, my_orders, remember]


def _namespace(user_id: str) -> tuple[str, str]:
    """Each user gets a private namespace in the store. The id is hex-encoded
    because store namespaces cannot contain some characters (like dots)."""
    return ("memory", user_id.encode().hex())


def save_fact(user_id: str, fact: str) -> None:
    fact = " ".join(fact.split())[:200]
    if fact:
        key = hashlib.sha1(fact.lower().encode()).hexdigest()[:16]  # same fact is stored once
        db.store().put(_namespace(user_id), key, {"fact": fact})


def load_facts(user_id: str, limit: int = 12) -> list[dict]:
    items = db.store().search(_namespace(user_id), limit=50)
    items.sort(key=lambda i: i.created_at)
    return [{"id": i.key, "fact": i.value["fact"]} for i in items[-limit:]]


def forget_facts(user_id: str) -> int:
    items = db.store().search(_namespace(user_id), limit=200)
    for i in items:
        db.store().delete(_namespace(user_id), i.key)
    return len(items)


def _set_pending(user_id: str, thread_id: str, request_id: str, kind: str, payload: dict) -> None:
    db.execute(
        "INSERT INTO pending_actions (user_id, thread_key, kind, payload, request_id) "
        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (user_id, thread_key) DO UPDATE SET "
        "kind = EXCLUDED.kind, payload = EXCLUDED.payload, request_id = EXCLUDED.request_id, created_at = now()",
        (user_id, thread_id, kind, json.dumps(payload), request_id),
    )
