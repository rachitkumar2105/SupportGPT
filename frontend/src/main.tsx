import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import "./styles.css";

import { lazy, StrictMode, Suspense, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router";
import { Shell } from "./components/Shell";
import { Skeleton, ToastProvider, useTheme } from "./components/ui";
import { AuthProvider, isStaff, useAuth } from "./lib/auth";
import type { Role } from "./lib/api";
import Landing from "./pages/Landing";
import Auth from "./pages/Auth";
import { NotFound, Privacy, Terms } from "./pages/Legal";

const Chat = lazy(() => import("./pages/Chat"));
const MyTickets = lazy(() => import("./pages/Tickets").then((m) => ({ default: m.MyTickets })));
const Queue = lazy(() => import("./pages/Tickets").then((m) => ({ default: m.Queue })));
const TicketView = lazy(() => import("./pages/TicketView"));
const Knowledge = lazy(() => import("./pages/Knowledge"));
const Insights = lazy(() => import("./pages/Insights"));
const Quality = lazy(() => import("./pages/Quality"));
const People = lazy(() => import("./pages/People"));
const Settings = lazy(() => import("./pages/Settings"));

function Loading() {
  return (
    <div className="page" style={{ display: "grid", gap: 12 }}>
      <Skeleton h={30} w="40%" />
      <Skeleton h={140} />
    </div>
  );
}

function Guard({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user, loading } = useAuth();
  const loc = useLocation();
  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname }} />;
  if (roles && !roles.includes(user.role)) return <Navigate to={isStaff(user) ? "/app/queue" : "/app/chat"} replace />;
  return <>{children}</>;
}

function PublicOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to={isStaff(user) ? "/app/queue" : "/app/chat"} replace />;
  return <>{children}</>;
}

function AppHome() {
  const { user } = useAuth();
  return <Navigate to={isStaff(user) ? "/app/queue" : "/app/chat"} replace />;
}

function App() {
  useTheme();
  const staff: Role[] = ["agent", "admin"];
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<PublicOnly><Auth mode="login" /></PublicOnly>} />
      <Route path="/signup" element={<PublicOnly><Auth mode="signup" /></PublicOnly>} />
      <Route path="/privacy" element={<Privacy />} />
      <Route path="/terms" element={<Terms />} />
      <Route path="/app" element={<Guard><Shell /></Guard>}>
        <Route index element={<AppHome />} />
        <Route path="chat" element={<Suspense fallback={<Loading />}><Guard roles={["customer"]}><Chat /></Guard></Suspense>} />
        <Route path="chat/:id" element={<Suspense fallback={<Loading />}><Guard roles={["customer"]}><Chat /></Guard></Suspense>} />
        <Route path="tickets" element={<Suspense fallback={<Loading />}><Guard roles={["customer"]}><MyTickets /></Guard></Suspense>} />
        <Route path="tickets/:id" element={<Suspense fallback={<Loading />}><TicketView /></Suspense>} />
        <Route path="queue" element={<Suspense fallback={<Loading />}><Guard roles={staff}><Queue /></Guard></Suspense>} />
        <Route path="knowledge" element={<Suspense fallback={<Loading />}><Guard roles={staff}><Knowledge /></Guard></Suspense>} />
        <Route path="insights" element={<Suspense fallback={<Loading />}><Guard roles={staff}><Insights /></Guard></Suspense>} />
        <Route path="quality" element={<Suspense fallback={<Loading />}><Guard roles={staff}><Quality /></Guard></Suspense>} />
        <Route path="people" element={<Suspense fallback={<Loading />}><Guard roles={["admin"]}><People /></Guard></Suspense>} />
        <Route path="settings" element={<Suspense fallback={<Loading />}><Settings /></Suspense>} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
);
