const API_PREFIX = "/api/v1";

export type Scope = {
  org_id: string;
  app_id: string;
  user_id: string;
  session_id: string;
};

export type TokenPair = {
  access_token: string;
  refresh_token: string;
};

export async function login(email: string, password: string): Promise<TokenPair> {
  const response = await fetch(`${API_PREFIX}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password })
  });
  if (!response.ok) {
    throw new Error("Login failed");
  }
  return response.json();
}

export async function refresh(refreshToken: string): Promise<TokenPair> {
  const response = await fetch(`${API_PREFIX}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken })
  });
  if (!response.ok) {
    throw new Error("Session refresh failed");
  }
  return response.json();
}

export async function me(token: string) {
  const response = await fetch(`${API_PREFIX}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw new Error("Failed to load current user");
  }
  return response.json();
}

export async function fetchGraph(token: string, scope: Scope) {
  const response = await fetch(`${API_PREFIX}/memory/graph`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ scope })
  });
  if (!response.ok) {
    throw new Error("Failed to load graph");
  }
  return response.json();
}

export async function fetchTimeline(token: string, scope: Scope) {
  const response = await fetch(`${API_PREFIX}/memory/timeline`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ scope })
  });
  if (!response.ok) {
    throw new Error("Failed to load timeline");
  }
  return response.json();
}
