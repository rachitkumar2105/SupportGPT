import { useCallback, useEffect, useState } from "react";
import { ErrorNote, Initials, Skeleton, useToast } from "../components/ui";
import { api, patch, type Role, type User } from "../lib/api";
import { useAuth } from "../lib/auth";
import { relative } from "../lib/format";

interface AuditRow {
  id: number;
  action: string;
  target: string | null;
  actor: string | null;
  meta: Record<string, unknown> | null;
  created_at: string;
}

const ACTIONS: Record<string, string> = {
  "auth.signup": "Signed up",
  "auth.login": "Signed in",
  "auth.demo_login": "Opened the demo console",
  "auth.locked": "Locked after failed sign-ins",
  "auth.password_changed": "Changed password",
  "ticket.escalated": "Handed a chat to a person",
  "ticket.created": "Opened a ticket",
  "ticket.reply": "Replied on a ticket",
  "ticket.updated": "Updated a ticket",
  "kb.upload": "Added a document",
  "kb.delete": "Removed a document",
  "admin.user_updated": "Changed a user",
  "eval.run": "Ran an evaluation",
};

export default function People() {
  const { user: me } = useAuth();
  const toast = useToast();
  const [tab, setTab] = useState<"people" | "audit">("people");
  const [users, setUsers] = useState<User[] | null>(null);
  const [audit, setAudit] = useState<AuditRow[] | null>(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    setErr(null);
    if (tab === "people")
      api<User[]>(`/api/admin/users${q ? `?q=${encodeURIComponent(q)}` : ""}`)
        .then(setUsers)
        .catch((e) => setErr(e.message));
    else
      api<AuditRow[]>("/api/admin/audit")
        .then(setAudit)
        .catch((e) => setErr(e.message));
  }, [tab, q]);
  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [load, q]);

  const change = async (u: User, body: { role?: Role; is_active?: boolean }) => {
    try {
      const upd = await patch<User>(`/api/admin/users/${u.id}`, body);
      setUsers((xs) => xs?.map((x) => (x.id === u.id ? upd : x)) ?? null);
      toast(`Updated ${u.name}. They'll need to refresh to see the change.`);
    } catch (e) {
      toast((e as Error).message, "error");
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1 style={{ fontSize: "clamp(1.6rem, 1.2rem + 1.4vw, 2.2rem)" }}>People</h1>
          <p>Promote customers to agents, deactivate accounts, and review the audit trail. Role changes sign the person out of every device.</p>
        </div>
        <div className="seg" role="group" aria-label="View">
          <button aria-pressed={tab === "people"} onClick={() => setTab("people")}>
            Accounts
          </button>
          <button aria-pressed={tab === "audit"} onClick={() => setTab("audit")}>
            Audit log
          </button>
        </div>
      </div>
      {err && <ErrorNote text={err} retry={load} />}

      {tab === "people" && (
        <>
          <div className="filters">
            <label htmlFor="pq" className="sr-only">
              Search people
            </label>
            <input id="pq" type="search" placeholder="Search by name or email" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {!users && !err && <Skeleton h={200} />}
          {users && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>Person</th>
                    <th>Role</th>
                    <th>Status</th>
                    <th>Joined</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => {
                    const locked = u.id === me?.id || u.is_demo;
                    return (
                      <tr key={u.id}>
                        <td>
                          <div className="who" style={{ padding: 0 }}>
                            <Initials name={u.name} />
                            <div className="who-text">
                              <strong>{u.name}</strong>
                              <span>{u.email}</span>
                            </div>
                          </div>
                        </td>
                        <td>
                          <label className="sr-only" htmlFor={`role-${u.id}`}>
                            Role for {u.name}
                          </label>
                          <select
                            id={`role-${u.id}`}
                            value={u.role}
                            disabled={locked}
                            onChange={(e) => change(u, { role: e.target.value as Role })}
                            style={{ minWidth: 130 }}
                          >
                            <option value="customer">Customer</option>
                            <option value="agent">Agent</option>
                            <option value="admin">Admin</option>
                          </select>
                        </td>
                        <td>
                          <button className="btn sm" disabled={locked} onClick={() => change(u, { is_active: !u.is_active })}>
                            {u.is_active ? "Deactivate" : "Reactivate"}
                          </button>
                          {!u.is_active && <div className="faint">Deactivated</div>}
                          {u.is_demo && <div className="faint">Demo account</div>}
                        </td>
                        <td>{relative(u.created_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {tab === "audit" && (
        <>
          {!audit && !err && <Skeleton h={200} />}
          {audit && (
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Who</th>
                    <th>What</th>
                    <th>Target</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.map((r) => (
                    <tr key={r.id}>
                      <td style={{ whiteSpace: "nowrap" }}>{relative(r.created_at)}</td>
                      <td>{r.actor ?? "System"}</td>
                      <td>{ACTIONS[r.action] ?? r.action}</td>
                      <td className="faint">{r.target}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
