import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router";
import { api, type Ticket } from "../lib/api";
import { isStaff, useAuth } from "../lib/auth";
import { Icon, Logo, type IconName } from "./Icon";
import { Initials, ServerStatus, ThemeButton } from "./ui";

interface NavItem {
  to: string;
  label: string;
  short: string;
  icon: IconName;
  roles: string[];
}

const NAV: NavItem[] = [
  { to: "/app/chat", label: "Ask for help", short: "Ask", icon: "chat", roles: ["customer"] },
  { to: "/app/tickets", label: "My tickets", short: "Tickets", icon: "ticket", roles: ["customer"] },
  { to: "/app/queue", label: "Ticket queue", short: "Queue", icon: "queue", roles: ["agent", "admin"] },
  { to: "/app/knowledge", label: "Knowledge base", short: "Articles", icon: "book", roles: ["agent", "admin"] },
  { to: "/app/insights", label: "Insights", short: "Insights", icon: "chart", roles: ["agent", "admin"] },
  { to: "/app/quality", label: "Answer quality", short: "Quality", icon: "gauge", roles: ["agent", "admin"] },
  { to: "/app/people", label: "People", short: "People", icon: "people", roles: ["admin"] },
  { to: "/app/settings", label: "Settings", short: "Settings", icon: "sliders", roles: ["customer", "agent", "admin"] },
];

export function Shell() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const loc = useLocation();
  const [openCount, setOpenCount] = useState<number | null>(null);
  const items = NAV.filter((n) => user && n.roles.includes(user.role));
  const chat = loc.pathname.startsWith("/app/chat");

  useEffect(() => {
    if (!isStaff(user)) return;
    api<Ticket[]>("/api/tickets?status=open")
      .then((t) => setOpenCount(t.length))
      .catch(() => setOpenCount(null));
  }, [user, loc.pathname]);

  if (!user) return null;
  const signOut = async () => {
    await logout();
    nav("/", { replace: true });
  };

  return (
    <div className="shell">
      <a className="skip" href="#content">
        Skip to content
      </a>
      <aside className="rail" aria-label="Main navigation">
        <NavLink to="/" className="brand">
          <Logo /> SupportGPT
        </NavLink>
        {items.map((n) => (
          <NavLink key={n.to} to={n.to} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
            <Icon name={n.icon} />
            {n.label}
            {n.to === "/app/queue" && openCount ? (
              <span className="lamp-count num" aria-label={`${openCount} open tickets`}>
                {openCount}
              </span>
            ) : null}
          </NavLink>
        ))}
        <div className="rail-foot">
          <div style={{ padding: "0 8px" }}>
            <ServerStatus />
          </div>
          <div className="who">
            <Initials name={user.name} />
            <div className="who-text">
              <strong>{user.name}</strong>
              <span>{user.is_demo ? "Demo agent" : user.email}</span>
            </div>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <ThemeButton />
            <button className="btn ghost" onClick={signOut} style={{ flex: 1, justifyContent: "flex-start" }}>
              <Icon name="logout" /> Sign out
            </button>
          </div>
        </div>
      </aside>

      <div className={`main${chat ? " chat-main" : ""}`}>
        <header className="topbar">
          <NavLink to="/" className="brand">
            <Logo size={26} /> SupportGPT
          </NavLink>
          <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <ThemeButton />
            <button className="btn ghost icon-btn" onClick={signOut} title="Sign out">
              <Icon name="logout" />
              <span className="sr-only">Sign out</span>
            </button>
          </div>
        </header>
        {user.is_demo && (
          <div className="demo-banner">
            <Icon name="handoff" size={18} />
            <span>
              You're in the demo agent console. Tickets marked "Sample" are seeded; anything visitors escalate shows up here too.
            </span>
          </div>
        )}
        <main id="content" tabIndex={-1} style={{ outline: "none", minWidth: 0 }}>
          <Outlet />
        </main>
        <nav className="tabbar" aria-label="Main navigation">
          {[...items.filter((n) => n.to !== "/app/settings").slice(0, 4), ...items.filter((n) => n.to === "/app/settings")].map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon name={n.icon} size={22} />
              {n.short}
            </NavLink>
          ))}
        </nav>
      </div>
    </div>
  );
}
