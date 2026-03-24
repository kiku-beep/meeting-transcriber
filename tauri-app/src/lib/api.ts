import { fetch as tauriFetch } from "@tauri-apps/plugin-http";

const BASE_URL = "http://127.0.0.1:8000";
const WS_URL = "ws://127.0.0.1:8000";

export { BASE_URL, WS_URL };

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  let res: Response;
  try {
    res = await tauriFetch(url, {
      method: options?.method ?? "GET",
      headers: {
        ...(options?.body ? { "Content-Type": "application/json" } : {}),
      },
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
  const res = await tauriFetch(`${BASE_URL}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.text();
}

export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const res = await tauriFetch(`${BASE_URL}${path}`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}
