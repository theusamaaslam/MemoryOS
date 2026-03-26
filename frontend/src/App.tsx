import { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { Admin } from "./pages/Admin";
import { Conversations } from "./pages/Conversations";
import { Review } from "./pages/Review";
import { LoginCard } from "./components/LoginCard";
import { listApps, me, refresh, login, type AppRecord, type CurrentUser, type Scope } from "./lib/api";

export function App() {
  const [token, setToken] = useState<string | null>(() => localStorage.getItem("memoryos_token"));
  const [refreshToken, setRefreshToken] = useState<string | null>(() => localStorage.getItem("memoryos_refresh_token"));
  const [error, setError] = useState<string>("");
  const [activeAppId, setActiveAppId] = useState<string>(() => localStorage.getItem("memoryos_app_id") || "memoryos-dashboard");
  const [activeSessionId, setActiveSessionId] = useState<string>(() => localStorage.getItem("memoryos_session_id") || "default-session");
  const [scope, setScope] = useState<Scope | null>(null);
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);
  const [availableApps, setAvailableApps] = useState<AppRecord[]>([]);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    async function loadIdentity() {
      try {
        let activeToken = token!;
        let resolvedUser;
        try {
          resolvedUser = await me(activeToken);
        } catch {
          if (!refreshToken) throw new Error("Session expired");
          const refreshed = await refresh(refreshToken);
          activeToken = refreshed.access_token;
          localStorage.setItem("memoryos_token", activeToken);
          localStorage.setItem("memoryos_refresh_token", refreshed.refresh_token);
          setToken(activeToken);
          setRefreshToken(refreshed.refresh_token);
          resolvedUser = await me(activeToken);
        }
        let apps: AppRecord[] = [];
        try {
          apps = await listApps(activeToken);
        } catch {
          apps = [];
        }
        const storedAppId = localStorage.getItem("memoryos_app_id") || activeAppId;
        const resolvedAppId =
          apps.find((app) => app.app_id === storedAppId)?.app_id
          || apps[0]?.app_id
          || storedAppId
          || "memoryos-dashboard";
        if (!cancelled) {
          setCurrentUser(resolvedUser);
          setAvailableApps(apps);
          setActiveAppId(resolvedAppId);
          localStorage.setItem("memoryos_app_id", resolvedAppId);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Authentication failed");
        }
        setToken(null);
        setRefreshToken(null);
        setCurrentUser(null);
        setAvailableApps([]);
        setScope(null);
        localStorage.removeItem("memoryos_token");
        localStorage.removeItem("memoryos_refresh_token");
      }
    }
    void loadIdentity();
    return () => { cancelled = true; };
  }, [token, refreshToken]);

  useEffect(() => {
    if (!currentUser) {
      setScope(null);
      return;
    }
    setScope({
      org_id: currentUser.org_id,
      app_id: activeAppId,
      user_id: currentUser.user_id,
      session_id: activeSessionId,
    });
  }, [activeAppId, activeSessionId, currentUser]);

  if (!token) {
    return (
      <LoginCard
        error={error}
        onLogin={async (email, password) => {
          try {
            const tokens = await login(email, password);
            localStorage.setItem("memoryos_token", tokens.access_token);
            localStorage.setItem("memoryos_refresh_token", tokens.refresh_token);
            setToken(tokens.access_token);
            setRefreshToken(tokens.refresh_token);
            setError("");
          } catch (err) {
            setError(err instanceof Error ? err.message : "Login failed");
          }
        }}
      />
    );
  }

  return (
    <BrowserRouter>
      <Layout
        scope={scope}
        currentUser={currentUser}
        availableApps={availableApps}
        onAppChange={(appId) => {
          const cleaned = appId.trim();
          if (!cleaned) return;
          localStorage.setItem("memoryos_app_id", cleaned);
          setActiveAppId(cleaned);
          setScope((currentScope) => (
            currentScope
              ? {
                  ...currentScope,
                  app_id: cleaned,
                }
              : currentScope
          ));
        }}
      >
        <Routes>
          <Route
            path="/"
            element={
              <Dashboard
                scope={scope}
                token={token}
                onSessionChange={(sessionId) => {
                  const cleaned = sessionId.trim();
                  if (!cleaned) return;
                  localStorage.setItem("memoryos_session_id", cleaned);
                  setActiveSessionId(cleaned);
                }}
              />
            }
          />
          <Route
            path="/conversations"
            element={
              <Conversations
                scope={scope}
                token={token}
                currentUser={currentUser}
                onSessionChange={(sessionId) => {
                  const cleaned = sessionId.trim();
                  if (!cleaned) return;
                  localStorage.setItem("memoryos_session_id", cleaned);
                  setActiveSessionId(cleaned);
                }}
              />
            }
          />
          <Route path="/review" element={<Review token={token} scope={scope} currentUser={currentUser} />} />
          <Route path="/admin" element={<Admin token={token} scope={scope} currentUser={currentUser} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}
