import { useCallback, useEffect, useState } from "react";
import { ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { cap, pct } from "../lib/format";

interface Analytics {
  window_days: number;
  conversations: number;
  questions: number;
  answers: number;
  deflection_rate: number | null;
  abstention_rate: number | null;
  helpful_rate: number | null;
  feedback: { up: number; down: number };
  latency_ms: { p50: number | null; p95: number | null };
  median_confidence: number | null;
  injection_flags: number;
  tickets: {
    created: number;
    open_now: number;
    sla_breached_now: number;
    by_category: Record<string, number>;
    by_priority: Record<string, number>;
    triage_by_llm: number;
    median_first_response_h: number | null;
    csat_avg: number | null;
    csat_count: number;
  };
  llm: { keys: Record<string, number>; models: Record<string, number> };
  series: { date: string; conversations: number; escalations: number; abstained: number }[];
  kb: { chunks: number; kb_version: number };
}

function Trend({ series }: { series: Analytics["series"] }) {
  const W = 720,
    H = 200,
    P = { l: 32, r: 10, t: 10, b: 26 };
  const max = Math.max(1, ...series.map((s) => Math.max(s.conversations, s.escalations)));
  const X = (i: number) => P.l + (i / Math.max(1, series.length - 1)) * (W - P.l - P.r);
  const Y = (v: number) => P.t + (1 - v / max) * (H - P.t - P.b);
  const path = (k: "conversations" | "escalations" | "abstained") =>
    series.map((s, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(s[k]).toFixed(1)}`).join(" ");
  const ticks = [0, Math.round(max / 2), max];
  return (
    <figure style={{ margin: 0 }}>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart" role="img" aria-label="Daily conversations and escalations">
        <g className="grid">
          {ticks.map((v) => (
            <g key={v}>
              <line x1={P.l} x2={W - P.r} y1={Y(v)} y2={Y(v)} />
              <text x={P.l - 6} y={Y(v) + 4} textAnchor="end">
                {v}
              </text>
            </g>
          ))}
          {series.map((s, i) =>
            i % Math.ceil(series.length / 7) === 0 ? (
              <text key={s.date} x={X(i)} y={H - 6} textAnchor="middle">
                {new Date(s.date + "T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric" })}
              </text>
            ) : null,
          )}
        </g>
        <path d={path("conversations")} fill="none" stroke="var(--switch)" strokeWidth="2.5" strokeLinejoin="round" />
        <path d={path("escalations")} fill="none" stroke="var(--lamp)" strokeWidth="2.5" strokeLinejoin="round" />
        <path d={path("abstained")} fill="none" stroke="var(--ink-3)" strokeWidth="1.8" strokeDasharray="5 4" />
      </svg>
      <figcaption className="legend">
        <span><i style={{ background: "var(--switch)" }} />Conversations</span>
        <span><i style={{ background: "var(--lamp)" }} />Handed to a person</span>
        <span><i style={{ background: "var(--ink-3)" }} />Declined (not in help center)</span>
      </figcaption>
    </figure>
  );
}

function Bars({ data }: { data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map((e) => e[1]));
  if (!entries.length) return <p className="faint">No tickets in this window.</p>;
  return (
    <div className="bars">
      {entries.map(([k, v]) => (
        <div className="bar-row" key={k}>
          <span>{cap(k)}</span>
          <span className="bar-track" aria-hidden="true">
            <i style={{ width: `${(v / max) * 100}%` }} />
          </span>
          <span className="num" style={{ textAlign: "right" }}>
            {v}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function Insights() {
  const [days, setDays] = useState(14);
  const [a, setA] = useState<Analytics | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    setErr(null);
    setA(null);
    api<Analytics>(`/api/admin/analytics?days=${days}`)
      .then(setA)
      .catch((e) => setErr(e.message));
  }, [days]);
  useEffect(load, [load]);

  const keys = a ? Object.entries(a.llm.keys) : [];
  const totalCalls = keys.reduce((s, [, v]) => s + v, 0);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 style={{ fontSize: "clamp(1.6rem, 1.2rem + 1.4vw, 2.2rem)" }}>Insights</h1>
          <p>Real usage of this deployment only. Sample tickets and demo accounts are excluded.</p>
        </div>
        <div className="seg" role="group" aria-label="Time window">
          {[7, 14, 30].map((d) => (
            <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>
              {d} days
            </button>
          ))}
        </div>
      </div>
      {err && <ErrorNote text={err} retry={load} />}
      {!a && !err && <Skeleton h={260} />}
      {a && (
        <>
          <div className="stat-grid">
            <div className="stat">
              <b className="num">{a.conversations}</b>
              <span>Conversations</span>
              <small>{a.questions} questions asked</small>
            </div>
            <div className="stat">
              <b>{pct(a.deflection_rate)}</b>
              <span>Resolved without a person</span>
              <small>answered and never escalated</small>
            </div>
            <div className="stat">
              <b>{pct(a.abstention_rate)}</b>
              <span>Answers declined</span>
              <small>not covered by the help center</small>
            </div>
            <div className="stat">
              <b>{pct(a.helpful_rate)}</b>
              <span>Rated helpful</span>
              <small>
                {a.feedback.up} up, {a.feedback.down} down
              </small>
            </div>
            <div className="stat">
              <b className="num">{a.latency_ms.p50 ? `${(a.latency_ms.p50 / 1000).toFixed(1)}s` : "n/a"}</b>
              <span>Median answer time</span>
              <small>p95 {a.latency_ms.p95 ? `${(a.latency_ms.p95 / 1000).toFixed(1)}s` : "n/a"}, full stream</small>
            </div>
            <div className="stat">
              <b className="num">{a.tickets.open_now}</b>
              <span>Open tickets</span>
              <small>{a.tickets.sla_breached_now} past their deadline</small>
            </div>
          </div>

          <section className="section">
            <h2 style={{ fontSize: "1.2rem" }}>Daily activity</h2>
            <div className="panel" style={{ padding: 16 }}>
              <Trend series={a.series} />
            </div>
          </section>

          <div className="split2 section">
            <div className="panel" style={{ padding: 16, display: "grid", gap: 12, alignContent: "start" }}>
              <h3>Tickets by category</h3>
              <Bars data={a.tickets.by_category} />
              <p className="faint">
                {a.tickets.created} created, {a.tickets.triage_by_llm} triaged by the model. Median first response{" "}
                {a.tickets.median_first_response_h !== null ? `${a.tickets.median_first_response_h}h` : "n/a"}. CSAT{" "}
                {a.tickets.csat_avg !== null ? `${a.tickets.csat_avg} of 5 (${a.tickets.csat_count} ratings)` : "n/a"}.
              </p>
            </div>
            <div className="panel" style={{ padding: 16, display: "grid", gap: 12, alignContent: "start" }}>
              <h3>Model and key usage</h3>
              {totalCalls === 0 ? (
                <p className="faint">No model calls in this window.</p>
              ) : (
                <>
                  <Bars data={a.llm.keys} />
                  <p className="faint">
                    Primary key serves calls until it hits a rate limit; the secondary takes over automatically. Models used:{" "}
                    {Object.entries(a.llm.models)
                      .map(([k, v]) => `${k} (${v})`)
                      .join(", ")}
                    .
                  </p>
                </>
              )}
              <p className="faint">
                {a.injection_flags} messages looked like prompt-injection attempts and were answered under the normal rules. Index:{" "}
                {a.kb.chunks} passages, version {a.kb.kb_version}.
              </p>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
