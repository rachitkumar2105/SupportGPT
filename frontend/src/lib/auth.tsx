import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, post, setCsrf, setSessionLostHandler, type User } from "./api";

interface Session {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<User>;
  signup: (name: string, email: string, password: string) => Promise<User>;
  demoAgent: () => Promise<User>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
}

const Ctx = createContext<Session | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    // No CSRF cookie means no session was ever started in this browser: skip the 401 round trip.
    if (!document.cookie.includes("sg_csrf=")) {
      setUser(null);
      setLoading(false);
      return;
    }
    try {
      setUser(await api<User>("/api/auth/me"));
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setSessionLostHandler(() => setUser(null));
    void reload();
  }, [reload]);

  const start = (s: { user: User; csrf_token: string }) => {
    setCsrf(s.csrf_token);
    setUser(s.user);
    return s.user;
  };

  const value = useMemo<Session>(
    () => ({
      user,
      loading,
      reload,
      login: async (email, password) => start(await post("/api/auth/login", { email, password })),
      signup: async (name, email, password) => start(await post("/api/auth/signup", { name, email, password })),
      demoAgent: async () => start(await post("/api/auth/demo-agent")),
      logout: async () => {
        try {
          await post("/api/auth/logout");
        } finally {
          setCsrf(null);
          setUser(null);
        }
      },
    }),
    [user, loading, reload],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): Session {
  const s = useContext(Ctx);
  if (!s) throw new Error("useAuth outside AuthProvider");
  return s;
}

export const isStaff = (u: User | null) => !!u && (u.role === "agent" || u.role === "admin");
