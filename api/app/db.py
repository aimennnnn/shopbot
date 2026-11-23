"""Postgres (Neon) access. Everything that must survive a restart lives here."""
import threading

from langgraph.store.postgres import PostgresStore
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config

_pool: ConnectionPool | None = None
_store: PostgresStore | None = None
_ready = False
_lock = threading.Lock()
_lock_init = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    price INTEGER NOT NULL,
    stock INTEGER NOT NULL DEFAULT 0,
    emoji TEXT NOT NULL DEFAULT '🛍️',
    active BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    product_id INTEGER NOT NULL,
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    total INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS orders_user_idx ON orders (user_id);
-- A risky action waiting for the customer to say yes (one per conversation).
CREATE TABLE IF NOT EXISTS pending_actions (
    user_id TEXT NOT NULL,
    thread_key TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL,
    request_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, thread_key)
);
-- Website customers prove who they are with a secret key. Only its hash is stored.
CREATE TABLE IF NOT EXISTS user_keys (
    user_id TEXT PRIMARY KEY,
    key_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- RAG knowledge base. scope is 'shop' (public) or 'user:<id>' (one customer's private chunks).
CREATE TABLE IF NOT EXISTS kb_chunks (
    id SERIAL PRIMARY KEY,
    scope TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scope, content)
);
CREATE INDEX IF NOT EXISTS kb_chunks_scope_idx ON kb_chunks (scope);
-- One row per /chat call, for the admin dashboard and cost tracking.
CREATE TABLE IF NOT EXISTS chat_log (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    message TEXT NOT NULL,
    reply TEXT NOT NULL,
    tool_calls JSONB NOT NULL DEFAULT '[]',
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    blocked BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

SEED = [
    ("Blue Pottery Mug", "Hand-painted Multani blue pottery mug, 300 ml, microwave safe.", "kitchen", 1200, 25, "☕"),
    ("Blue Pottery Plate Set", "Set of 4 hand-painted dinner plates in Multani blue.", "kitchen", 4800, 8, "🍽️"),
    ("Truck Art Coasters", "Set of 6 wooden coasters painted in bright truck-art style.", "home", 950, 40, "🎨"),
    ("Truck Art Kettle", "Steel kettle hand-painted with truck-art flowers. Decorative and usable.", "kitchen", 2600, 12, "🫖"),
    ("Ajrak Cotton Scarf", "Block-printed Sindhi ajrak scarf, pure cotton, maroon and indigo.", "clothing", 1800, 30, "🧣"),
    ("Embroidered Cushion Cover", "Hand-embroidered Balochi mirror-work cushion cover, 16x16 in.", "home", 1500, 20, "🛋️"),
    ("Leather Khussa (Women)", "Handmade leather khussa with gold thread work. Sizes 36-41.", "footwear", 3200, 15, "🥿"),
    ("Peshawari Chappal (Men)", "Classic handmade leather Peshawari chappal, brown. Sizes 40-45.", "footwear", 4500, 10, "👞"),
    ("Camel Skin Lamp", "Hand-painted Multani camel skin table lamp, 12 in tall.", "home", 5500, 5, "🪔"),
    ("Brass Chai Set", "Engraved brass tray with 6 small chai cups.", "kitchen", 6900, 4, "🍵"),
    ("Hand-knotted Mini Rug", "2x3 ft wool rug, hand-knotted, red tribal pattern.", "home", 9500, 3, "🧶"),
    ("Walnut Wood Jewellery Box", "Hand-carved Kashmiri walnut wood box with velvet lining.", "gifts", 3800, 9, "🎁"),
    ("Onyx Marble Chess Set", "Green and white onyx chess set, 12 in board.", "gifts", 7500, 0, "♟️"),
]


def pool() -> ConnectionPool:
    """Shared connection pool. Connections are checked before use because
    Neon closes idle ones when the database goes to sleep."""
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                if not config.DATABASE_URL:
                    raise RuntimeError("DATABASE_URL is not set")
                _pool = ConnectionPool(
                    config.DATABASE_URL,
                    min_size=1,
                    max_size=5,
                    kwargs={"autocommit": True, "prepare_threshold": None, "row_factory": dict_row},
                    check=ConnectionPool.check_connection,
                    open=True,
                    timeout=20,
                )
    return _pool


def init() -> None:
    """Create tables, the long-term memory store and demo products once.
    Safe to call many times."""
    global _ready, _store
    if _ready:
        return
    with _lock_init:
        if _ready:
            return
        with pool().connection() as conn:
            conn.execute(SCHEMA)
            if conn.execute("SELECT count(*) AS n FROM products").fetchone()["n"] == 0:
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO products (name, description, category, price, stock, emoji) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        SEED,
                    )
        store = PostgresStore(pool())
        store.setup()
        _store = store
        _ready = True
    try:  # demo documents for the knowledge base; never stops the shop from starting
        from . import rag
        rag.seed()
    except Exception:
        pass


def store() -> PostgresStore:
    """LangGraph store that holds long-term memory, keyed by user_id."""
    init()
    return _store


def query(sql: str, params: tuple = ()) -> list[dict]:
    with pool().connection() as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else []


def execute(sql: str, params: tuple = ()) -> int:
    with pool().connection() as conn:
        return conn.execute(sql, params).rowcount
