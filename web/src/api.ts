// All calls to the agent API live here.
export const API = (import.meta.env.VITE_API_URL || "https://shopbot-api-vnny.onrender.com").replace(/\/$/, "");

export type Product = {
  id: number; name: string; description: string; category: string;
  price: number; stock: number; emoji: string; active?: boolean;
};
export type Order = {
  id: number; user_id?: string; product_name: string; quantity: number;
  total: number; status: string; created_at: string;
};
export type Fact = { id: string; fact: string };
export type ToolCall = { name: string; args: Record<string, unknown> };
export type ChatReply = { reply: string; tool_calls: ToolCall[]; tokens: { in: number; out: number } };
export type ChatLog = {
  id: number; user_id: string; thread_id: string; message: string; reply: string;
  tool_calls: ToolCall[]; tokens_in: number; tokens_out: number; blocked: boolean; agent: string; created_at: string;
};
export type KbDoc = { title: string; content: string; chunks: number };
export type Stats = {
  chats: number; users: number; conversations: number; tokens_in: number; tokens_out: number;
  blocked: number; with_tools: number; orders: number; revenue: number; cancelled: number;
  daily: { day: string; chats: number; tokens: number }[];
  low_stock: { id: number; name: string; stock: number }[];
  agents: { agent: string; messages: number; avg_tokens: number }[];
};

// This browser's secret key. The API ties each website customer id to the first
// key that uses it, so knowing someone's id is not enough to read their data.
function userKey(): string {
  let key = store.get("shopbot_key", "");
  if (key.length < 16) {
    const bytes = new Uint8Array(24);
    crypto.getRandomValues(bytes);
    key = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    store.set("shopbot_key", key);
  }
  return key;
}

async function call<T>(path: string, init: RequestInit = {}, adminToken?: string): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (adminToken) headers["x-admin-token"] = adminToken;
  else headers["x-user-key"] = userKey();
  const res = await fetch(API + path, { ...init, headers });
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail).catch(() => "");
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json();
}

const q = (userId: string) => `?user_id=${encodeURIComponent(userId)}`;

export const api = {
  products: () => call<Product[]>("/products"),
  orders: (userId: string) => call<Order[]>("/orders" + q(userId)),
  memory: (userId: string) => call<Fact[]>("/memory" + q(userId)),
  forget: (userId: string) => call<{ deleted: number }>("/memory" + q(userId), { method: "DELETE" }),
  chat: (user_id: string, thread_id: string, message: string) =>
    call<ChatReply>("/chat", { method: "POST", body: JSON.stringify({ user_id, thread_id, message }) }),

  adminStats: (t: string) => call<Stats>("/admin/stats", {}, t),
  adminOrders: (t: string) => call<Order[]>("/admin/orders", {}, t),
  adminChats: (t: string) => call<ChatLog[]>("/admin/chats", {}, t),
  adminProducts: (t: string) => call<Product[]>("/admin/products", {}, t),
  adminKnowledge: (t: string) => call<KbDoc[]>("/admin/knowledge", {}, t),
  adminSaveDocument: (t: string, title: string, content: string) =>
    call<{ chunks: number }>("/admin/knowledge", { method: "POST", body: JSON.stringify({ title, content }) }, t),
  adminDeleteDocument: (t: string, title: string) =>
    call<{ deleted: number }>("/admin/knowledge?title=" + encodeURIComponent(title), { method: "DELETE" }, t),
  adminReset: (t: string) => call<{ reset: boolean }>("/admin/reset", { method: "POST" }, t),
  adminUploadCatalog: (t: string, products: Partial<Product>[]) =>
    call<{ added: number; updated: number }>("/admin/catalog", { method: "POST", body: JSON.stringify({ products }) }, t),
  adminSaveProduct: (t: string, p: Partial<Product>) =>
    call<{ id: number }>(p.id ? `/admin/products/${p.id}` : "/admin/products",
      { method: p.id ? "PUT" : "POST", body: JSON.stringify(p) }, t),
};

export const rupees = (n: number) => "Rs " + Number(n).toLocaleString("en-PK");

// localStorage can be unavailable (private mode), so never let it throw.
export const store = {
  get(key: string, fallback: string): string {
    try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
  },
  set(key: string, value: string) {
    try { localStorage.setItem(key, value); } catch { /* ignore */ }
  },
};

export const randomId = (prefix: string) =>
  prefix + "-" + Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-3);
