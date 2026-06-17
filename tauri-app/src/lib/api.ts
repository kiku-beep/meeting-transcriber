import { fetch as tauriFetch } from "@tauri-apps/plugin-http";

// ── Server connection config ─────────────────────────────────────
const SERVER_URL_STORAGE_KEY = "transcriber_server_url";
const AUTH_TOKEN_STORAGE_KEY = "transcriber_auth_token";
const CLIENT_ID_STORAGE_KEY = "transcriber_client_id";
export const CONNECTION_CONFIG_CHANGED = "transcriber:connection-config-changed";
const DEFAULT_URL = "http://127.0.0.1:8000";

function getDefaultServerUrl(): string {
  return sanitizeServerUrl(import.meta.env.VITE_BACKEND_URL || DEFAULT_URL);
}

function sanitizeServerUrl(url: string): string {
  const trimmed = url.trim().replace(/\/+$/, "");
  if (!trimmed) return DEFAULT_URL;
  if (/^https?:\/\//.test(trimmed)) return trimmed;
  return `http://${trimmed}`;
}

function getStoredServerUrl(): string {
  try {
    return sanitizeServerUrl(localStorage.getItem(SERVER_URL_STORAGE_KEY) || getDefaultServerUrl());
  } catch {
    return getDefaultServerUrl();
  }
}

function getStoredAuthToken(): string {
  try {
    return localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

function generateClientId(): string {
  const random = Math.random().toString(36).slice(2, 10);
  return `mac_${Date.now()}_${random}`;
}

function getStoredClientId(): string {
  try {
    const existing = localStorage.getItem(CLIENT_ID_STORAGE_KEY);
    if (existing) return existing;
    const generated = generateClientId();
    localStorage.setItem(CLIENT_ID_STORAGE_KEY, generated);
    return generated;
  } catch {
    return generateClientId();
  }
}

function notifyConnectionConfigChanged(): void {
  try {
    window.dispatchEvent(new CustomEvent(CONNECTION_CONFIG_CHANGED));
  } catch { /* ignore */ }
}

let _baseUrl = getStoredServerUrl();
let _authToken = getStoredAuthToken();
let _clientId = getStoredClientId();

export function getBaseUrl(): string {
  return _baseUrl;
}

export function getWsUrl(): string {
  return _baseUrl.replace(/^http/, "ws");
}

export function setServerUrl(url: string): void {
  _baseUrl = sanitizeServerUrl(url);
  try {
    localStorage.setItem(SERVER_URL_STORAGE_KEY, _baseUrl);
  } catch { /* ignore */ }
  notifyConnectionConfigChanged();
}

export function setAuthToken(token: string): void {
  _authToken = token.trim();
  try {
    if (_authToken) localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, _authToken);
    else localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
  } catch { /* ignore */ }
  notifyConnectionConfigChanged();
}

export function getAuthToken(): string {
  return _authToken;
}

// Keep backward-compatible exports (computed from current config)
export const BASE_URL = DEFAULT_URL; // NOTE: use getBaseUrl() for dynamic URL
export const WS_URL = DEFAULT_URL.replace(/^http/, "ws");

// ── Client ID for multi-session support ──────────────────────────
export function getClientId(): string {
  return _clientId;
}

export function setClientId(id: string): void {
  const trimmed = id.trim();
  if (!trimmed) return;
  _clientId = trimmed;
  try {
    localStorage.setItem(CLIENT_ID_STORAGE_KEY, _clientId);
  } catch { /* ignore */ }
  notifyConnectionConfigChanged();
}

export function resetClientId(): string {
  const generated = generateClientId();
  setClientId(generated);
  return generated;
}

export function addClientIdQuery(path: string): string {
  if (!path.startsWith("/api/session")) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}client_id=${encodeURIComponent(getClientId())}`;
}

export function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function httpFetch(url: string, options?: RequestInit): Promise<Response> {
  if (isTauriRuntime()) {
    return tauriFetch(url, options);
  }
  return fetch(url, options);
}

// ── API fetch helpers ────────────────────────────────────────────

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const requestPath = addClientIdQuery(path);
  const url = `${getBaseUrl()}${requestPath}`;
  const headers: Record<string, string> = {};
  if (options?.body) headers["Content-Type"] = "application/json";
  if (_authToken) headers["Authorization"] = `Bearer ${_authToken}`;

  let res: Response;
  try {
    res = await httpFetch(url, {
      method: options?.method ?? "GET",
      headers,
      body: options?.body as string | undefined,
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error(`[apiFetch] Network error: ${options?.method ?? "GET"} ${url} -> ${msg}`);
    throw new Error(`${msg} (${options?.method ?? "GET"} ${requestPath})`);
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export async function apiFetchText(path: string): Promise<string> {
  const requestPath = addClientIdQuery(path);
  const headers: Record<string, string> = {};
  if (_authToken) headers["Authorization"] = `Bearer ${_authToken}`;
  const res = await httpFetch(`${getBaseUrl()}${requestPath}`, { headers });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.text();
}

export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const requestPath = addClientIdQuery(path);
  const headers: Record<string, string> = {};
  if (_authToken) headers["Authorization"] = `Bearer ${_authToken}`;
  const res = await httpFetch(`${getBaseUrl()}${requestPath}`, {
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
