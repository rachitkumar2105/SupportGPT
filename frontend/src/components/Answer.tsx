import { Fragment, useLayoutEffect, useRef, useState } from "react";
import type { Source } from "../lib/api";
import { Icon } from "./Icon";

/** Renders an answer whose [n] citations are physically patched to their source cards:
 *  hovering, focusing or tapping a citation draws a cable to the excerpt it came from. */
// gpt-oss cites as 【1】; normalise so live streams and stored answers render the same.
const normalise = (t: string) =>
  t.replace(/\u3010\s*(\d+)(?:\s*\u2020[^\u3011]*)?\s*\u3011/g, "[$1]").replace(/\u3010[^\u3011]*$/, "");

export function CitedAnswer({
  text: rawText,
  sources,
  streaming,
  abstained,
}: {
  text: string;
  sources: Source[];
  streaming?: boolean;
  abstained?: boolean;
}) {
  const text = normalise(rawText);
  const box = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<number | null>(null);
  const [pinned, setPinned] = useState<number | null>(null);
  const [cables, setCables] = useState<{ d: string; len: number; key: string }[]>([]);
  const lit = active ?? pinned;
  const used = new Set([...text.matchAll(/\[(\d+)\]/g)].map((m) => Number(m[1])));
  const shown = sources.filter((s) => used.has(s.n) || !text.includes("["));

  useLayoutEffect(() => {
    const root = box.current;
    if (!root || lit === null) {
      setCables([]);
      return;
    }
    const base = root.getBoundingClientRect();
    const target = root.querySelector<HTMLElement>(`.source[data-n="${lit}"] .jack`);
    if (!target) {
      setCables([]);
      return;
    }
    const t = target.getBoundingClientRect();
    const tx = t.left + t.width / 2 - base.left;
    const ty = t.top + t.height / 2 - base.top;
    const out: { d: string; len: number; key: string }[] = [];
    root.querySelectorAll<HTMLElement>(`.cite[data-n="${lit}"]`).forEach((c, i) => {
      const r = c.getBoundingClientRect();
      const sx = r.left + r.width / 2 - base.left;
      const sy = r.bottom - base.top;
      const sag = Math.max(30, Math.abs(ty - sy) * 0.5);
      const d = `M${sx},${sy} C${sx},${sy + sag} ${tx},${ty - sag} ${tx},${ty}`;
      const len = Math.hypot(tx - sx, ty - sy) * 1.35 + 40;
      out.push({ d, len, key: `${lit}-${i}` });
    });
    setCables(out);
  }, [lit, text, sources.length]);

  const parts = text.split(/(\[\d+\])/g);
  const pinnedSource = sources.find((s) => s.n === pinned);

  return (
    <div className={`answer${abstained ? " abstained" : ""}`} ref={box}>
      <div className="answer-text">
        {parts.map((p, i) => {
          const m = p.match(/^\[(\d+)\]$/);
          if (!m || !sources.some((s) => s.n === Number(m[1]))) return <Fragment key={i}>{p}</Fragment>;
          const n = Number(m[1]);
          return (
            <button
              key={i}
              type="button"
              className={`cite${lit === n ? " on" : ""}`}
              data-n={n}
              aria-label={`Source ${n}: ${sources.find((s) => s.n === n)?.doc_title ?? ""}`}
              aria-expanded={pinned === n}
              onMouseEnter={() => setActive(n)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(n)}
              onBlur={() => setActive(null)}
              onClick={() => setPinned((p) => (p === n ? null : n))}
            >
              {n}
            </button>
          );
        })}
        {streaming && <span className="caret" aria-hidden="true" />}
      </div>

      {shown.length > 0 && !abstained && (
        <div className="sources-wrap">
          <div className="sources" aria-label="Sources">
            {shown.map((s) => (
              <button
                type="button"
                key={s.n}
                data-n={s.n}
                className={`source${lit === s.n ? " on" : ""}`}
                onMouseEnter={() => setActive(s.n)}
                onMouseLeave={() => setActive(null)}
                onClick={() => setPinned((p) => (p === s.n ? null : s.n))}
                aria-expanded={pinned === s.n}
              >
                <span className="jack" aria-hidden="true" />
                <strong>
                  {s.n}. {s.doc_title}
                </strong>
                <span className="src-meta">
                  {s.heading ?? "Overview"}
                  {s.page ? `, page ${s.page}` : ""}
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
      {pinnedSource && (
        <div className="src-detail">
          <strong>
            From "{pinnedSource.doc_title}"{pinnedSource.heading ? `, ${pinnedSource.heading}` : ""}
          </strong>
          {"\n"}
          {pinnedSource.snippet}
          {pinnedSource.snippet.length >= 320 ? "..." : ""}
        </div>
      )}
      <svg className="cables" aria-hidden="true">
        {cables.map((c) => (
          <path key={c.key} d={c.d} style={{ ["--len" as string]: c.len }} />
        ))}
      </svg>
    </div>
  );
}

export function ConfidenceMeter({ value, threshold }: { value: number; threshold: number }) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <span className="meter" title={`Retrieval confidence ${v.toFixed(2)}; answers need at least ${threshold.toFixed(2)}`}>
      <span className="meter-track" aria-hidden="true">
        <span className={`meter-fill${v < threshold ? " low" : ""}`} style={{ width: `${v * 100}%` }} />
        <span className="meter-mark" style={{ left: `${threshold * 100}%` }} />
      </span>
      <span className="num">match {v.toFixed(2)}</span>
    </span>
  );
}

export function FeedbackButtons({ value, onChange }: { value: number; onChange: (v: -1 | 0 | 1) => void }) {
  return (
    <span style={{ display: "inline-flex", gap: 2 }}>
      <button className="fb-btn" aria-pressed={value === 1} onClick={() => onChange(value === 1 ? 0 : 1)} title="Helpful">
        <Icon name="thumbUp" size={18} />
        <span className="sr-only">Mark as helpful</span>
      </button>
      <button className="fb-btn" aria-pressed={value === -1} onClick={() => onChange(value === -1 ? 0 : -1)} title="Not helpful">
        <Icon name="thumbDown" size={18} />
        <span className="sr-only">Mark as not helpful</span>
      </button>
    </span>
  );
}
