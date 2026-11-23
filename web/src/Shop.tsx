import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, Fact, Order, Product, randomId, rupees, store, ToolCall } from "./api";

type Msg = { role: "user" | "bot"; text: string; tools?: ToolCall[]; tokens?: { in: number; out: number } };
type Tab = "chat" | "orders" | "memory";

const TOOL_LABELS: Record<string, string> = {
  search_products: "Searched the catalogue",
  place_order: "Prepared an order",
  cancel_order: "Prepared a cancellation",
  confirm_action: "Completed it",
  my_orders: "Checked your orders",
  remember: "Saved to memory",
};

const STARTERS = [
  "What gifts do you have under Rs 2000?",
  "Show me something for the kitchen",
  "What have I ordered before?",
];

const msgKey = (user: string, thread: string) => `shopbot_msgs_${user}_${thread}`;
const loadMsgs = (user: string, thread: string): Msg[] => {
  try { return JSON.parse(store.get(msgKey(user, thread), "[]")); } catch { return []; }
};

export default function Shop() {
  // Who is shopping, and which conversation is open. Both survive a page reload.
  const [userId, setUserId] = useState(() => {
    const saved = store.get("shopbot_user", "");
    if (saved.startsWith("web-")) return saved;
    const fresh = randomId("web-guest");
    store.set("shopbot_user", fresh);
    return fresh;
  });
  const [threadId, setThreadId] = useState(() => {
    const saved = store.get("shopbot_thread", "");
    if (saved) return saved;
    const fresh = randomId("chat");
    store.set("shopbot_thread", fresh);
    return fresh;
  });

  const [products, setProducts] = useState<Product[] | null>(null);
  const [waking, setWaking] = useState(false);
  const [category, setCategory] = useState("all");
  const [orders, setOrders] = useState<Order[]>([]);
  const [facts, setFacts] = useState<Fact[]>([]);
  const [messages, setMessages] = useState<Msg[]>(() => loadMsgs(userId, threadId));
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<Tab>("chat");
  const [chatOpen, setChatOpen] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [switchError, setSwitchError] = useState("");
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);

  // The free API host sleeps when idle, so keep trying until it wakes up.
  const loadProducts = useCallback(async () => {
    for (let attempt = 0; attempt < 8; attempt++) {
      try {
        setProducts(await api.products());
        setWaking(false);
        return;
      } catch {
        setWaking(true);
        await new Promise((r) => setTimeout(r, 6000));
      }
    }
  }, []);

  const loadMine = useCallback(async (user: string) => {
    try {
      const [o, f] = await Promise.all([api.orders(user), api.memory(user)]);
      setOrders(o);
      setFacts(f);
    } catch { /* shown as empty lists; the chat still works */ }
  }, []);

  useEffect(() => { loadProducts(); }, [loadProducts]);
  useEffect(() => { loadMine(userId); }, [userId, loadMine]);
  useEffect(() => { store.set(msgKey(userId, threadId), JSON.stringify(messages.slice(-60))); }, [messages, userId, threadId]);
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight }); }, [messages, busy, tab]);

  const categories = useMemo(
    () => ["all", ...Array.from(new Set((products ?? []).map((p) => p.category)))],
    [products],
  );
  const shown = (products ?? []).filter((p) => category === "all" || p.category === category);

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setTab("chat");
    setChatOpen(true);
    setDraft("");
    setMessages((m) => [...m, { role: "user", text: message }]);
    setBusy(true);
    try {
      const r = await api.chat(userId, threadId, message);
      setMessages((m) => [...m, { role: "bot", text: r.reply, tools: r.tool_calls, tokens: r.tokens }]);
      const used = r.tool_calls.map((t) => t.name);
      if (used.includes("confirm_action")) loadProducts();
      if (used.includes("confirm_action") || used.includes("remember") || /my name is|call me/i.test(message)) loadMine(userId);
    } catch {
      setMessages((m) => [...m, { role: "bot", text: "ShopBot did not answer. It may be waking up. Send your message again in a moment." }]);
    } finally {
      setBusy(false);
    }
  }

  function newChat() {
    const fresh = randomId("chat");
    store.set("shopbot_thread", fresh);
    setThreadId(fresh);
    setMessages([]);
    setTab("chat");
  }

  async function switchUser(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const name = String(new FormData(e.currentTarget).get("name") || "").trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
    if (!name) return;
    const id = "web-" + name;
    try {
      setOrders(await api.orders(id)); // fails if another device already owns this name
    } catch {
      setSwitchError("That name is already used on another device. Pick a different one.");
      return;
    }
    const fresh = randomId("chat");
    store.set("shopbot_user", id);
    store.set("shopbot_thread", fresh);
    setUserId(id);
    setThreadId(fresh);
    setMessages([]);
    setSwitching(false);
    setSwitchError("");
  }

  async function forgetMe() {
    await api.forget(userId).catch(() => null);
    setFacts([]);
  }

  const last = messages[messages.length - 1];
  const awaitingConfirm =
    !busy && last?.role === "bot" &&
    !!last.tools?.some((t) => t.name === "place_order" || t.name === "cancel_order") &&
    !last.tools?.some((t) => t.name === "confirm_action");

  return (
    <div className="page">
      <div className="tileband" aria-hidden="true" />
      <header className="topbar">
        <a className="brand" href="#/">
          <span className="brand-name">Dastkari</span>
          <span className="brand-urdu" lang="ur">دستکاری</span>
        </a>
        <nav className="topnav">
          <a href="#/admin">Seller dashboard</a>
        </nav>
      </header>

      <div className="layout">
        <main className="shop">
          <section className="hero">
            <h1>Handmade in Pakistan, sent from the workshop to your door.</h1>
            <p>
              Blue pottery from Multan, truck art from Karachi, ajrak from Sindh. Not sure what to pick?
              Ask ShopBot. It knows every item, remembers what you like and takes your order.
            </p>
            <button className="btn btn-primary hero-cta" onClick={() => setChatOpen(true)}>Ask ShopBot</button>
          </section>

          <div className="filters" role="tablist" aria-label="Product categories">
            {categories.map((c) => (
              <button key={c} role="tab" aria-selected={c === category}
                className={"chip" + (c === category ? " chip-on" : "")} onClick={() => setCategory(c)}>
                {c === "all" ? "Everything" : c[0].toUpperCase() + c.slice(1)}
              </button>
            ))}
          </div>

          {products === null && (
            <p className="notice">
              {waking ? "Waking up the shop. The first visit can take up to a minute." : "Loading products…"}
            </p>
          )}

          <ul className="grid">
            {shown.map((p) => (
              <li key={p.id} className="card">
                <div className="card-art" aria-hidden="true">{p.emoji}</div>
                <div className="card-body">
                  <h2>{p.name}</h2>
                  <p className="card-desc">{p.description}</p>
                  <div className="card-row">
                    <span className="price">{rupees(p.price)}</span>
                    <span className={"stock" + (p.stock === 0 ? " stock-out" : p.stock <= 5 ? " stock-low" : "")}>
                      {p.stock === 0 ? "Sold out" : p.stock <= 5 ? `Only ${p.stock} left` : "In stock"}
                    </span>
                  </div>
                  <div className="card-actions">
                    <button className="btn" onClick={() => send(`Tell me about the ${p.name}`)}>Ask</button>
                    <button className="btn btn-primary" disabled={p.stock === 0}
                      onClick={() => send(`I want to order 1 ${p.name}`)}>Order</button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </main>

        <aside className={"assistant" + (chatOpen ? " assistant-open" : "")} aria-label="ShopBot assistant">
          <div className="assistant-head">
            <div>
              <strong>ShopBot</strong>
              <span className="assistant-sub">Sales assistant for Dastkari</span>
            </div>
            <button className="btn btn-quiet close-chat" onClick={() => setChatOpen(false)}>Close</button>
          </div>

          <div className="who">
            {switching ? (
              <form onSubmit={switchUser} className="who-form">
                <input name="name" placeholder="Customer name, e.g. sara" autoFocus maxLength={30} aria-label="Customer name" />
                <button className="btn btn-primary" type="submit">Switch</button>
                <button className="btn btn-quiet" type="button" onClick={() => { setSwitching(false); setSwitchError(""); }}>Cancel</button>
                {switchError && <p className="error who-error" role="alert">{switchError}</p>}
              </form>
            ) : (
              <>
                <span>Shopping as <b>{userId.replace(/^web-/, "")}</b></span>
                <button className="link" onClick={() => setSwitching(true)}>Switch customer</button>
              </>
            )}
          </div>

          <div className="tabs" role="tablist">
            {(["chat", "orders", "memory"] as Tab[]).map((t) => (
              <button key={t} role="tab" aria-selected={tab === t} className={"tab" + (tab === t ? " tab-on" : "")}
                onClick={() => setTab(t)}>
                {t === "chat" ? "Chat" : t === "orders" ? `My orders (${orders.length})` : `Memory (${facts.length})`}
              </button>
            ))}
          </div>

          {tab === "chat" && (
            <>
              <div className="messages" ref={listRef} aria-live="polite">
                {messages.length === 0 && (
                  <div className="empty">
                    <p>Ask for a product, a gift idea or your order. Try one of these:</p>
                    {STARTERS.map((s) => (
                      <button key={s} className="starter" onClick={() => send(s)}>{s}</button>
                    ))}
                  </div>
                )}
                {messages.map((m, i) => (
                  <div key={i} className={"msg msg-" + m.role}>
                    <p>{m.text}</p>
                    {m.tools && m.tools.length > 0 && (
                      <div className="tools">
                        {Array.from(new Set(m.tools.map((t) => TOOL_LABELS[t.name] ?? t.name))).map((label) => <span key={label} className="tool">{label}</span>)}
                      </div>
                    )}
                  </div>
                ))}
                {busy && <div className="msg msg-bot msg-typing"><p>ShopBot is thinking…</p></div>}
                {awaitingConfirm && (
                  <div className="confirm">
                    <button className="btn btn-primary" onClick={() => send("Yes, please confirm.")}>Yes, confirm</button>
                    <button className="btn" onClick={() => send("No, don't do that.")}>No, leave it</button>
                  </div>
                )}
              </div>
              <form className="composer" onSubmit={(e) => { e.preventDefault(); send(draft); }}>
                <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Message ShopBot"
                  aria-label="Message ShopBot" maxLength={500} />
                <button className="btn btn-primary" type="submit" disabled={busy || !draft.trim()}>Send</button>
              </form>
              <button className="link new-chat" onClick={newChat}>Start a new conversation</button>
            </>
          )}

          {tab === "orders" && (
            <div className="panel">
              {orders.length === 0 && <p className="empty-note">No orders yet. Ask ShopBot to order something for you.</p>}
              {orders.map((o) => (
                <div key={o.id} className="row">
                  <div>
                    <b>#{o.id}</b> {o.quantity} × {o.product_name}
                    <div className="muted">{new Date(o.created_at).toLocaleDateString()}</div>
                  </div>
                  <div className="row-end">
                    <span>{rupees(o.total)}</span>
                    <span className={"badge badge-" + o.status}>{o.status}</span>
                  </div>
                </div>
              ))}
            </div>
          )}

          {tab === "memory" && (
            <div className="panel">
              <p className="muted">
                What ShopBot remembers about you across conversations. Only you see this.
              </p>
              {facts.length === 0 && <p className="empty-note">Nothing yet. Tell ShopBot your name or what you like.</p>}
              <ul className="facts">{facts.map((f) => <li key={f.id}>{f.fact}</li>)}</ul>
              {facts.length > 0 && <button className="btn" onClick={forgetMe}>Forget everything about me</button>}
            </div>
          )}
        </aside>
      </div>

      {!chatOpen && <button className="fab btn btn-primary" onClick={() => setChatOpen(true)}>Ask ShopBot</button>}
      <footer className="foot">
        Dastkari is a demo shop built for the FAST-NUCES Agentic AI hackathon. Orders are not real.
      </footer>
    </div>
  );
}
