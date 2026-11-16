import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { CitedAnswer } from "../components/Answer";
import { Icon } from "../components/Icon";
import { ErrorNote, Initials, PriorityChip, Skeleton, SlaCord, StatusChip, useToast } from "../components/ui";
import { api, patch, post, type Source, type TicketDetail, type User } from "../lib/api";
import { isStaff, useAuth } from "../lib/auth";
import { cap, dateTime, relative } from "../lib/format";

export default function TicketView() {
  const { id } = useParams();
  const { user } = useAuth();
  const staff = isStaff(user);
  const toast = useToast();
  const [t, setT] = useState<TicketDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [agents, setAgents] = useState<User[]>([]);
  const [body, setBody] = useState("");
  const [internal, setInternal] = useState(false);
  const [aiUsed, setAiUsed] = useState(false);
  const [draftSources, setDraftSources] = useState<Source[]>([]);
  const [drafting, setDrafting] = useState(false);
  const [sending, setSending] = useState(false);
  const [score, setScore] = useState(0);
  const [comment, setComment] = useState("");

  const load = useCallback(() => {
    setErr(null);
    api<TicketDetail>(`/api/tickets/${id}`)
      .then(setT)
      .catch((e) => setErr(e.message));
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    if (staff) api<User[]>("/api/admin/agents").then(setAgents).catch(() => {});
  }, [staff]);

  if (err) return <div className="page"><ErrorNote text={err} retry={load} /></div>;
  if (!t)
    return (
      <div className="page" style={{ display: "grid", gap: 12 }}>
        <Skeleton h={32} w="60%" />
        <Skeleton h={120} />
        <Skeleton h={80} />
      </div>
    );

  const update = async (change: Record<string, unknown>) => {
    try {
      setT(await patch<TicketDetail>(`/api/tickets/${t.id}`, change));
      toast("Ticket updated");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const draft = async () => {
    setDrafting(true);
    try {
      const d = await post<{ text: string; sources: Source[] }>(`/api/tickets/${t.id}/draft`);
      setBody(d.text);
      setDraftSources(d.sources);
      setInternal(false);
      setAiUsed(true);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setDrafting(false);
    }
  };

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!body.trim()) return;
    setSending(true);
    try {
      setT(await post<TicketDetail>(`/api/tickets/${t.id}/messages`, { body, internal, ai_assisted: aiUsed && !internal }));
      setBody("");
      setAiUsed(false);
      setDraftSources([]);
      toast(internal ? "Note added" : "Reply sent");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSending(false);
    }
  };

  const rate = async () => {
    try {
      setT(await post<TicketDetail>(`/api/tickets/${t.id}/csat`, { score, comment: comment.trim() || null }));
      toast("Thanks for the rating");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const kindLabel = (k: string, name: string | null) =>
    k === "note" ? `${name ?? "Agent"} (internal note)` : k === "system" ? "" : name ?? (k === "agent" ? "Support" : "Customer");

  return (
    <div className="page">
      <Link to={staff ? "/app/queue" : "/app/tickets"} className="btn ghost sm" style={{ marginBottom: 10, paddingLeft: 6 }}>
        <Icon name="back" size={18} /> {staff ? "Queue" : "My tickets"}
      </Link>
      <div className="page-head" style={{ alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <h1 style={{ fontSize: "clamp(1.4rem, 1.1rem + 1.2vw, 2rem)" }}>{t.subject}</h1>
          <div className="row-meta" style={{ marginTop: 10 }}>
            <span className="num">#{t.id}</span>
            <PriorityChip p={t.priority} />
            <StatusChip s={t.status} />
            <span>{cap(t.category)}</span>
            <span>Opened {relative(t.created_at)}</span>
            <SlaCord created={t.created_at} due={t.sla_due_at} status={t.status} />
          </div>
        </div>
      </div>

      <div className="ticket-grid">
        <div style={{ display: "grid", gap: 16, minWidth: 0 }}>
          {staff && (
            <div className="panel" style={{ padding: 16, display: "grid", gap: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                <h3>Summary for the agent</h3>
                <span className="faint">
                  {t.triage_source === "llm"
                    ? "Triaged by the model"
                    : t.triage_source === "sample"
                      ? "Sample ticket"
                      : "Triaged by keyword rules (model unavailable)"}
                  , sentiment {t.sentiment}
                </span>
              </div>
              <p style={{ whiteSpace: "pre-wrap" }}>{t.summary}</p>
            </div>
          )}

          {t.transcript.length > 0 && (
            <details className="transcript" open={staff}>
              <summary>Chat before hand-off ({t.transcript.length} messages)</summary>
              <div className="inner">
                {t.transcript.map((m) =>
                  m.role === "user" ? (
                    <div key={m.id} className="bubble-user">
                      {m.content}
                    </div>
                  ) : (
                    <CitedAnswer key={m.id} text={m.content} sources={m.sources ?? []} abstained={m.abstained} />
                  ),
                )}
              </div>
            </details>
          )}

          <div className="timeline" aria-label="Ticket messages">
            {t.messages.map((m) => (
              <article key={m.id} className={`tmsg ${m.kind}`}>
                {m.kind !== "system" && (
                  <header>
                    <strong>{kindLabel(m.kind, m.author_name)}</strong>
                    <time dateTime={m.created_at} title={dateTime(m.created_at)}>
                      {relative(m.created_at)}
                    </time>
                    {m.ai_assisted && staff && <span className="chip">Drafted with AI, edited by agent</span>}
                  </header>
                )}
                <div className="body">{m.body}</div>
              </article>
            ))}
          </div>

          {(staff || t.status !== "resolved") && (
            <form className={`reply-box${internal ? " internal" : ""}`} onSubmit={send}>
              {staff && (
                <div className="reply-actions">
                  <div className="seg" role="group" aria-label="Message type">
                    <button type="button" aria-pressed={!internal} onClick={() => setInternal(false)}>
                      Reply to customer
                    </button>
                    <button type="button" aria-pressed={internal} onClick={() => setInternal(true)}>
                      Internal note
                    </button>
                  </div>
                  <button type="button" className="btn sm" onClick={draft} disabled={drafting}>
                    {drafting ? <span className="spinner" /> : <Icon name="pen" size={18} />} Draft a reply
                  </button>
                </div>
              )}
              <label htmlFor="reply" className="sr-only">
                Message
              </label>
              <textarea
                id="reply"
                rows={staff ? 6 : 4}
                maxLength={4000}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                placeholder={staff ? (internal ? "Only agents see notes." : "Write a reply, or draft one from the help center.") : "Add more detail or reply to the agent"}
              />
              {draftSources.length > 0 && !internal && (
                <p className="faint">
                  Draft grounded in: {draftSources.map((s) => s.doc_title).filter((v, i, a) => a.indexOf(v) === i).join(", ")}. Check
                  anything in [square brackets] before sending.
                </p>
              )}
              <div className="reply-actions">
                <span className="faint">{!staff && "Our team replies here. You'll see it next time you open this ticket."}</span>
                <button className="btn primary" disabled={sending || !body.trim()}>
                  {sending ? <span className="spinner" /> : <Icon name="send" size={18} />}
                  {internal ? "Add note" : staff ? "Send reply" : "Send"}
                </button>
              </div>
            </form>
          )}

          {!staff && t.status === "resolved" && t.csat === null && (
            <div className="reply-box">
              <h3>How did we do?</h3>
              <div className="stars" role="group" aria-label="Rating from 1 to 5">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button key={n} type="button" aria-pressed={score === n} onClick={() => setScore(n)}>
                    {n}
                  </button>
                ))}
              </div>
              <textarea rows={2} maxLength={500} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Optional comment" aria-label="Comment" />
              <div>
                <button className="btn primary" disabled={!score} onClick={rate}>
                  Send rating
                </button>
              </div>
            </div>
          )}
          {t.csat !== null && (
            <p className="faint">
              Rated {t.csat} of 5{t.csat_comment ? `: "${t.csat_comment}"` : ""}
            </p>
          )}
        </div>

        <aside className="side">
          {staff ? (
            <div className="panel">
              <h3>Handling</h3>
              <div className="field">
                <label htmlFor="s-status">Status</label>
                <select id="s-status" value={t.status} onChange={(e) => update({ status: e.target.value })}>
                  <option value="open">Open</option>
                  <option value="pending">Waiting on customer</option>
                  <option value="resolved">Resolved</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="s-pri">Priority</label>
                <select id="s-pri" value={t.priority} onChange={(e) => update({ priority: e.target.value })}>
                  {["urgent", "high", "medium", "low"].map((p) => (
                    <option key={p} value={p}>
                      {cap(p)}
                    </option>
                  ))}
                </select>
                <span className="hint">Changing priority resets the response deadline from when the ticket opened.</span>
              </div>
              <div className="field">
                <label htmlFor="s-cat">Category</label>
                <select id="s-cat" value={t.category} onChange={(e) => update({ category: e.target.value })}>
                  {["billing", "account", "technical", "data", "other"].map((c) => (
                    <option key={c} value={c}>
                      {cap(c)}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="s-asg">Assignee</label>
                <select id="s-asg" value={t.assignee?.id ?? 0} onChange={(e) => update({ assignee_id: Number(e.target.value) })}>
                  <option value={0}>Unassigned</option>
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                      {a.id === user?.id ? " (you)" : ""}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          ) : null}
          <div className="panel">
            <h3>Details</h3>
            {staff && (
              <div className="who" style={{ padding: 0 }}>
                <Initials name={t.customer.name} />
                <div className="who-text">
                  <strong>{t.customer.name}</strong>
                  <span>{t.customer.email}</span>
                </div>
              </div>
            )}
            <dl className="kv">
              <dt>Response due</dt>
              <dd className="num">{dateTime(t.sla_due_at)}</dd>
              <dt>First response</dt>
              <dd className="num">{t.first_response_at ? relative(t.first_response_at) : "Not yet"}</dd>
              {t.resolved_at && (
                <>
                  <dt>Resolved</dt>
                  <dd className="num">{relative(t.resolved_at)}</dd>
                </>
              )}
              {!staff && (
                <>
                  <dt>Handled by</dt>
                  <dd>{t.assignee?.name ?? "Next available agent"}</dd>
                </>
              )}
            </dl>
          </div>
        </aside>
      </div>
    </div>
  );
}
