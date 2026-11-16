import { useState } from "react";
import { useNavigate } from "react-router";
import { useToast } from "../components/ui";
import { post } from "../lib/api";
import { useAuth } from "../lib/auth";
import { dateTime } from "../lib/format";

export default function Settings() {
  const { user, reload } = useAuth();
  const toast = useToast();
  const nav = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (!user) return null;

  const tooWeak = next.length > 0 && (next.length < 10 || !/[a-z]/i.test(next) || !/\d/.test(next));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await post("/api/auth/change-password", { current_password: current, new_password: next });
      toast("Password changed. Sign in again with your new password.");
      await reload();
      nav("/login", { replace: true });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page" style={{ maxWidth: 720 }}>
      <div className="page-head">
        <div>
          <h1 style={{ fontSize: "clamp(1.6rem, 1.2rem + 1.4vw, 2.2rem)" }}>Settings</h1>
        </div>
      </div>
      <div className="panel" style={{ padding: 20, display: "grid", gap: 10 }}>
        <h2 style={{ fontSize: "1.15rem" }}>Account</h2>
        <dl className="kv">
          <dt>Name</dt>
          <dd>{user.name}</dd>
          <dt>Email</dt>
          <dd>{user.email}</dd>
          <dt>Role</dt>
          <dd>{user.role === "customer" ? "Customer" : user.role === "agent" ? "Support agent" : "Administrator"}</dd>
          <dt>Member since</dt>
          <dd>{dateTime(user.created_at)}</dd>
        </dl>
      </div>

      {!user.is_demo && (
        <form className="panel" style={{ padding: 20, display: "grid", gap: 14, marginTop: 16 }} onSubmit={submit} noValidate>
          <h2 style={{ fontSize: "1.15rem" }}>Change password</h2>
          <p className="faint">Changing your password signs you out everywhere, including this device.</p>
          <div className="field">
            <label htmlFor="cur">Current password</label>
            <input id="cur" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="new">New password</label>
            <input
              id="new"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              aria-invalid={tooWeak}
              aria-describedby="new-hint"
              required
            />
            <span id="new-hint" className={tooWeak ? "err" : "hint"}>
              At least 10 characters with letters and numbers.
            </span>
          </div>
          {err && (
            <p className="err" role="alert" style={{ color: "var(--cable)" }}>
              {err}
            </p>
          )}
          <div>
            <button className="btn primary" disabled={busy || !current || !next || tooWeak}>
              {busy && <span className="spinner" />} Change password
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
