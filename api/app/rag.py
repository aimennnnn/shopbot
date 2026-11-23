"""RAG with privacy isolation.

The knowledge base is a table of text chunks, each with an embedding vector
and a scope:

    scope = "shop"            the seller's documents, every customer may retrieve them
    scope = "user:<user_id>"  one customer's private notes and order receipts

search() only ever looks at "shop" plus the caller's own scope. The scope is
built from the user_id of the request, never from anything the model says, so
one customer's private chunks can never be retrieved for another customer.

Retrieval is hybrid: vector similarity plus BM25 word matching, fused with
Reciprocal Rank Fusion.

Embeddings: a small built-in embedder (feature hashing of words and letter
trigrams, 256 dimensions, cosine similarity). It needs no extra service, key
or memory, which matters on a free 512 MB server. It matches on wording, not
deep meaning. embed() is the only function to replace to plug in a neural
embedding model later.
"""
import json
import math
import re
import zlib

from . import db

DIM = 256
TOP_K = 4
MIN_SCORE = 0.12
SHOP = "shop"

STOP = set("a an the is are was were be to of in on at for and or do does did can could would will i you we it "
           "my your our me us this that with by from as have has had how what when where which who please".split())

# A little help with wording: words that mean the same thing share one token.
SAME = {
    "shipping": "delivery", "ship": "delivery", "shipped": "delivery", "deliver": "delivery", "delivered": "delivery",
    "courier": "delivery", "parcel": "delivery", "arrive": "delivery", "arrives": "delivery", "dispatch": "delivery",
    "refund": "return", "refunds": "return", "returns": "return", "exchange": "return", "replace": "return",
    "replacement": "return", "broken": "damaged", "breakage": "damaged", "damage": "damaged", "cracked": "damaged",
    "pay": "payment", "paying": "payment", "paid": "payment", "cod": "cash", "wash": "care", "washing": "care",
    "clean": "care", "cleaning": "care", "maintain": "care", "charges": "charge", "fee": "charge", "cost": "charge",
    "wrapping": "wrap", "wrapped": "wrap", "artisans": "artisan", "makers": "artisan", "made": "artisan",
    "makes": "artisan", "make": "artisan", "maker": "artisan", "handmade": "artisan", "dishwasher": "wash",
    "abroad": "outside", "international": "outside", "overseas": "outside",
}


def _tokens(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if w in STOP:
            continue
        w = SAME.get(w, w)
        if len(w) > 3 and w.endswith("s"):
            w = w[:-1]
        out.append(w)
    return out


def embed(text: str) -> list[float]:
    """Text -> unit vector. Words count fully, letter trigrams a little (helps with typos)."""
    v = [0.0] * DIM

    def add(feature: str, weight: float) -> None:
        h = zlib.crc32(feature.encode())
        v[h % DIM] += weight if (h >> 16) & 1 else -weight

    for w in _tokens(text):
        add("w:" + w, 1.0)
        for i in range(len(w) - 2):
            add("c:" + w[i:i + 3], 0.25)
    norm = math.sqrt(sum(x * x for x in v))
    return [round(x / norm, 5) for x in v] if norm else v


def chunk(text: str, size: int = 260) -> list[str]:
    """Splits a document into chunks of a few sentences each."""
    parts, current = [], ""
    for piece in re.split(r"(?<=[.!?])\s+|\n+", text.strip()):
        piece = piece.strip()
        if not piece:
            continue
        if current and len(current) + len(piece) + 1 > size:
            parts.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        parts.append(current)
    return parts


def user_scope(user_id: str) -> str:
    return "user:" + user_id


def add_document(scope: str, title: str, text: str) -> int:
    """Chunks, embeds and stores a document. The same chunk is stored once per scope."""
    added = 0
    for part in chunk(text):
        added += db.execute(
            "INSERT INTO kb_chunks (scope, title, content, embedding) VALUES (%s, %s, %s, %s::jsonb) "
            "ON CONFLICT (scope, content) DO NOTHING",
            (scope, title[:120], part, json.dumps(embed(f"{title}. {part}"))),
        )
    return added


def delete_document(scope: str, title: str) -> int:
    return db.execute("DELETE FROM kb_chunks WHERE scope = %s AND title = %s", (scope, title))


def delete_scope(scope: str) -> int:
    return db.execute("DELETE FROM kb_chunks WHERE scope = %s", (scope,))


def search(user_id: str, query: str, k: int = TOP_K) -> list[dict]:
    """Hybrid retrieval over the shop's documents and this user's own private
    chunks. Nobody else's private chunks are even read from the database.

    Two rankings are made and fused:
      1. vector: cosine similarity between the query embedding and each chunk embedding
      2. lexical: BM25 on the words
    Reciprocal Rank Fusion (RRF) adds 1 / (60 + rank) from each ranking, so a
    chunk that both methods like comes first."""
    rows = db.query(
        "SELECT scope, title, content, embedding FROM kb_chunks WHERE scope = %s OR scope = %s",
        (SHOP, user_scope(user_id)),
    )
    if not rows:
        return []
    q_vec, q_words = embed(query), set(_tokens(query))

    vector = [sum(a * b for a, b in zip(q_vec, r["embedding"])) for r in rows]

    docs = [_tokens(f"{r['title']} {r['content']}") for r in rows]
    avg_len = sum(len(d) for d in docs) / len(docs) or 1
    lexical = []
    for d in docs:
        score = 0.0
        for w in q_words:
            tf = d.count(w)
            if tf:
                df = sum(1 for other in docs if w in other)
                idf = math.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(d) / avg_len))
        lexical.append(score)

    fused = [0.0] * len(rows)
    for scores, floor in ((vector, MIN_SCORE), (lexical, 0.0)):
        ranked = sorted((i for i in range(len(rows)) if scores[i] > floor), key=lambda i: scores[i], reverse=True)
        for rank, i in enumerate(ranked):
            fused[i] += 1 / (60 + rank)

    best = sorted((i for i in range(len(rows)) if fused[i] > 0), key=lambda i: fused[i], reverse=True)[:k]
    return [{"private": rows[i]["scope"] != SHOP, "title": rows[i]["title"], "content": rows[i]["content"],
             "score": round(fused[i], 4)} for i in best]


# Demo documents for the demo shop. The seller can edit them in the dashboard.
SEED_DOCS = [
    ("Delivery",
     "We deliver all over Pakistan by courier. Delivery to Karachi, Lahore and Islamabad takes 2 to 3 working days. "
     "Delivery to other cities takes 4 to 6 working days. The delivery charge is Rs 250 per order. "
     "Delivery is free on orders above Rs 5,000. We do not deliver outside Pakistan yet."),
    ("Returns and damaged items",
     "You can return any item within 7 days of delivery if it is unused and in its original packing. "
     "If an item arrives damaged, send us a photo within 48 hours and we send a free replacement. "
     "Personalised and made-to-order items cannot be returned."),
    ("Payment",
     "We accept cash on delivery everywhere in Pakistan. We also accept bank transfer, Easypaisa and JazzCash. "
     "Orders above Rs 15,000 need advance payment."),
    ("Product care",
     "Blue pottery: hand wash with mild soap. It is microwave safe but not dishwasher safe. "
     "Ajrak: wash separately in cold water the first time, because the natural dyes can run. "
     "Leather khussa and Peshawari chappal: keep them dry, they soften after a few wears. "
     "Camel skin lamp: wipe with a dry cloth and keep it away from water. "
     "Brass: polish with lemon and a soft cloth to keep the shine."),
    ("About Dastkari",
     "Dastkari works with artisan families in Multan, Hala, Karachi and Peshawar. "
     "Every piece is handmade, so small differences in colour and pattern are normal. "
     "We offer free gift wrap and a handwritten note on request."),
]


def seed() -> None:
    """Loads the demo documents the first time the shop starts."""
    if db.query("SELECT 1 FROM kb_chunks WHERE scope = %s LIMIT 1", (SHOP,)):
        return
    for title, text in SEED_DOCS:
        add_document(SHOP, title, text)
