import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { Priority, TicketStatus } from "../lib/api";
import { cap, sla } from "../lib/format";
import { Icon } from "./Icon";

/* ---------------- toasts ---------------- */
type Toast = { id: number; text: string; tone: "info" | "error" };
const ToastCtx = createContext<(text: string, tone?: "info" | "error") => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: "info" | "error" = "info") => {
    const id = Date.now() + Math.random();
    setItems((xs) => [...xs.slice(-2), { id, text, tone }]);
    setTimeout(() => setItems((xs) => xs.filter((x) => x.id !== id)), tone === "error" ? 6000 : 3500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.tone === "error" ? "error" : ""}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

/* ---------------- theme ---------------- */
type Theme = "light" | "dark";
function initialTheme(): Theme {
  try {
    const saved = localStorage.getItem("sg-theme");
    if (saved === "light" || saved === "dark") return saved;
  } catch {
    /* storage unavailable */
  }
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]:not([media])')?.remove();
  }, [theme]);
  const toggle = () =>
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      try {
        localStorage.setItem("sg-theme", next);
      } catch {
        /* ignore */
      }
      return next;
    });
  return { theme, toggle };
}

export function ThemeButton() {
  const { theme, toggle } = useTheme();
  return (
    <button className="btn ghost icon-btn" onClick={toggle} title={theme === "dark" ? "Use light theme" : "Use dark theme"}>
      <Icon name={theme === "dark" ? "sun" : "moon"} />
      <span className="sr-only">{theme === "dark" ? "Use light theme" : "Use dark theme"}</span>
    </button>
  );
}

/* ---------------- server status ---------------- */
type Health = "ok" | "warming" | "down" | "checking";
export function useServerHealth(pollWhileWarming = true): Health {
  const [state, setState] = useState<Health>("checking");
  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const check = async () => {
      try {
        const r = await fetch("/api/health", { cache: "no-store" });
        const body = r.ok ? await r.json() : null;
        const s: Health = body?.status === "ok" ? "ok" : body ? "warming" : "down";
        if (alive) setState(s);
        if (alive && s !== "ok" && pollWhileWarming) timer = setTimeout(check, 5000);
      } catch {
        if (alive) {
          setState("down");
          if (pollWhileWarming) timer = setTimeout(check, 6000);
        }
      }
    };
    void check();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [pollWhileWarming]);
  return state;
}

export function ServerStatus() {
  const s = useServerHealth();
  const label =
    s === "ok" ? "Service online" : s === "warming" ? "Server starting up" : s === "down" ? "Server waking up" : "Checking service";
  return (
    <span className={`status-pill ${s}`} title="Live status of the API on Hugging Face Spaces">
      <span className="dot" />
      {label}
    </span>
  );
}

/* ---------------- chips ---------------- */
export function PriorityChip({ p }: { p: Priority }) {
  return (
    <span className={`chip ${p === "urgent" ? "urgent" : p === "high" ? "high" : ""}`}>
      <span className="dot" />
      {cap(p)}
    </span>
  );
}
export function StatusChip({ s }: { s: TicketStatus }) {
  const label = s === "pending" ? "Waiting on customer" : cap(s);
  return <span className={`chip ${s}`}>{label}</span>;
}

export function SlaCord({ created, due, status }: { created: string; due: string; status: TicketStatus }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);
  if (status === "resolved") return null;
  const s = sla(created, due, now);
  return (
    <span className={`sla ${s.tone}`} title={`Response due ${new Date(due).toLocaleString()}`}>
      <span className="sla-cord" aria-hidden="true">
        <i style={{ width: `${Math.max(s.breached ? 100 : 4, s.fraction * 100)}%` }} />
      </span>
      <span className="num">{s.label}</span>
    </span>
  );
}

export function Initials({ name }: { name: string }) {
  const i = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
  return <span className="avatar" aria-hidden="true">{i || "?"}</span>;
}

export function Skeleton({ h = 18, w = "100%" }: { h?: number; w?: string | number }) {
  return <div className="skeleton" style={{ height: h, width: w }} />;
}

export function ErrorNote({ text, retry }: { text: string; retry?: () => void }) {
  return (
    <div className="notice error" role="alert">
      <Icon name="alert" />
      <div style={{ display: "grid", gap: 8 }}>
        <span>{text}</span>
        {retry && (
          <button className="btn sm" onClick={retry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}
