// Cliente da API do ULTRON: base configurável, tokens com renovação automática.

export type User = { id: string; email: string; name: string; role: string };
type Session = { access: string; refresh: string; user: User };

const SESSION_KEY = "ultron.session";
const BASE_KEY = "ultron.apiBase";

function safeGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* armazenamento indisponível (aba privada) */
  }
}

export function apiBase(): string {
  const stored = typeof window !== "undefined" ? safeGet(BASE_KEY) : null;
  return (stored || process.env.NEXT_PUBLIC_API_URL || "").replace(/\/+$/, "");
}

export function setApiBase(url: string) {
  safeSet(BASE_KEY, url.trim() ? url.trim().replace(/\/+$/, "") : null);
}

export function getSession(): Session | null {
  const raw = safeGet(SESSION_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Session;
  } catch {
    return null;
  }
}

export function saveSession(data: { access_token: string; refresh_token: string; user: User }) {
  safeSet(SESSION_KEY, JSON.stringify({ access: data.access_token, refresh: data.refresh_token, user: data.user }));
}

export function clearSession() {
  safeSet(SESSION_KEY, null);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const s = getSession();
  if (!s) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const r = await fetch(`${apiBase()}/api/auth/refresh`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: s.refresh }),
        });
        if (!r.ok) return false;
        saveSession(await r.json());
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

function detailMessage(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x && typeof x === "object" && "msg" in x ? String(x.msg) : String(x))).join("; ");
    return JSON.stringify(d);
  }
  return `Erro ${status}`;
}

export async function api<T = unknown>(path: string, init: RequestInit & { json?: unknown } = {}, retry = true): Promise<T> {
  const s = getSession();
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (init.json !== undefined) headers["Content-Type"] = "application/json";
  if (s) headers["Authorization"] = `Bearer ${s.access}`;
  let r: Response;
  try {
    r = await fetch(`${apiBase()}${path}`, {
      ...init,
      headers,
      body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
    });
  } catch {
    throw new ApiError(0, "Sem conexão com o servidor do ULTRON.");
  }
  if (r.status === 401 && retry && s && !path.startsWith("/api/auth/")) {
    if (await refreshTokens()) return api<T>(path, init, false);
    clearSession();
    if (typeof window !== "undefined" && !location.pathname.startsWith("/login")) location.href = "/login/";
    throw new ApiError(401, "Sessão expirada");
  }
  const text = await r.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  if (!r.ok) throw new ApiError(r.status, detailMessage(body, r.status));
  return body as T;
}

export const get = <T = unknown>(p: string) => api<T>(p);
export const post = <T = unknown>(p: string, json: unknown = {}) => api<T>(p, { method: "POST", json });
export const put = <T = unknown>(p: string, json: unknown = {}) => api<T>(p, { method: "PUT", json });
export const patch = <T = unknown>(p: string, json: unknown = {}) => api<T>(p, { method: "PATCH", json });
export const del = <T = unknown>(p: string) => api<T>(p, { method: "DELETE" });

export async function logout() {
  const s = getSession();
  if (s) {
    try {
      await fetch(`${apiBase()}/api/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: s.refresh }),
      });
    } catch {
      /* ignora */
    }
  }
  clearSession();
  location.href = "/login/";
}
