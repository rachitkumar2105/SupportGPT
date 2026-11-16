const rtf = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function relative(iso: string, now = Date.now()): string {
  const diff = (new Date(iso).getTime() - now) / 1000;
  const abs = Math.abs(diff);
  if (abs < 45) return "just now";
  if (abs < 3600) return rtf.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), "hour");
  return rtf.format(Math.round(diff / 86400), "day");
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** SLA status: remaining fraction of the window and a label. */
export function sla(createdIso: string, dueIso: string, now = Date.now()) {
  const created = new Date(createdIso).getTime();
  const due = new Date(dueIso).getTime();
  const total = Math.max(1, due - created);
  const left = due - now;
  const fraction = Math.max(0, Math.min(1, left / total));
  const breached = left < 0;
  const mins = Math.round(Math.abs(left) / 60000);
  const span = mins < 60 ? `${mins}m` : mins < 2880 ? `${Math.round(mins / 60)}h` : `${Math.round(mins / 1440)}d`;
  return {
    fraction,
    breached,
    tone: breached ? "breach" : fraction < 0.25 ? "warn" : "ok",
    label: breached ? `${span} over` : `${span} left`,
  } as const;
}

export const pct = (v: number | null | undefined, digits = 0) =>
  v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(digits)}%`;

export const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
