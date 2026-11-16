// Thin fetch wrapper: same-origin /api (Vercel rewrites it to the Hugging Face Space),
// HttpOnly session cookies, double-submit CSRF header, and one silent refresh on 401.

export type Role = "customer" | "agent" | "admin";

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  is_demo: boolean;
  is_active: boolean;
  created_at: string;
}

export interface Source {
  n: number;
  chunk_id: number;
  document_id: number;
  doc_title: string;
  doc_slug: string;
  heading: string | null;
  page: number | null;
  snippet: string;
  dense: number;
  bm25: number;
  dense_rank: number | null;
  bm25_rank: number | null;
  rrf: number;
}

export interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  sources: Source[] | null;
  confidence: number | null;
  abstained: boolean;
  latency_ms: number | null;
  model: string | null;
  feedback: number;
  created_at: string;
}

export interface Conversation {
  id: number;
  title: string;
  status: "active" | "escalated";
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
  ticket_id: number | null;
}

export interface Person {
  id: number;
  name: string;
  email: string;
}

export type Priority = "low" | "medium" | "high" | "urgent";
export type Category = "billing" | "account" | "technical" | "data" | "other";
export type TicketStatus = "open" | "pending" | "resolved";

export interface Ticket {
  id: number;
  subject: string;
  summary: string;
  category: Category;
  priority: Priority;
  sentiment: string;
  triage_source: string;
  status: TicketStatus;
  sla_due_at: string;
  first_response_at: string | null;
  resolved_at: string | null;
  csat: number | null;
  created_at: string;
  updated_at: string;
  customer: Person;
  assignee: Person | null;
  conversation_id: number | null;
}

export interface TicketMessage {
  id: number;
  kind: "customer" | "agent" | "note" | "system";
  body: string;
  ai_assisted: boolean;
  created_at: string;
  author_name: string | null;
}

export interface TicketDetail extends Ticket {
  messages: TicketMessage[];
  transcript: ChatMessage[];
  csat_comment: string | null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp("(?:^|; )" + name + "=([^;]*)"));
  return m ? decodeURIComponent(m[1]) : null;
}

let csrfMemory: string | null = null;
export function setCsrf(token: string | null) {
  csrfMemory = token;
}
function csrf(): string | null {
  return readCookie("sg_csrf") ?? csrfMemory;
}

let refreshing: Promise<boolean> | null = null;
let onSessionLost: (() => void) | null = null;
export function setSessionLostHandler(fn: () => void) {
  onSessionLost = fn;
}

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const r = await fetch("/api/auth/refresh", {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-CSRF-Token": csrf() ?? "" },
        });
        if (!r.ok) return false;
        const body = await r.json();
        setCsrf(body.csrf_token);
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

async function errorFrom(r: Response): Promise<ApiError> {
  let message = `Request failed (${r.status}).`;
  try {
    const body = await r.json();
    if (typeof body.detail === "string") message = body.detail;
  } catch {
    if (r.status === 502 || r.status === 503 || r.status === 504)
      message = "The server is waking up. Give it a few seconds and try again.";
  }
  if (r.status === 429) message = message || "Too many requests. Please wait a moment.";
  return new ApiError(r.status, message);
}

export async function raw(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== "GET" && method !== "HEAD") {
    const t = csrf();
    if (t) headers.set("X-CSRF-Token", t);
  }
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let r: Response;
  try {
    r = await fetch(path, { ...init, method, headers, credentials: "same-origin" });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
  }
  if (r.status === 401 && retry && !path.startsWith("/api/auth/")) {
    if (await tryRefresh()) return raw(path, init, false);
    onSessionLost?.();
  }
  if (r.status === 403 && retry && method !== "GET") {
    // A stale CSRF token after a refresh in another tab: refresh once and retry.
    const body = await r.clone().json().catch(() => ({}));
    if (typeof body.detail === "string" && body.detail.includes("session token") && (await tryRefresh()))
      return raw(path, init, false);
  }
  return r;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const r = await raw(path, init);
  if (!r.ok) throw await errorFrom(r);
  if (r.status === 204) return undefined as T;
  return r.json() as Promise<T>;
}

export const post = <T,>(path: string, body?: unknown) =>
  api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T,>(path: string, body: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const del = (path: string) => api<void>(path, { method: "DELETE" });

export type StreamEvent =
  | { event: "meta"; data: { user_message_id: number; masked_cards: number } }
  | { event: "sources"; data: { sources: Source[]; confidence: number } }
  | { event: "token"; data: { t: string } }
  | { event: "replace"; data: { text: string; sources: Source[] } }
  | { event: "done"; data: { message_id: number; confidence: number; abstained: boolean; latency_ms: number; model: string | null } }
  | { event: "error"; data: { detail: string } };

export async function streamMessage(
  conversationId: number,
  content: string,
  onEvent: (e: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const r = await raw(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
    signal,
  });
  if (!r.ok || !r.body) throw await errorFrom(r);
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent({ event, data: JSON.parse(data) } as StreamEvent);
    }
  }
}
