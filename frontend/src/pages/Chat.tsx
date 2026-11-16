import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { CitedAnswer, ConfidenceMeter, FeedbackButtons } from "../components/Answer";
import { Icon } from "../components/Icon";
import { ErrorNote, Skeleton, useToast } from "../components/ui";
import {
  api,
  del,
  post,
  streamMessage,
  type ChatMessage,
  type Conversation,
  type ConversationDetail,
  type Source,
} from "../lib/api";
import { relative } from "../lib/format";

const STARTERS = [
  "I was charged twice for my renewal",
  "How do I turn on two-factor login?",
  "My third laptop won't sync",
  "Can I get a refund on the annual plan?",
];

interface Live {
  text: string;
  sources: Source[];
  confidence: number | null;
  done: boolean;
  abstained: boolean;
}

let thresholdCache: number | null = null; // fetched from /api/health

export default function Chat() {
  const { id } = useParams();
  const convId = id ? Number(id) : null;
  const nav = useNavigate();
  const toast = useToast();
  const [list, setList] = useState<Conversation[] | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [busy, setBusy] = useState(false);
  const [showList, setShowList] = useState(false);
  const [escalating, setEscalating] = useState(false);
  const [note, setNote] = useState("");
  const [threshold, setThreshold] = useState(thresholdCache ?? 0.57);
  const bodyRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const justCreated = useRef<number | null>(null);

  const loadList = useCallback(() => {
    api<Conversation[]>("/api/conversations")
      .then(setList)
      .catch(() => setList([]));
  }, []);

  useEffect(() => {
    loadList();
    if (thresholdCache === null)
      fetch("/api/health")
        .then((r) => r.json())
        .then((h) => {
          thresholdCache = h.abstain_threshold;
          setThreshold(h.abstain_threshold);
        })
        .catch(() => {});
  }, [loadList]);

  useEffect(() => {
    if (convId !== null && convId === justCreated.current) return; // we navigated here mid-stream
    abortRef.current?.abort();
    setLive(null);
    setPending(null);
    setLoadErr(null);
    setEscalating(false);
    if (!convId) {
      setDetail(null);
      return;
    }
    api<ConversationDetail>(`/api/conversations/${convId}`)
      .then(setDetail)
      .catch((e) => setLoadErr(e.message));
  }, [convId]);

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight, behavior: "smooth" });
  }, [detail?.messages.length, live?.text, pending]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || busy) return;
    setBusy(true);
    setDraft("");
    setPending(content);
    setLive({ text: "", sources: [], confidence: null, done: false, abstained: false });
    let cid = convId;
    try {
      if (!cid) {
        const c = await post<Conversation>("/api/conversations");
        cid = c.id;
        justCreated.current = c.id;
        nav(`/app/chat/${c.id}`, { replace: true });
        setDetail({ ...c, messages: [], ticket_id: null });
      }
      abortRef.current = new AbortController();
      await streamMessage(
        cid!,
        content,
        (e) => {
          if (e.event === "sources") setLive((l) => l && { ...l, sources: e.data.sources, confidence: e.data.confidence });
          else if (e.event === "token") setLive((l) => l && { ...l, text: l.text + e.data.t });
          else if (e.event === "replace") setLive((l) => l && { ...l, text: e.data.text, sources: e.data.sources });
          else if (e.event === "done") setLive((l) => l && { ...l, done: true, abstained: e.data.abstained });
          else if (e.event === "error") toast(e.data.detail, "error");
          else if (e.event === "meta" && e.data.masked_cards)
            toast("We hid the card number you typed. Never share full card numbers in chat.");
        },
        abortRef.current.signal,
      );
      const fresh = await api<ConversationDetail>(`/api/conversations/${cid}`);
      setDetail(fresh);
      setLive(null);
      setPending(null);
      loadList();
      justCreated.current = null;
    } catch (e) {
      setLive(null);
      setPending(null);
      setDraft(content);
      if ((e as Error).name !== "AbortError") toast((e as Error).message, "error");
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  };

  const feedback = async (m: ChatMessage, v: -1 | 0 | 1) => {
    try {
      const upd = await post<ChatMessage>(`/api/messages/${m.id}/feedback`, { value: v });
      setDetail((d) => d && { ...d, messages: d.messages.map((x) => (x.id === m.id ? upd : x)) });
      if (v === -1) toast("Thanks. If the answer missed, you can hand this to a person.");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const escalate = async () => {
    if (!convId) return;
    setBusy(true);
    try {
      const r = await post<{ ticket_id: number }>(`/api/conversations/${convId}/escalate`, { note: note.trim() || null });
      toast("Ticket opened. A specialist will reply here and by ticket.");
      nav(`/app/tickets/${r.ticket_id}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (c: Conversation) => {
    if (!window.confirm(`Delete "${c.title}"? This removes the conversation for good.`)) return;
    try {
      await del(`/api/conversations/${c.id}`);
      setList((l) => l?.filter((x) => x.id !== c.id) ?? null);
      if (c.id === convId) nav("/app/chat");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  const messages = detail?.messages ?? [];
  const escalated = detail?.status === "escalated";
  const hasAnswer = messages.some((m) => m.role === "assistant");
  const lastAbstained = [...messages].reverse().find((m) => m.role === "assistant")?.abstained;

  return (
    <div className="chat-layout">
      <aside className={`convo-list${showList ? " open" : ""}`} aria-label="Your conversations">
        <header>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <h2 style={{ fontSize: "1.1rem" }}>Conversations</h2>
            <button className="btn ghost icon-btn mobile-only" onClick={() => setShowList(false)}>
              <Icon name="x" />
              <span className="sr-only">Close list</span>
            </button>
          </div>
          <button
            className="btn primary"
            onClick={() => {
              setShowList(false);
              nav("/app/chat");
              setTimeout(() => inputRef.current?.focus(), 50);
            }}
          >
            <Icon name="plus" /> New question
          </button>
        </header>
        <div className="convo-items">
          {list === null && [1, 2, 3].map((i) => <Skeleton key={i} h={48} />)}
          {list?.length === 0 && <p className="faint" style={{ padding: "8px 12px" }}>Your questions will show up here.</p>}
          {list?.map((c) => (
            <div key={c.id} style={{ display: "flex", alignItems: "center", gap: 2 }}>
              <Link
                to={`/app/chat/${c.id}`}
                className={`convo-item${c.id === convId ? " active" : ""}`}
                onClick={() => setShowList(false)}
              >
                <strong>{c.title}</strong>
                <span className="faint">
                  {c.status === "escalated" ? "With a specialist, " : ""}
                  {relative(c.updated_at)}
                </span>
              </Link>
              <button className="fb-btn" onClick={() => remove(c)} title="Delete conversation">
                <Icon name="trash" size={16} />
                <span className="sr-only">Delete {c.title}</span>
              </button>
            </div>
          ))}
        </div>
      </aside>

      <section className="thread" aria-label="Conversation">
        <div className="thread-head">
          <button className="btn ghost icon-btn mobile-only" onClick={() => setShowList(true)} title="Conversations">
            <Icon name="menu" />
            <span className="sr-only">Show conversations</span>
          </button>
          <h2>{detail?.title ?? "Ask the Fieldnote help center"}</h2>
          {detail && hasAnswer && !escalated && (
            <button className={`btn sm ${lastAbstained ? "lamp" : ""}`} onClick={() => setEscalating((v) => !v)} aria-expanded={escalating}>
              <Icon name="handoff" size={18} /> Talk to a person
            </button>
          )}
          {escalated && detail?.ticket_id && (
            <Link className="btn sm" to={`/app/tickets/${detail.ticket_id}`}>
              <Icon name="ticket" size={18} /> View ticket
            </Link>
          )}
        </div>

        <div className="thread-body" ref={bodyRef}>
          <div className="thread-inner">
            {loadErr && <ErrorNote text={loadErr} />}
            {!convId && !pending && (
              <div className="empty">
                <h2>What do you need help with?</h2>
                <p className="muted">
                  Answers come from the Fieldnote help center (Fieldnote is a fictional app used for this demo), with each
                  claim linked to the article it came from. If the help center doesn't cover it, you'll be offered a person
                  instead of a guess.
                </p>
                <div className="suggestions">
                  {STARTERS.map((s) => (
                    <button key={s} className="suggestion" onClick={() => send(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="bubble-user">
                  {m.content}
                </div>
              ) : (
                <div key={m.id} style={{ display: "grid", gap: 8 }}>
                  <CitedAnswer text={m.content} sources={m.sources ?? []} abstained={m.abstained} />
                  <div className="answer-foot">
                    {m.confidence !== null && <ConfidenceMeter value={m.confidence} threshold={threshold} />}
                    {m.latency_ms !== null && !m.abstained && <span className="num">{(m.latency_ms / 1000).toFixed(1)}s</span>}
                    {!m.abstained && <FeedbackButtons value={m.feedback} onChange={(v) => feedback(m, v)} />}
                  </div>
                </div>
              ),
            )}

            {pending && <div className="bubble-user">{pending}</div>}
            {live && (
              <div style={{ display: "grid", gap: 8 }} aria-live="polite">
                {live.text ? (
                  <CitedAnswer text={live.text} sources={live.sources} streaming={!live.done} abstained={live.abstained} />
                ) : (
                  <div className="answer-foot">
                    <span className="spinner" aria-hidden="true" />
                    {live.sources.length ? `Reading ${live.sources.length} help-center excerpts` : "Searching the help center"}
                  </div>
                )}
              </div>
            )}

            {escalating && !escalated && (
              <div className="reply-box" style={{ marginTop: 4 }}>
                <label htmlFor="esc-note" style={{ fontWeight: 700 }}>
                  Anything the specialist should know?
                </label>
                <textarea
                  id="esc-note"
                  rows={3}
                  maxLength={1000}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Optional. Your conversation is attached automatically."
                />
                <div className="reply-actions">
                  <span className="faint">We'll sort it by urgency and reply on the ticket.</span>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button className="btn ghost" onClick={() => setEscalating(false)}>
                      Cancel
                    </button>
                    <button className="btn primary" onClick={escalate} disabled={busy}>
                      {busy ? <span className="spinner" /> : <Icon name="handoff" size={18} />} Open a ticket
                    </button>
                  </div>
                </div>
              </div>
            )}
            {escalated && (
              <div className="notice">
                <Icon name="handoff" />
                <span>
                  A support specialist has this conversation now.{" "}
                  {detail?.ticket_id && <Link to={`/app/tickets/${detail.ticket_id}`}>Follow it on your ticket</Link>}.
                </span>
              </div>
            )}
          </div>
        </div>

        {!escalated && (
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              void send(draft);
            }}
          >
            <div className="composer-inner">
              <div className="composer-box">
                <label htmlFor="ask" className="sr-only">
                  Your question
                </label>
                <textarea
                  id="ask"
                  ref={inputRef}
                  rows={1}
                  maxLength={2000}
                  value={draft}
                  placeholder="Ask a question about Fieldnote"
                  onChange={(e) => {
                    setDraft(e.target.value);
                    e.target.style.height = "auto";
                    e.target.style.height = `${Math.min(180, e.target.scrollHeight)}px`;
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      void send(draft);
                    }
                  }}
                />
                <button className="btn primary icon-btn" type="submit" disabled={busy || !draft.trim()} title="Send">
                  {busy ? <span className="spinner" /> : <Icon name="up" />}
                  <span className="sr-only">Send</span>
                </button>
              </div>
              <div className="composer-row faint">
                <span>Enter to send, Shift+Enter for a new line. Don't share passwords or card numbers.</span>
                {draft.length > 1600 && <span className="num">{2000 - draft.length} left</span>}
              </div>
            </div>
          </form>
        )}
      </section>
    </div>
  );
}
