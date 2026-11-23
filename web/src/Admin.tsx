import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, ChatLog, KbDoc, Order, Product, rupees, Stats } from "./api";

const AGENT_NAMES: Record<string, string> = {
  sales: "Sales agent",
  support: "Support agent",
  guard: "Safety guard (no model)",
};

type View = "overview" | "orders" | "products" | "knowledge" | "chats";

const session = {
  get: () => { try { return sessionStorage.getItem("shopbot_admin") ?? ""; } catch { return ""; } },
  set: (v: string) => { try { v ? sessionStorage.setItem("shopbot_admin", v) : sessionStorage.removeItem("shopbot_admin"); } catch { /* ignore */ } },
};

export default function Admin() {
  const [token, setToken] = useState(session.get);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("overview");
  const [stats, setStats] = useState<Stats | null>(null);
  const [orders, setOrders] = useState<Order[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [chats, setChats] = useState<ChatLog[]>([]);
  const [docs, setDocs] = useState<KbDoc[]>([]);
  const [loading, setLoading] = useState(false);

  const [confirmReset, setConfirmReset] = useState(false);
  const [updated, setUpdated] = useState("");

  const load = useCallback(async (t: string, quiet = false) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const [s, o, p, c, k] = await Promise.all([
        api.adminStats(t), api.adminOrders(t), api.adminProducts(t), api.adminChats(t), api.adminKnowledge(t),
      ]);
      setStats(s); setOrders(o); setProducts(p); setChats(c); setDocs(k);
      session.set(t);
      setToken(t);
      setUpdated(new Date().toLocaleTimeString());
    } catch (e) {
      if (quiet) return; // a failed background refresh keeps the last numbers on screen
      session.set("");
      setToken("");
      setError(e instanceof Error ? e.message : "Could not sign in");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (token) load(token); /* eslint-disable-next-line */ }, []);

  // Live dashboard: fetch fresh numbers every 10 seconds while signed in.
  useEffect(() => {
    if (!token) return;
    const timer = setInterval(() => load(token, true), 10000);
    return () => clearInterval(timer);
  }, [token, load]);

  async function resetData() {
    await api.adminReset(token).catch(() => null);
    setConfirmReset(false);
    load(token);
  }

  function signIn(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    load(String(new FormData(e.currentTarget).get("password") || ""));
  }

  if (!token || !stats) {
    return (
      <div className="page">
        <div className="tileband" aria-hidden="true" />
        <form className="signin" onSubmit={signIn}>
          <h1>Seller dashboard</h1>
          <p>Enter the admin password to see orders, stock and conversations.</p>
          <input name="password" type="password" placeholder="Admin password" aria-label="Admin password" autoFocus required />
          <button className="btn btn-primary" type="submit" disabled={loading}>{loading ? "Signing in…" : "Sign in"}</button>
          {error && <p className="error" role="alert">{error}</p>}
          <a href="#/">Back to the shop</a>
        </form>
      </div>
    );
  }

  const maxChats = Math.max(1, ...stats.daily.map((d) => d.chats));

  return (
    <div className="page">
      <div className="tileband" aria-hidden="true" />
      <header className="topbar">
        <a className="brand" href="#/"><span className="brand-name">Dastkari</span><span className="brand-tag">Seller dashboard</span></a>
        <nav className="topnav">
          <span className="live"><span className="live-dot" aria-hidden="true" />Live, updated {updated}</span>
          <button className="link" onClick={() => load(token)}>{loading ? "Refreshing…" : "Refresh"}</button>
          <a href="#/">View shop</a>
          <button className="link" onClick={() => { session.set(""); setToken(""); setStats(null); }}>Sign out</button>
        </nav>
      </header>

      <main className="admin">
        <div className="tabs admin-tabs" role="tablist">
          {(["overview", "orders", "products", "knowledge", "chats"] as View[]).map((v) => (
            <button key={v} role="tab" aria-selected={view === v} className={"tab" + (view === v ? " tab-on" : "")} onClick={() => setView(v)}>
              {v === "overview" ? "Overview" : v === "orders" ? `Orders (${orders.length})` : v === "products" ? `Products (${products.length})` : v === "knowledge" ? `Knowledge (${docs.length})` : "Conversations"}
            </button>
          ))}
        </div>

        {view === "overview" && (
          <>
            <div className="stats">
              <Stat label="Revenue" value={rupees(stats.revenue)} note={`${stats.orders} ${stats.orders === 1 ? "order" : "orders"}, ${stats.cancelled} cancelled`} />
              <Stat label="Customers" value={stats.users} note={`${stats.conversations} ${stats.conversations === 1 ? "conversation" : "conversations"}`} />
              <Stat label="Messages answered" value={stats.chats} note={`${stats.with_tools} used a tool`} />
              <Stat label="Tokens used" value={(stats.tokens_in + stats.tokens_out).toLocaleString()}
                note={`${stats.tokens_in.toLocaleString()} in, ${stats.tokens_out.toLocaleString()} out`} />
              <Stat label="Blocked attempts" value={stats.blocked} note="Prompt injection stopped before the model" />
              <Stat label="Tokens per message" value={stats.chats ? Math.round((stats.tokens_in + stats.tokens_out) / stats.chats) : 0} note="Average, in and out" />
            </div>
            <div className="two">
              <section className="box">
                <h2>Messages per day</h2>
                {stats.daily.length === 0 && <p className="empty-note">No conversations yet.</p>}
                {[...stats.daily].reverse().map((d) => (
                  <div key={d.day} className="bar-row">
                    <span className="bar-label">{new Date(d.day).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</span>
                    <span className="bar"><span style={{ width: `${(d.chats / maxChats) * 100}%` }} /></span>
                    <span className="bar-num">{d.chats}</span>
                  </div>
                ))}
              </section>
              <section className="box">
                <h2>Running low</h2>
                {stats.low_stock.length === 0 && <p className="empty-note">Everything is well stocked.</p>}
                {stats.low_stock.map((p) => (
                  <div key={p.id} className="row">
                    <span>{p.name}</span>
                    <span className={"stock " + (p.stock === 0 ? "stock-out" : "stock-low")}>{p.stock === 0 ? "Sold out" : `${p.stock} left`}</span>
                  </div>
                ))}
              </section>
            </div>
            <section className="box agents-box">
              <h2>Who answered</h2>
              {(stats.agents ?? []).length === 0 && <p className="empty-note">No messages yet.</p>}
              {(stats.agents ?? []).map((a) => (
                <div key={a.agent} className="row">
                  <span>{AGENT_NAMES[a.agent] ?? a.agent}</span>
                  <span className="muted">{a.messages} {a.messages === 1 ? "message" : "messages"}, {a.avg_tokens.toLocaleString()} tokens each on average</span>
                </div>
              ))}
            </section>
            <section className="box reset-box">
              <h2>Start from zero</h2>
              <p className="muted">
                Deletes every order, conversation, remembered fact and message count. Products stay, and stock from deleted orders is put back. This cannot be undone.
              </p>
              {confirmReset ? (
                <div className="form-actions">
                  <button className="btn btn-danger" onClick={resetData}>Yes, delete all customer activity</button>
                  <button className="btn" onClick={() => setConfirmReset(false)}>Keep everything</button>
                </div>
              ) : (
                <button className="btn" onClick={() => setConfirmReset(true)}>Clear all customer activity</button>
              )}
            </section>
          </>
        )}

        {view === "orders" && (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Order</th><th>Customer</th><th>Item</th><th>Qty</th><th>Total</th><th>Status</th><th>Date</th></tr></thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id}>
                    <td>#{o.id}</td><td>{o.user_id}</td><td>{o.product_name}</td><td>{o.quantity}</td>
                    <td>{rupees(o.total)}</td><td><span className={"badge badge-" + o.status}>{o.status}</span></td>
                    <td>{new Date(o.created_at).toLocaleString()}</td>
                  </tr>
                ))}
                {orders.length === 0 && <tr><td colSpan={7} className="empty-note">No orders yet.</td></tr>}
              </tbody>
            </table>
          </div>
        )}

        {view === "products" && <Products token={token} products={products} onSaved={() => load(token)} />}

        {view === "knowledge" && <Knowledge token={token} docs={docs} onSaved={() => load(token, true)} />}

        {view === "chats" && (
          <div className="chatlog">
            {chats.length === 0 && <p className="empty-note">No conversations yet.</p>}
            {chats.map((c) => (
              <article key={c.id} className={"log" + (c.blocked ? " log-blocked" : "")}>
                <header>
                  <b>{c.user_id}</b> <span className="muted">in {c.thread_id}, {new Date(c.created_at).toLocaleString()}</span>
                  <span className="muted log-tokens">{c.tokens_in + c.tokens_out} tokens</span>
                </header>
                <p><span className="who-tag">Customer</span> {c.message}</p>
                <p><span className="who-tag">ShopBot</span> {c.reply}</p>
                <div className="tools">
                  {c.blocked && <span className="tool tool-blocked">Blocked by safety guard</span>}
                  {!c.blocked && c.agent && <span className="tool tool-agent">{AGENT_NAMES[c.agent] ?? c.agent}</span>}
                  {c.tool_calls.map((t, i) => <span key={i} className="tool">{t.name}</span>)}
                </div>
              </article>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string | number; note: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      <span className="muted">{note}</span>
    </div>
  );
}

// Small CSV reader that understands quoted cells.
function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], cell = "", quoted = false;
  const endRow = () => { row.push(cell); cell = ""; if (row.some((c) => c.trim())) rows.push(row); row = []; };
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; }
      else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n") endRow();
    else if (c !== "\r") cell += c;
  }
  endRow();
  return rows;
}

const SAMPLE_CSV =
  "name,description,category,price,stock,emoji\n" +
  'Clay Diya Set,"Set of 6 hand-painted clay lamps",home,650,30,🪔\n' +
  "Sindhi Topi,Mirror-work cap from Sindh,clothing,1400,12,🧢\n";

const BLANK: Partial<Product> = { name: "", description: "", category: "", price: 0, stock: 0, emoji: "🛍️", active: true };

function Products({ token, products, onSaved }: { token: string; products: Product[]; onSaved: () => void }) {
  const [editing, setEditing] = useState<Partial<Product> | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [uploadNote, setUploadNote] = useState("");

  // Seller uploads a catalog as a CSV file: name, description, category, price, stock, emoji.
  async function uploadCsv(file: File | undefined) {
    if (!file) return;
    setError("");
    setUploadNote("");
    try {
      const rows = parseCsv(await file.text());
      const head = rows[0].map((h) => h.trim().toLowerCase());
      const col = (r: string[], name: string) => (r[head.indexOf(name)] ?? "").trim();
      if (!head.includes("name") || !head.includes("price")) throw new Error("The file needs at least name and price columns.");
      const items = rows.slice(1).filter((r) => col(r, "name")).map((r) => ({
        name: col(r, "name"), description: col(r, "description"), category: col(r, "category").toLowerCase(),
        price: Math.round(Number(col(r, "price")) || 0), stock: Math.round(Number(col(r, "stock")) || 0),
        emoji: col(r, "emoji") || "🛍️", active: true,
      }));
      if (items.length === 0) throw new Error("No products found in the file.");
      const r = await api.adminUploadCatalog(token, items);
      setUploadNote(`Catalog uploaded: ${r.added} added, ${r.updated} updated.`);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not read that file");
    }
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setSaving(true);
    setError("");
    try {
      await api.adminSaveProduct(token, { ...editing, price: Number(editing.price), stock: Number(editing.stock) });
      setEditing(null);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the product");
    } finally {
      setSaving(false);
    }
  }

  const field = (key: keyof Product, value: string | number | boolean) => setEditing((p) => ({ ...p, [key]: value }));

  return (
    <>
      {editing ? (
        <form className="box product-form" onSubmit={save}>
          <h2>{editing.id ? `Edit ${editing.name}` : "Add a product"}</h2>
          <label>Name<input required value={editing.name ?? ""} onChange={(e) => field("name", e.target.value)} /></label>
          <label>Description<textarea rows={2} value={editing.description ?? ""} onChange={(e) => field("description", e.target.value)} /></label>
          <div className="form-row">
            <label>Category<input value={editing.category ?? ""} onChange={(e) => field("category", e.target.value)} /></label>
            <label>Emoji<input value={editing.emoji ?? ""} onChange={(e) => field("emoji", e.target.value)} maxLength={4} /></label>
            <label>Price (Rs)<input type="number" min={0} required value={editing.price ?? 0} onChange={(e) => field("price", e.target.value)} /></label>
            <label>Stock<input type="number" min={0} required value={editing.stock ?? 0} onChange={(e) => field("stock", e.target.value)} /></label>
          </div>
          <label className="check"><input type="checkbox" checked={editing.active ?? true} onChange={(e) => field("active", e.target.checked)} /> Show in the shop</label>
          {error && <p className="error" role="alert">{error}</p>}
          <div className="form-actions">
            <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? "Saving…" : "Save product"}</button>
            <button className="btn" type="button" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </form>
      ) : (
        <div className="catalog-tools">
          <button className="btn btn-primary" onClick={() => setEditing(BLANK)}>Add a product</button>
          <label className="btn">
            Upload catalog (CSV)
            <input type="file" accept=".csv,text/csv" hidden onChange={(e) => { uploadCsv(e.target.files?.[0]); e.target.value = ""; }} />
          </label>
          <a href={"data:text/csv;charset=utf-8," + encodeURIComponent(SAMPLE_CSV)} download="catalog-sample.csv">Download a sample file</a>
          {uploadNote && <span className="muted">{uploadNote}</span>}
          {error && <span className="error" role="alert">{error}</span>}
        </div>
      )}
      <div className="table-wrap">
        <table>
          <thead><tr><th></th><th>Product</th><th>Category</th><th>Price</th><th>Stock</th><th>Shown</th><th></th></tr></thead>
          <tbody>
            {products.map((p) => (
              <tr key={p.id} className={p.active ? "" : "row-off"}>
                <td>{p.emoji}</td><td>{p.name}</td><td>{p.category}</td><td>{rupees(p.price)}</td>
                <td><span className={"stock" + (p.stock === 0 ? " stock-out" : p.stock <= 5 ? " stock-low" : "")}>{p.stock}</span></td>
                <td>{p.active ? "Yes" : "Hidden"}</td>
                <td><button className="link" onClick={() => setEditing(p)}>Edit</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

// The shop's documents that ShopBot searches before answering (RAG).
function Knowledge({ token, docs, onSaved }: { token: string; docs: KbDoc[]; onSaved: () => void }) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.adminSaveDocument(token, title, content);
      setTitle("");
      setContent("");
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the document");
    } finally {
      setSaving(false);
    }
  }

  async function remove(t: string) {
    await api.adminDeleteDocument(token, t).catch(() => null);
    onSaved();
  }

  return (
    <>
      <p className="muted kb-note">
        ShopBot searches these documents before it answers questions about delivery, returns, payment and care.
        Customers' private notes and receipts are stored separately and are never shown here.
      </p>
      <form className="box product-form" onSubmit={save}>
        <h2>Add or replace a document</h2>
        <label>Title<input required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Eid sale" maxLength={120} /></label>
        <label>Text<textarea required rows={4} value={content} onChange={(e) => setContent(e.target.value)}
          placeholder="Write it in plain sentences. Saving with an existing title replaces that document." /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <div className="form-actions">
          <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? "Saving…" : "Save document"}</button>
        </div>
      </form>
      <div className="chatlog">
        {docs.map((d) => (
          <article key={d.title} className="log">
            <header>
              <b>{d.title}</b>
              <span className="muted">{d.chunks} {d.chunks === 1 ? "chunk" : "chunks"}</span>
              <button className="link log-tokens" onClick={() => remove(d.title)}>Delete</button>
            </header>
            <p>{d.content}</p>
          </article>
        ))}
        {docs.length === 0 && <p className="empty-note">No documents yet. Add one so ShopBot can answer shop questions.</p>}
      </div>
    </>
  );
}
