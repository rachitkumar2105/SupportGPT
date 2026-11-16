import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Icon } from "../components/Icon";
import { ErrorNote, PriorityChip, Skeleton, SlaCord, StatusChip, useToast } from "../components/ui";
import { api, post, type Category, type Priority, type Ticket } from "../lib/api";
import { useAuth } from "../lib/auth";
import { cap, relative } from "../lib/format";

function TicketRow({ t, staff, me }: { t: Ticket; staff: boolean; me?: number }) {
  return (
    <Link to={`/app/tickets/${t.id}`} className="row">
      <div style={{ display: "grid", gap: 6, minWidth: 0 }}>
        <span className="row-title">{t.subject}</span>
        <span className="row-meta">
          <span className="num">#{t.id}</span>
          <PriorityChip p={t.priority} />
          <StatusChip s={t.status} />
          <span>{cap(t.category)}</span>
          {staff && <span>{t.customer.name}</span>}
          {t.triage_source === "sample" && <span className="chip">Sample</span>}
          {staff && t.assignee && <span>{t.assignee.id === me ? "Assigned to you" : `Assigned to ${t.assignee.name}`}</span>}
          <span>Opened {relative(t.created_at)}</span>
        </span>
      </div>
      <SlaCord created={t.created_at} due={t.sla_due_at} status={t.status} />
    </Link>
  );
}

export function MyTickets() {
  const toast = useToast();
  const nav = useNavigate();
  const [items, setItems] = useState<Ticket[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [composing, setComposing] = useState(false);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setErr(null);
    api<Ticket[]>("/api/tickets?status=all")
      .then(setItems)
      .catch((e) => setErr(e.message));
  }, []);
  useEffect(load, [load]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const t = await post<Ticket>("/api/tickets", { subject, body });
      toast("Ticket opened");
      nav(`/app/tickets/${t.id}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 style={{ fontSize: "clamp(1.6rem, 1.2rem + 1.4vw, 2.2rem)" }}>My tickets</h1>
          <p>Conversations you handed to a person, and requests you opened directly.</p>
        </div>
        <button className="btn" onClick={() => setComposing((v) => !v)} aria-expanded={composing}>
          <Icon name="plus" /> Open a ticket
        </button>
      </div>

      {composing && (
        <form className="reply-box" onSubmit={create} style={{ marginBottom: 18 }}>
          <div className="field">
            <label htmlFor="t-subj">Subject</label>
            <input id="t-subj" value={subject} onChange={(e) => setSubject(e.target.value)} minLength={3} maxLength={150} required />
          </div>
          <div className="field">
            <label htmlFor="t-body">What's going on?</label>
            <textarea id="t-body" rows={5} value={body} onChange={(e) => setBody(e.target.value)} minLength={5} maxLength={4000} required />
            <span className="hint">Include what you tried and any error codes. Never include passwords or card numbers.</span>
          </div>
          <div className="reply-actions">
            <span className="faint">Tip: asking in chat first is usually faster.</span>
            <button className="btn primary" disabled={busy}>
              {busy ? <span className="spinner" /> : null} Open ticket
            </button>
          </div>
        </form>
      )}

      {err && <ErrorNote text={err} retry={load} />}
      {!items && !err && (
        <div className="list">
          {[1, 2].map((i) => (
            <div className="row" key={i}>
              <Skeleton h={40} />
            </div>
          ))}
        </div>
      )}
      {items && items.length === 0 && (
        <div className="empty">
          <h2>No tickets yet</h2>
          <p className="muted">
            Most questions are answered in chat. When the help center can't answer, "Talk to a person" opens a ticket with your
            conversation attached.
          </p>
          <Link className="btn primary" to="/app/chat">
            <Icon name="chat" /> Ask a question
          </Link>
        </div>
      )}
      {items && items.length > 0 && (
        <div className="list">
          {items.map((t) => (
            <TicketRow key={t.id} t={t} staff={false} />
          ))}
        </div>
      )}
    </div>
  );
}

export function Queue() {
  const { user } = useAuth();
  const [items, setItems] = useState<Ticket[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [status, setStatus] = useState("active");
  const [priority, setPriority] = useState<"" | Priority>("");
  const [category, setCategory] = useState<"" | Category>("");
  const [mine, setMine] = useState(false);
  const [q, setQ] = useState("");

  const load = useCallback(() => {
    setErr(null);
    const p = new URLSearchParams({ status });
    if (priority) p.set("priority", priority);
    if (category) p.set("category", category);
    if (mine) p.set("mine", "true");
    if (q.trim()) p.set("q", q.trim());
    api<Ticket[]>(`/api/tickets?${p}`)
      .then(setItems)
      .catch((e) => setErr(e.message));
  }, [status, priority, category, mine, q]);

  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [load, q]);

  const breached = items?.filter((t) => t.status !== "resolved" && new Date(t.sla_due_at).getTime() < Date.now()).length ?? 0;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 style={{ fontSize: "clamp(1.6rem, 1.2rem + 1.4vw, 2.2rem)" }}>Ticket queue</h1>
          <p>
            Sorted by response deadline. Each ticket arrives triaged by the model (category, priority, summary), and the cord
            shows how much of its response window is left.
          </p>
        </div>
        {breached > 0 && (
          <span className="chip urgent">
            <span className="dot" /> {breached} past due
          </span>
        )}
      </div>

      <div className="filters" role="group" aria-label="Filter tickets">
        <div className="seg">
          {[
            ["active", "Needs action"],
            ["resolved", "Resolved"],
            ["all", "All"],
          ].map(([v, l]) => (
            <button key={v} aria-pressed={status === v} onClick={() => setStatus(v)}>
              {l}
            </button>
          ))}
        </div>
        <label className="sr-only" htmlFor="f-pri">
          Priority
        </label>
        <select id="f-pri" value={priority} onChange={(e) => setPriority(e.target.value as Priority | "")}>
          <option value="">Any priority</option>
          {["urgent", "high", "medium", "low"].map((p) => (
            <option key={p} value={p}>
              {cap(p)}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="f-cat">
          Category
        </label>
        <select id="f-cat" value={category} onChange={(e) => setCategory(e.target.value as Category | "")}>
          <option value="">Any category</option>
          {["billing", "account", "technical", "data", "other"].map((c) => (
            <option key={c} value={c}>
              {cap(c)}
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="f-q">
          Search
        </label>
        <input id="f-q" type="search" placeholder="Search subject or summary" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn" aria-pressed={mine} onClick={() => setMine((m) => !m)} style={mine ? { borderColor: "var(--switch)" } : undefined}>
          {mine ? <Icon name="check" size={18} /> : null} Assigned to me
        </button>
      </div>

      {err && <ErrorNote text={err} retry={load} />}
      {!items && !err && (
        <div className="list">
          {[1, 2, 3].map((i) => (
            <div className="row" key={i}>
              <Skeleton h={44} />
            </div>
          ))}
        </div>
      )}
      {items && items.length === 0 && (
        <div className="empty">
          <h2>{status === "active" ? "Queue is clear" : "No tickets match"}</h2>
          <p className="muted">
            {status === "active"
              ? "New tickets appear here when a customer hands a conversation to a person, or opens one directly."
              : "Try a different filter."}
          </p>
        </div>
      )}
      {items && items.length > 0 && (
        <div className="list">
          {items.map((t) => (
            <TicketRow key={t.id} t={t} staff me={user?.id} />
          ))}
        </div>
      )}
    </div>
  );
}
