import { useCallback, useEffect, useState } from "react";
import { Icon } from "../components/Icon";
import { ErrorNote, Skeleton, useToast } from "../components/ui";
import { api, post } from "../lib/api";
import { dateTime, pct } from "../lib/format";

type Mode = "hybrid" | "dense" | "bm25";
interface Abst {
  threshold: number;
  precision: number;
  recall: number;
  false_refusal_rate: number;
  balanced_accuracy: number;
}
interface Metrics {
  n_answerable: number;
  n_out_of_scope: number;
  retrieval: Record<Mode, { "hit@1": number; "hit@3": number; "hit@5": number; mrr: number }>;
  abstention: { current: Abst; best: Abst; sweep: Abst[] };
  confidence: { answerable_median: number | null; out_of_scope_median: number | null };
  latency_ms: { mean: number | null; p95: number | null };
  hybrid_misses: { q: string; expected: string; got: string[]; rank: number | null }[];
}
interface Run {
  id: number;
  created_at: string;
  kb_version: number;
  n_questions: number;
  duration_ms: number;
  metrics: Metrics;
}

function Sweep({ sweep, current }: { sweep: Abst[]; current: number }) {
  const W = 640,
    H = 220,
    P = { l: 40, r: 12, t: 12, b: 30 };
  const xs = sweep.map((s) => s.threshold);
  const x0 = Math.min(...xs),
    x1 = Math.max(...xs);
  const X = (v: number) => P.l + ((v - x0) / (x1 - x0 || 1)) * (W - P.l - P.r);
  const Y = (v: number) => P.t + (1 - v) * (H - P.t - P.b);
  const line = (key: keyof Abst) => sweep.map((s, i) => `${i ? "L" : "M"}${X(s.threshold).toFixed(1)},${Y(s[key] as number).toFixed(1)}`).join(" ");
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="How refusal accuracy changes with the confidence threshold">
        <g className="grid">
          {[0, 0.25, 0.5, 0.75, 1].map((v) => (
            <g key={v}>
              <line x1={P.l} x2={W - P.r} y1={Y(v)} y2={Y(v)} />
              <text x={P.l - 8} y={Y(v) + 4} textAnchor="end">
                {Math.round(v * 100)}
              </text>
            </g>
          ))}
          {xs.filter((_, i) => i % 5 === 0).map((v) => (
            <text key={v} x={X(v)} y={H - 8} textAnchor="middle">
              {v.toFixed(2)}
            </text>
          ))}
        </g>
        <line x1={X(current)} x2={X(current)} y1={P.t} y2={H - P.b} stroke="var(--lamp)" strokeWidth="2" strokeDasharray="4 4" />
        <path d={line("balanced_accuracy")} fill="none" stroke="var(--switch)" strokeWidth="2.5" />
        <path d={line("recall")} fill="none" stroke="var(--ink-3)" strokeWidth="2" />
        <path d={line("false_refusal_rate")} fill="none" stroke="var(--cable)" strokeWidth="2" />
      </svg>
      <figcaption className="legend">
        <span><i style={{ background: "var(--switch)" }} />Balanced accuracy</span>
        <span><i style={{ background: "var(--ink-3)" }} />Out-of-scope questions refused</span>
        <span><i style={{ background: "var(--cable)" }} />Answerable questions wrongly refused</span>
        <span><i style={{ background: "var(--lamp)" }} />Current threshold</span>
      </figcaption>
    </figure>
  );
}

export default function Quality() {
  const toast = useToast();
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(() => {
    setErr(null);
    api<Run[]>("/api/admin/eval")
      .then(setRuns)
      .catch((e) => setErr(e.message));
  }, []);
  useEffect(load, [load]);

  const run = async () => {
    setRunning(true);
    try {
      await post("/api/admin/eval");
      toast("Evaluation finished");
      load();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setRunning(false);
    }
  };

  const latest = runs?.[0];
  const m = latest?.metrics;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 style={{ fontSize: "clamp(1.6rem, 1.2rem + 1.4vw, 2.2rem)" }}>Answer quality</h1>
          <p>
            A fixed set of hand-written questions, phrased differently from the articles, is run against the live index. In-scope
            questions check that the right article is retrieved; out-of-scope ones check that the assistant declines instead of
            guessing.
          </p>
        </div>
        <button className="btn primary" onClick={run} disabled={running}>
          {running ? <span className="spinner" /> : <Icon name="refresh" />} Run evaluation
        </button>
      </div>

      {err && <ErrorNote text={err} retry={load} />}
      {!runs && !err && <Skeleton h={200} />}
      {runs && !latest && (
        <div className="empty">
          <h2>No evaluation yet</h2>
          <p className="muted">Run one to measure retrieval and refusal accuracy on this deployment. It takes a few seconds and doesn't call the language model.</p>
        </div>
      )}

      {latest && m && (
        <>
          <p className="faint">
            Run #{latest.id}, {dateTime(latest.created_at)}: {m.n_answerable} answerable and {m.n_out_of_scope} out-of-scope questions,
            knowledge base version {latest.kb_version}, {(latest.duration_ms / 1000).toFixed(1)}s.
          </p>
          <div className="stat-grid" style={{ marginTop: 12 }}>
            <div className="stat">
              <b>{pct(m.retrieval.hybrid["hit@1"])}</b>
              <span>Right article ranked first</span>
            </div>
            <div className="stat">
              <b>{pct(m.retrieval.hybrid["hit@3"])}</b>
              <span>Right article in the top 3</span>
            </div>
            <div className="stat">
              <b className="num">{m.retrieval.hybrid.mrr.toFixed(3)}</b>
              <span>Mean reciprocal rank</span>
            </div>
            <div className="stat">
              <b>{pct(m.abstention.current.recall)}</b>
              <span>Out-of-scope questions declined</span>
              <small>at threshold {m.abstention.current.threshold.toFixed(2)}</small>
            </div>
            <div className="stat">
              <b>{pct(m.abstention.current.false_refusal_rate)}</b>
              <span>Answerable questions declined</span>
            </div>
            <div className="stat">
              <b className="num">{m.latency_ms.p95 ?? "n/a"} ms</b>
              <span>Retrieval p95 (embed + search)</span>
            </div>
          </div>

          <section className="section">
            <h2 style={{ fontSize: "1.2rem" }}>Hybrid against each ranker alone</h2>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Ranker</th>
                    <th>Top 1</th>
                    <th>Top 3</th>
                    <th>Top 5</th>
                    <th>MRR</th>
                  </tr>
                </thead>
                <tbody>
                  {(["hybrid", "dense", "bm25"] as Mode[]).map((k) => (
                    <tr key={k}>
                      <td>{k === "hybrid" ? "Hybrid (RRF)" : k === "dense" ? "Vectors only" : "BM25 only"}</td>
                      <td className="num">{pct(m.retrieval[k]["hit@1"], 1)}</td>
                      <td className="num">{pct(m.retrieval[k]["hit@3"], 1)}</td>
                      <td className="num">{pct(m.retrieval[k]["hit@5"], 1)}</td>
                      <td className="num">{m.retrieval[k].mrr.toFixed(3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="section">
            <h2 style={{ fontSize: "1.2rem" }}>Choosing the refusal threshold</h2>
            <p className="muted" style={{ maxWidth: "70ch" }}>
              Median best-match score is {m.confidence.answerable_median?.toFixed(3)} for answerable questions and{" "}
              {m.confidence.out_of_scope_median?.toFixed(3)} for out-of-scope ones. The best balanced threshold on this set is{" "}
              {m.abstention.best.threshold.toFixed(2)} ({pct(m.abstention.best.balanced_accuracy, 1)} balanced accuracy).
            </p>
            <div className="panel" style={{ padding: 16 }}>
              <Sweep sweep={m.abstention.sweep} current={m.abstention.current.threshold} />
            </div>
          </section>

          {m.hybrid_misses.length > 0 && (
            <section className="section">
              <h2 style={{ fontSize: "1.2rem" }}>Questions where the right article wasn't first</h2>
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Question</th>
                      <th>Expected</th>
                      <th>Ranked</th>
                      <th>Top results</th>
                    </tr>
                  </thead>
                  <tbody>
                    {m.hybrid_misses.map((x) => (
                      <tr key={x.q}>
                        <td>{x.q}</td>
                        <td>{x.expected}</td>
                        <td className="num">{x.rank ?? "not in top 5"}</td>
                        <td className="faint">{x.got.join(", ")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </>
      )}
    </div>
  );
}
