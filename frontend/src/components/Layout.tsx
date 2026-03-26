import { type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { BookOpen, BrainCircuit, Inbox, LayoutDashboard, LogOut, MessageSquareText, ShieldAlert } from "lucide-react";
import type { AppRecord, CurrentUser, Scope } from "../lib/api";

interface LayoutProps {
  children: ReactNode;
  scope: Scope | null;
  currentUser: CurrentUser | null;
  availableApps: AppRecord[];
  onAppChange: (appId: string) => void;
}

const PAGE_COPY: Record<string, { title: string; subtitle: string }> = {
  "/": {
    title: "Agent Memory Workbench",
    subtitle: "Inspectable sessions, ingestion, retrieval traces, graph memory, and MCP setup in one place.",
  },
  "/conversations": {
    title: "Conversation Runtime",
    subtitle: "Operate server-owned conversations, inspect full threads, and open grounded answer traces.",
  },
  "/review": {
    title: "Memory Review Inbox",
    subtitle: "Approve, reject, and inspect what reflection wants the system to remember across sessions.",
  },
  "/admin": {
    title: "Tenant Control Room",
    subtitle: "Filter tenant-wide conversations, inspect traceability, and manage operational memory visibility.",
  },
};

export function Layout({ children, scope, currentUser, availableApps, onAppChange }: LayoutProps) {
  const location = useLocation();
  const pageCopy = PAGE_COPY[location.pathname] ?? PAGE_COPY["/"];

  const handleLogout = () => {
    localStorage.removeItem("memoryos_token");
    localStorage.removeItem("memoryos_refresh_token");
    window.location.reload();
  };

  const initials = (scope?.org_id || "M").slice(0, 1).toUpperCase();
  const isAdmin = currentUser?.role === "owner" || currentUser?.role === "admin";

  return (
    <div className="app-layout animate-fade-in shell-light">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="brand-mark">
            <BrainCircuit size={24} color="var(--brand-primary)" />
          </div>
          <div>
            <h2>MemoryOS</h2>
            <p className="text-sm text-secondary">Agent Memory Control</p>
          </div>
        </div>

        <nav className="sidebar-nav">
          <NavLink to="/" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            <LayoutDashboard size={20} />
            <span>Workbench</span>
          </NavLink>
          <NavLink to="/conversations" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
            <MessageSquareText size={20} />
            <span>Conversations</span>
          </NavLink>
          {isAdmin ? (
            <NavLink to="/review" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <Inbox size={20} />
              <span>Review Inbox</span>
            </NavLink>
          ) : null}
          {isAdmin ? (
            <NavLink to="/admin" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <ShieldAlert size={20} />
              <span>Admin</span>
            </NavLink>
          ) : null}
          <a href="/docs" target="_blank" rel="noreferrer" className="nav-item">
            <BookOpen size={20} />
            <span>API Docs</span>
          </a>
        </nav>

        <div className="sidebar-footer">
          <div className="mb-4">
            <p className="section-label">Active Scope</p>
            <div className="scope-card">
              <div className="scope-row">
                <span className="text-secondary">Org</span>
                <span className="font-medium">{scope ? scope.org_id : "Default"}</span>
              </div>
              <div className="scope-row">
                <span className="text-secondary">App</span>
                {availableApps.length > 0 ? (
                  <select
                    className="input-base"
                    value={scope?.app_id ?? availableApps[0]?.app_id ?? ""}
                    onChange={(event) => onAppChange(event.target.value)}
                    style={{ maxWidth: "170px", padding: "0.45rem 0.65rem", fontSize: "0.84rem" }}
                  >
                    {availableApps.map((app) => (
                      <option key={app.app_id} value={app.app_id}>
                        {app.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="font-medium">{scope ? scope.app_id : "Default"}</span>
                )}
              </div>
              <div className="scope-row">
                <span className="text-secondary">User</span>
                <span className="font-medium">{scope ? scope.user_id.slice(0, 8) : "n/a"}</span>
              </div>
              <div className="scope-row">
                <span className="text-secondary">Role</span>
                <span className="font-medium">{currentUser?.role ?? "member"}</span>
              </div>
            </div>
          </div>

          <button onClick={handleLogout} className="nav-item nav-logout w-full" style={{ background: "transparent", border: "none", cursor: "pointer" }}>
            <LogOut size={20} />
            <span>Sign Out</span>
          </button>
        </div>
      </aside>

      <main className="main-content">
        <header className="header">
          <div>
            <p className="section-label" style={{ marginBottom: "0.35rem" }}>Memory Operations</p>
            <h1 className="page-title">{pageCopy.title}</h1>
            <p className="text-sm text-secondary">{pageCopy.subtitle}</p>
          </div>
          <div className="header-user">
            <div className="avatar-chip">{initials}</div>
            <div>
              <div className="font-medium">{scope?.app_id ?? "memoryos-dashboard"}</div>
              <div className="text-xs text-secondary">{currentUser?.email ?? "MCP transports enabled"}</div>
            </div>
          </div>
        </header>
        <div className="workspace-body">
          {children}
        </div>
      </main>
    </div>
  );
}
