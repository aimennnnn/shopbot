"""ShopBot agent API (FastAPI).

Graded endpoints:  POST /chat   GET /health
Website endpoints: /products /orders /memory and /admin/* (password protected)
"""
import logging
import os
import threading
import time
import urllib.request
import uuid

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict

from . import config, db, rag, security
from .graph import get_graph, get_llm, run_turn
from .tools import forget_facts, load_facts

log = logging.getLogger("shopbot")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="ShopBot Agent API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def warm_up() -> None:
    """Connect to the database in the background so the first chat is fast."""
    def run() -> None:
        try:
            get_graph()
            get_llm("sales")  # loads the model clients now, so the first chat is not slow
            get_llm("support")
        except Exception as e:  # the app still starts; /chat will retry
            log.warning("warm-up failed: %s", e)

    threading.Thread(target=run, daemon=True).start()
    threading.Thread(target=keep_awake, daemon=True).start()


def keep_awake() -> None:
    """Render's free plan sleeps after 15 minutes without traffic, and Neon
    pauses after 5. Every 4 minutes this touches the database, and every 8
    minutes it calls the service's own public /health, so neither goes cold."""
    url = os.getenv("RENDER_EXTERNAL_URL", "").rstrip("/")
    turn = 0
    while True:
        time.sleep(240)
        turn += 1
        try:
            db.query("SELECT 1")
        except Exception as e:
            log.warning("keep-awake database ping failed: %s", e)
        if url and turn % 2 == 0:
            try:
                urllib.request.urlopen(url + "/health", timeout=30).read()
                log.info("keep-awake ping ok")
            except Exception as e:
                log.warning("keep-awake ping failed: %s", e)


# ---------- graded endpoints ----------

class ChatIn(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)
    user_id: str = "anonymous"
    thread_id: str = "default"
    message: str = ""


@app.get("/health", response_class=PlainTextResponse)
def health() -> str:
    return "ok"


@app.post("/chat")
def chat(body: ChatIn, request: Request, x_user_key: str = Header(default="")) -> dict:
    if security.too_many_requests(request):
        return {"reply": "You are sending messages too fast. Please wait a minute and try again.",
                "tool_calls": [], "tokens": {"in": 0, "out": 0}, "error": "rate_limited"}
    user_id = body.user_id.strip()[:100] or "anonymous"
    security.check_user(user_id, x_user_key)
    thread_id = body.thread_id.strip()[:100] or "default"
    message = body.message.strip()[: config.MAX_MESSAGE_CHARS]
    if not message:
        return {"reply": "Please type a message. I can help you find products or manage your orders.",
                "tool_calls": [], "tokens": {"in": 0, "out": 0}}
    try:
        out = run_turn(user_id, thread_id, message, request_id=uuid.uuid4().hex)
    except Exception as e:
        log.exception("chat failed")
        return {"reply": "Sorry, something went wrong on our side. Please try again in a moment.",
                "tool_calls": [], "tokens": {"in": 0, "out": 0}, "error": type(e).__name__}
    try:
        db.execute(
            "INSERT INTO chat_log (user_id, thread_id, message, reply, tool_calls, tokens_in, tokens_out, blocked, agent) "
            "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)",
            (user_id, thread_id, message, out["reply"], _json(out["tool_calls"]),
             out["tokens"]["in"], out["tokens"]["out"], out["blocked"], out["agent"]),
        )
    except Exception:
        log.exception("could not write chat_log")
    return {"reply": out["reply"], "tool_calls": out["tool_calls"], "tokens": out["tokens"]}


# ---------- storefront endpoints (used by the customer page) ----------

@app.get("/")
def root() -> dict:
    return {"name": "ShopBot Agent API", "shop": config.SHOP_NAME, "endpoints": ["POST /chat", "GET /health"]}


@app.get("/products")
def products() -> list[dict]:
    db.init()
    return db.query("SELECT id, name, description, category, price, stock, emoji FROM products "
                    "WHERE active ORDER BY id")


@app.get("/orders")
def orders(user_id: str, x_user_key: str = Header(default="")) -> list[dict]:
    security.check_user(user_id, x_user_key)
    db.init()
    return db.query("SELECT id, product_name, quantity, total, status, created_at FROM orders "
                    "WHERE user_id = %s ORDER BY id DESC LIMIT 50", (user_id,))


@app.get("/memory")
def memory(user_id: str, x_user_key: str = Header(default="")) -> list[dict]:
    security.check_user(user_id, x_user_key)
    return load_facts(user_id, limit=50)


@app.delete("/memory")
def forget(user_id: str, x_user_key: str = Header(default="")) -> dict:
    security.check_user(user_id, x_user_key)
    return {"deleted": forget_facts(user_id)}


# ---------- admin endpoints (seller dashboard) ----------

def admin(request: Request, x_admin_token: str = Header(default="")) -> None:
    security.check_admin(request, x_admin_token)
    db.init()


class ProductIn(BaseModel):
    name: str
    description: str = ""
    category: str = ""
    price: int
    stock: int = 0
    emoji: str = "🛍️"
    active: bool = True


@app.get("/admin/stats", dependencies=[Depends(admin)])
def admin_stats() -> dict:
    chats = db.query(
        "SELECT count(*) AS chats, count(DISTINCT user_id) AS users, "
        "count(DISTINCT (user_id, thread_id)) AS conversations, "
        "coalesce(sum(tokens_in), 0) AS tokens_in, coalesce(sum(tokens_out), 0) AS tokens_out, "
        "count(*) FILTER (WHERE blocked) AS blocked, "
        "count(*) FILTER (WHERE tool_calls <> '[]'::jsonb) AS with_tools FROM chat_log")[0]
    sales = db.query(
        "SELECT count(*) FILTER (WHERE status = 'confirmed') AS orders, "
        "coalesce(sum(total) FILTER (WHERE status = 'confirmed'), 0) AS revenue, "
        "count(*) FILTER (WHERE status = 'cancelled') AS cancelled FROM orders")[0]
    daily = db.query(
        "SELECT created_at::date AS day, count(*) AS chats, sum(tokens_in + tokens_out) AS tokens "
        "FROM chat_log GROUP BY 1 ORDER BY 1 DESC LIMIT 7")
    low = db.query("SELECT id, name, stock FROM products WHERE active AND stock <= 5 ORDER BY stock")
    agents = db.query(
        "SELECT agent, count(*) AS messages, coalesce(round(avg(tokens_in + tokens_out)), 0)::int AS avg_tokens "
        "FROM chat_log WHERE agent <> '' GROUP BY agent ORDER BY messages DESC")
    return {**chats, **sales, "daily": daily, "low_stock": low, "agents": agents}


@app.get("/admin/orders", dependencies=[Depends(admin)])
def admin_orders() -> list[dict]:
    return db.query("SELECT id, user_id, product_name, quantity, total, status, created_at "
                    "FROM orders ORDER BY id DESC LIMIT 200")


@app.get("/admin/chats", dependencies=[Depends(admin)])
def admin_chats() -> list[dict]:
    return db.query("SELECT id, user_id, thread_id, message, reply, tool_calls, tokens_in, tokens_out, "
                    "blocked, agent, created_at FROM chat_log ORDER BY id DESC LIMIT 100")


@app.get("/admin/products", dependencies=[Depends(admin)])
def admin_products() -> list[dict]:
    return db.query("SELECT id, name, description, category, price, stock, emoji, active "
                    "FROM products ORDER BY id")


@app.post("/admin/products", dependencies=[Depends(admin)])
def admin_add_product(p: ProductIn) -> dict:
    return db.query(
        "INSERT INTO products (name, description, category, price, stock, emoji, active) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (p.name, p.description, p.category, p.price, p.stock, p.emoji, p.active))[0]


@app.put("/admin/products/{product_id}", dependencies=[Depends(admin)])
def admin_update_product(product_id: int, p: ProductIn) -> dict:
    n = db.execute(
        "UPDATE products SET name = %s, description = %s, category = %s, price = %s, stock = %s, "
        "emoji = %s, active = %s WHERE id = %s",
        (p.name, p.description, p.category, p.price, p.stock, p.emoji, p.active, product_id))
    if not n:
        raise HTTPException(status_code=404, detail="No such product")
    return {"id": product_id}


@app.post("/admin/reset", dependencies=[Depends(admin)])
def admin_reset() -> dict:
    """Clears all customer activity so the shop starts from zero: orders,
    conversations, memory and the message log. The product catalog stays,
    and stock taken by the deleted orders is put back."""
    get_graph()  # makes sure the conversation tables exist, even on a brand new database
    with db.pool().connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE products p SET stock = p.stock + o.qty FROM "
            "(SELECT product_id, sum(quantity) AS qty FROM orders WHERE status = 'confirmed' GROUP BY 1) o "
            "WHERE p.id = o.product_id")
        conn.execute("TRUNCATE orders, pending_actions, chat_log, user_keys, "
                     "checkpoints, checkpoint_blobs, checkpoint_writes RESTART IDENTITY")
        conn.execute("DELETE FROM store WHERE prefix LIKE 'memory.%%'")
        conn.execute("DELETE FROM kb_chunks WHERE scope LIKE 'user:%%'")  # private notes; shop documents stay
    return {"reset": True}


class DocumentIn(BaseModel):
    title: str
    content: str


@app.get("/admin/knowledge", dependencies=[Depends(admin)])
def admin_knowledge() -> list[dict]:
    """The shop's own documents in the knowledge base (never customers' private chunks)."""
    return db.query(
        "SELECT title, string_agg(content, ' ' ORDER BY id) AS content, count(*) AS chunks "
        "FROM kb_chunks WHERE scope = %s GROUP BY title ORDER BY min(id)", (rag.SHOP,))


@app.post("/admin/knowledge", dependencies=[Depends(admin)])
def admin_add_document(doc: DocumentIn) -> dict:
    title = doc.title.strip()[:120]
    if not title or not doc.content.strip():
        raise HTTPException(status_code=400, detail="A document needs a title and some text")
    rag.delete_document(rag.SHOP, title)  # saving again with the same title replaces it
    return {"chunks": rag.add_document(rag.SHOP, title, doc.content[:20000])}


@app.delete("/admin/knowledge", dependencies=[Depends(admin)])
def admin_delete_document(title: str) -> dict:
    return {"deleted": rag.delete_document(rag.SHOP, title)}


class CatalogIn(BaseModel):
    products: list[ProductIn]


@app.post("/admin/catalog", dependencies=[Depends(admin)])
def admin_upload_catalog(body: CatalogIn) -> dict:
    """Bulk upload from the dashboard's CSV import. A product with the same
    name is updated, anything new is added."""
    added = updated = 0
    for p in body.products[:500]:
        n = db.execute(
            "UPDATE products SET description = %s, category = %s, price = %s, stock = %s, emoji = %s, "
            "active = %s WHERE lower(name) = lower(%s)",
            (p.description, p.category, p.price, p.stock, p.emoji, p.active, p.name))
        if n:
            updated += 1
        else:
            db.execute(
                "INSERT INTO products (name, description, category, price, stock, emoji, active) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (p.name, p.description, p.category, p.price, p.stock, p.emoji, p.active))
            added += 1
    return {"added": added, "updated": updated}


def _json(value) -> str:
    import json
    return json.dumps(value)
