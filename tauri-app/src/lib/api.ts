import { fetch as tauriFetch } from "@tauri-apps/plugin-http";

// ── Server connection config ─────────────────────────────────────
const STORAGE_KEY = "transcriber_server_url";
const DEFAULT_URL = "http://127.0.0.1:8000";

function getStoredServerUrl(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_URL;
  } catch {
    return DEFAULT_URL;
  }
}

let _baseUrl = getStoredServerUrl();
let _authToken = "";

export function getBaseUrl(): string {
  return _baseUrl;
}

export function getWsUrl(): string {
  return _baseUrl.replace(/^http/, "ws");
}

export function setServerUrl(url: string): void {
  _baseUrl = url.replace(/\/+$/, ""); // trim trailing slash
  try {
    localStorage.setItem(STORAGE_KEY, _baseUrl);
  } catch { /* ignore */ }
}

export function setAuthToken(token: string): void {
  _authToken = token;
}

export function getAuthToken(): string {
  return _authToken;
}

// Keep backward-compatible exports (computed from current config)
export const BASE_URL = DEFAULT_URL; // NOTE: use getBaseUrl() for dynamic URL
export const WS_URL = DEFAULT_URL.replace(/^http/, "ws");

// ── Client ID for multi-session support ──────────────────────────
let _clientId = `client_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

export function getClientId(): string {
  return _clientId;
}

export function setClientId(id: string): void {
  _clientId = id;
}

// ── API fetch helpers ────────────────────────────────────────────

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${getBaseUrl()}${path}`;
  const headers: Record<string, string> = {};
  if (options?.body) headers["Content-Type"] = "application/json";
  if (_authToken) headers["Authorization"] = `Bearer ${_authToken}`;

  let res: Response;
  try {
    res = await tauriFetch(url, {
      method: options?.method ?? "GET",
      headers,
      body: options?.body as string | undefined,
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error(`[apiFetch] Network error: ${options?.method ?? "GET"} ${url} → ${msg}`);
    throw new Error(`${msg} (${options?.method ?? "GET"} ${path})`);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function apiFetchText(path: string): Promise<string> {
  const headers: Record<string, string> = {};
  if (_authToken) headers["Authorization"] = `Bearer ${_authToken}`;
  const res = await tauriFetch(`${getBaseUrl()}${path}`, { headers });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.text();
}

export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  if (_authToken) headers["Authorization"] = `Bearer ${_authToken}`;
  const res = await tauriFetch(`${getBaseUrl()}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
