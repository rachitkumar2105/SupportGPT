import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { Icon, Logo } from "../components/Icon";
import { ServerStatus, ThemeButton, useToast } from "../components/ui";
import { useAuth } from "../lib/auth";
import { dateTime, pct } from "../lib/format";

const REPO = "https://github.com/rachitkumar2105/SupportGPT";

interface Scenario {
  q: string;
  jacks: { title: string; section: string; lit: boolean }[];
  match: number; // 0..1 position on the meter, illustrative
  answer?: string;
  handoff?: string;
}

const SCENARIOS: Scenario[] = [
  {
    q: "Can I still get my money back for this month?",
    jacks: [
      { title: "Refunds and cancellation", section: "Refund policy", lit: true },
      { title: "Plans and billing", section: "Changing plans", lit: false },
      { title: "Refunds and cancellation", section: "How long refunds take", lit: true },
    ],
    match: 0.86,
    answer:
      "Yes, if you ask within 14 days of the charge and haven't added more than 1 GB of new attachments [1]. Refunds go back to your card within 2 business days [2].",
  },
  {
    q: "Do you have a student discount?",
    jacks: [
      { title: "Plans and billing", section: "Plus plan", lit: false },
      { title: "Plans and billing", section: "Payment methods", lit: false },
      { title: "Getting started", section: "Creating your account", lit: false },
    ],
    match: 0.52,
    handoff: "Not in the help center. Handed to a person as a billing question, medium priority.",
  },
];
const THRESHOLD = 0.7;

function useReducedMotion() {
  const [r, setR] = useState(() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false);
  useEffect(() => {
    const m = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const on = () => setR(m.matches);
    m?.addEventListener("change", on);
    return () => m?.removeEventListener("change", on);
  }, []);
  return r;
}

/** The hero: one question at a time is patched through the board. */
function Switchboard() {
  const reduced = useReducedMotion();
  const [idx, setIdx] = useState(0);
  const [phase, setPhase] = useState(reduced ? 4 : 0); // 0 asked, 1 jacks shown, 2 lit, 3 meter, 4 result
  const [typed, setTyped] = useState(0);
  const [playing, setPlaying] = useState(!reduced);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const s = SCENARIOS[idx];

  useEffect(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    if (reduced || !playing) {
      setPhase(4);
      setTyped(s.answer?.length ?? 0);
      return;
    }
    setPhase(0);
    setTyped(0);
    const at = (ms: number, fn: () => void) => timers.current.push(setTimeout(fn, ms));
    at(700, () => setPhase(1));
    at(1500, () => setPhase(2));
    at(2300, () => setPhase(3));
    at(3000, () => setPhase(4));
    if (s.answer) {
      const len = s.answer.length;
      for (let i = 1; i <= len; i += 3) at(3000 + i * 14, () => setTyped(Math.min(len, i + 2)));
    }
    at(s.answer ? 3000 + s.answer.length * 14 + 3200 : 6800, () => setIdx((i) => (i + 1) % SCENARIOS.length));
    return () => timers.current.forEach(clearTimeout);
  }, [idx, playing, reduced, s.answer]);

  const parts = (s.answer ?? "").slice(0, typed).replace(/\[\d?$/, "").split(/(\[\d\])/g);

  return (
    <div className="board" aria-label="Illustration of how a question is answered or handed off">
      <div className="board-controls">
        <div className="seg" role="group" aria-label="Example question">
          <button aria-pressed={idx === 0} onClick={() => setIdx(0)}>
            Answerable
          </button>
          <button aria-pressed={idx === 1} onClick={() => setIdx(1)}>
            Not covered
          </button>
        </div>
        {!reduced && (
          <button className="btn ghost sm" onClick={() => setPlaying((p) => !p)} aria-pressed={!playing}>
            {playing ? "Pause" : "Play"}
          </button>
        )}
      </div>
      <div className="board-q">{s.q}</div>
      <div className="board-jacks" aria-hidden={phase < 1}>
        {s.jacks.map((j, i) => (
          <div
            key={`${idx}-${i}`}
            className={`bjack${phase >= 2 && j.lit ? " lit" : ""}`}
            style={{ opacity: phase >= 1 ? 1 : 0.25, transition: `opacity 300ms ${i * 90}ms` }}
          >
            <span className="lampdot" aria-hidden="true" />
            <strong style={{ color: "var(--ink)" }}>{j.title}</strong>
            <span>{j.section}</span>
          </div>
        ))}
      </div>
      <div className="board-route">
        <span className="meter-track" aria-hidden="true">
          <span
            className={`meter-fill${s.match < THRESHOLD ? " low" : ""}`}
            style={{ width: phase >= 3 ? `${s.match * 100}%` : "0%", transition: "width 600ms var(--ease)" }}
          />
          <span className="meter-mark" style={{ left: `${THRESHOLD * 100}%` }} />
        </span>
        <span>{phase < 3 ? "Searching the help center" : s.match >= THRESHOLD ? "Strong match: answer with sources" : "Weak match: don't guess"}</span>
      </div>
      {phase >= 4 && s.answer && (
        <div className="board-a">
          {parts.map((p, i) =>
            /^\[\d\]$/.test(p) ? (
              <span key={i} className="cite on" aria-label={`source ${p[1]}`}>
                {p[1]}
              </span>
            ) : (
              <span key={i}>{p}</span>
            ),
          )}
        </div>
      )}
      {phase >= 4 && s.handoff && (
        <div className="board-handoff">
          <Icon name="handoff" /> {s.handoff}
        </div>
      )}
    </div>
  );
}

interface Quality {
  created_at: string;
  n_answerable: number;
  n_out_of_scope: number;
  retrieval: Record<string, { "hit@1": number; "hit@3": number; mrr: number }>;
  abstention: { recall: number; false_refusal_rate: number; threshold: number };
}

export default function Landing() {
  const { user, demoAgent } = useAuth();
  const nav = useNavigate();
  const toast = useToast();
  const [quality, setQuality] = useState<Quality | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetch("/api/public/quality")
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => setQuality(b?.latest ?? null))
      .catch(() => {});
  }, []);

  const tryAgent = async () => {
    setBusy(true);
    try {
      await demoAgent();
      nav("/app/queue");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  const home = user ? (user.role === "customer" ? "/app/chat" : "/app/queue") : null;

  return (
    <>
      <header className="site-head">
        <Link to="/" className="brand" style={{ padding: 0 }}>
          <Logo /> SupportGPT
        </Link>
        <nav aria-label="Site">
          <ThemeButton />
          {home ? (
            <Link className="btn" to={home}>
              Open the app
            </Link>
          ) : (
            <>
              <Link className="btn ghost" to="/login">
                Sign in
              </Link>
              <Link className="btn primary" to="/signup">
                Create account
              </Link>
            </>
          )}
        </nav>
      </header>

      <main id="content">
        <section className="hero">
          <div>
            <h1>Support answers with the receipts attached.</h1>
            <p className="lede">
              SupportGPT answers customer questions from your help center and links every claim to the passage it came from. When
              the help center doesn't cover a question, it says so and hands the conversation to a person, already summarised and
              sorted by urgency.
            </p>
            <div className="ctas">
              <Link className="btn primary" to={home ?? "/signup"}>
                <Icon name="chat" /> Ask the demo help center
              </Link>
              <button className="btn" onClick={tryAgent} disabled={busy}>
                {busy ? <span className="spinner" /> : <Icon name="queue" />} Open the agent console
              </button>
            </div>
            <p className="faint" style={{ marginTop: 14 }}>
              The demo answers for Fieldnote, a fictional note-taking app. <ServerStatus />
            </p>
          </div>
          <Switchboard />
        </section>

        <section className="band" aria-labelledby="how">
          <h2 id="how">What happens to a question</h2>
          <div className="steps">
            <div className="step">
              <span className="n">1. Retrieve</span>
              <h3>Two searches, one ranking</h3>
              <p>
                Vector search catches paraphrases like "get my money back". Keyword search (BM25) catches exact terms like "E-402"
                or "Team plan". Their rankings are fused, so neither blind spot decides alone.
              </p>
            </div>
            <div className="step">
              <span className="n">2. Decide</span>
              <h3>Answer only on a strong match</h3>
              <p>
                If the best passage scores below a threshold tuned on a test set, the model is never asked. The customer is told it
                isn't covered and offered a person. The model can also decline when the passages don't contain the answer.
              </p>
            </div>
            <div className="step">
              <span className="n">3. Answer or hand off</span>
              <h3>Cited answers, triaged tickets</h3>
              <p>
                Answers stream with numbered citations wired to their sources. Hand-offs arrive in the agent queue with a category,
                priority, summary and response deadline, plus a reply draft grounded in the same articles.
              </p>
            </div>
          </div>
        </section>

        <section className="band proof" aria-labelledby="measured">
          <div>
            <h2 id="measured">Measured, not assumed</h2>
            <p>
              A set of hand-written questions, phrased differently from the articles, runs against the live index from the Answer
              quality page. Half the point is the questions it should refuse: a support bot that guesses is worse than one that
              says "let me get someone".
            </p>
            <p>
              <a href={`${REPO}#evaluation`} target="_blank" rel="noreferrer">
                How the evaluation works
              </a>
            </p>
          </div>
          {quality ? (
            <div>
              <div className="stat-grid">
                <div className="stat">
                  <b>{pct(quality.retrieval.hybrid["hit@1"])}</b>
                  <span>Right article ranked first</span>
                </div>
                <div className="stat">
                  <b>{pct(quality.retrieval.hybrid["hit@3"])}</b>
                  <span>Right article in the top 3</span>
                </div>
                <div className="stat">
                  <b>{pct(quality.abstention.recall)}</b>
                  <span>Out-of-scope questions declined</span>
                </div>
                <div className="stat">
                  <b>{pct(quality.abstention.false_refusal_rate)}</b>
                  <span>Answerable questions declined</span>
                </div>
              </div>
              <p className="faint" style={{ marginTop: 10 }}>
                Latest run on this deployment, {dateTime(quality.created_at)}: {quality.n_answerable} answerable and{" "}
                {quality.n_out_of_scope} out-of-scope questions, refusal threshold {quality.abstention.threshold.toFixed(2)}.
              </p>
            </div>
          ) : (
            <div className="panel" style={{ padding: 18 }}>
              <p className="muted">Live numbers appear here after the first evaluation run on this deployment.</p>
            </div>
          )}
        </section>

        <section className="band" aria-labelledby="built">
          <h2 id="built">Built for the boring parts too</h2>
          <div className="split2" style={{ marginTop: 18 }}>
            <div className="feature">
              <h3>Sessions that can't be lifted by a script</h3>
              <p>
                HttpOnly cookies, 15-minute access tokens, rotating refresh tokens with theft detection, CSRF tokens and an origin
                allowlist. Passwords are hashed with Argon2id; repeated failures lock the account.
              </p>
            </div>
            <div className="feature">
              <h3>Guardrails on what goes in</h3>
              <p>
                Card numbers typed into chat are masked before they're stored or sent to the model. Retrieved text is treated as data,
                and messages that look like prompt injection are flagged for review.
              </p>
            </div>
            <div className="feature">
              <h3>Keeps working when a provider doesn't</h3>
              <p>
                A rate-limited API key fails over to a second key, and a retired model falls through to the next one. If no model is
                reachable, customers get a clear way to reach a person instead of an error.
              </p>
            </div>
            <div className="feature">
              <h3>Roles that match a real desk</h3>
              <p>
                Customers see their own conversations and tickets. Agents work the queue with internal notes and drafts. Admins manage
                articles, people and the audit log.
              </p>
            </div>
          </div>
        </section>
      </main>

      <footer className="site-foot">
        <span>SupportGPT by Rachit Kumar Singh. Fieldnote is fictional.</span>
        <nav aria-label="Footer">
          <Link to="/privacy">Privacy</Link>
          <Link to="/terms">Terms</Link>
          <a href={REPO} target="_blank" rel="noreferrer">
            Source on GitHub
          </a>
          <a href="/api/docs" target="_blank" rel="noreferrer">
            API reference
          </a>
        </nav>
      </footer>
    </>
  );
}
