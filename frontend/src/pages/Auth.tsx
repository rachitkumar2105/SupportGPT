import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { Icon, Logo } from "../components/Icon";
import { useToast } from "../components/ui";
import type { User } from "../lib/api";
import { useAuth } from "../lib/auth";

const homeFor = (u: User) => (u.role === "customer" ? "/app/chat" : "/app/queue");

export default function Auth({ mode }: { mode: "login" | "signup" }) {
  const { login, signup, demoAgent } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const toast = useToast();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const from = (loc.state as { from?: string } | null)?.from;

  const emailBad = touched.email && !/^\S+@\S+\.\S+$/.test(email);
  const pwBad = mode === "signup" && touched.password && (password.length < 10 || !/[a-z]/i.test(password) || !/\d/.test(password));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setTouched({ email: true, password: true, name: true });
    setErr(null);
    setBusy(true);
    try {
      const u = mode === "login" ? await login(email, password) : await signup(name, email, password);
      nav(from && from.startsWith("/app") ? from : homeFor(u), { replace: true });
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const agent = async () => {
    setBusy(true);
    try {
      const u = await demoAgent();
      nav(homeFor(u), { replace: true });
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <div className="auth-side">
        <Link to="/" className="brand">
          <Logo /> SupportGPT
        </Link>
        <blockquote>Every answer shows its source. Every hand-off arrives ready to work.</blockquote>
        <p>
          Sign up as a customer to ask the Fieldnote demo help center anything. To see the other side, open the agent console
          without an account.
        </p>
      </div>
      <div className="auth-form-wrap">
        <form className="auth-form" onSubmit={submit} noValidate>
          <div>
            <h1 style={{ fontSize: "clamp(1.7rem, 1.3rem + 1.5vw, 2.3rem)" }}>{mode === "login" ? "Sign in" : "Create your account"}</h1>
            <p className="muted" style={{ marginTop: 6 }}>
              {mode === "login" ? "New here? " : "Already have an account? "}
              <Link to={mode === "login" ? "/signup" : "/login"} state={loc.state}>
                {mode === "login" ? "Create an account" : "Sign in"}
              </Link>
            </p>
          </div>

          {mode === "signup" && (
            <div className="field">
              <label htmlFor="name">Name</label>
              <input id="name" autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required />
            </div>
          )}
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              inputMode="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => setTouched((t) => ({ ...t, email: true }))}
              aria-invalid={emailBad || undefined}
              aria-describedby={emailBad ? "email-err" : undefined}
              required
            />
            {emailBad && (
              <span id="email-err" className="err">
                Enter an email address like name@example.com.
              </span>
            )}
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <div style={{ position: "relative" }}>
              <input
                id="password"
                type={show ? "text" : "password"}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onBlur={() => setTouched((t) => ({ ...t, password: true }))}
                aria-invalid={pwBad || undefined}
                aria-describedby="pw-hint"
                maxLength={128}
                required
                style={{ paddingRight: 72 }}
              />
              <button
                type="button"
                className="btn ghost sm"
                onClick={() => setShow((s) => !s)}
                style={{ position: "absolute", right: 4, top: 4 }}
                aria-pressed={show}
              >
                {show ? "Hide" : "Show"}
              </button>
            </div>
            {mode === "signup" && (
              <span id="pw-hint" className={pwBad ? "err" : "hint"}>
                At least 10 characters, with letters and numbers.
              </span>
            )}
          </div>

          {err && (
            <div className="notice error" role="alert">
              <Icon name="alert" /> <span>{err}</span>
            </div>
          )}

          <button className="btn primary" disabled={busy} style={{ width: "100%" }}>
            {busy && <span className="spinner" />}
            {mode === "login" ? "Sign in" : "Create account"}
          </button>

          <div className="divider">or</div>
          <button type="button" className="btn" onClick={agent} disabled={busy} style={{ width: "100%" }}>
            <Icon name="queue" /> Open the agent console as a demo agent
          </button>
          <p className="faint">
            By continuing you agree to the <Link to="/terms">terms</Link> and <Link to="/privacy">privacy notice</Link>. The first
            request can take up to a minute while the free server wakes up, and demo accounts reset when it restarts.
          </p>
        </form>
      </div>
    </div>
  );
}
