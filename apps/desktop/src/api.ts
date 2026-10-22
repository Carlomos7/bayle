import { invoke } from "@tauri-apps/api/core";

/** What the Rust shell learned from the engine's handshake line. */
export interface Backend {
  base_url: string;
  token: string;
  app_version: string;
  contract_version: string;
}

export interface Health {
  app_version: string;
  contract_version: string;
  ready: boolean;
}

export const getBackend = () => invoke<Backend>("get_backend");

/** The one place that adds the bearer header and the base URL. */
export function createApi(backend: Pick<Backend, "base_url" | "token">) {
  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${backend.base_url}${path}`, {
      ...init,
      headers: { ...init.headers, Authorization: `Bearer ${backend.token}` },
    });
    if (!response.ok) throw new Error(`${init.method ?? "GET"} ${path}: HTTP ${response.status}`);
    return (await response.json()) as T;
  }
  return { get: <T>(path: string) => request<T>(path) };
}
