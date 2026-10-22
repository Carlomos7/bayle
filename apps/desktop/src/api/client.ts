import { invoke } from "@tauri-apps/api/core";
import { createClient } from "@bayle/api";
import type { Problem } from "./types";

/** What the Rust shell learned from the engine's handshake line. */
export interface Backend {
  base_url: string;
  token: string;
  app_version: string;
  contract_version: string;
}

export class ApiError extends Error {
  constructor(
    readonly problem: Problem,
    readonly status: number,
  ) {
    super(problem.message);
  }
}

export const getBackend = () => invoke<Backend>("get_backend");

function toProblem(body: unknown, status: number): Problem {
  const p = body as Partial<Problem> | null;
  if (typeof p?.code === "string" && typeof p.message === "string") {
    return { code: p.code, message: p.message, details: p.details ?? {} };
  }
  return { code: "http_error", message: `HTTP ${status}`, details: {} };
}

export type Api = ReturnType<typeof createApi>;

/** The generated client (packages/api) for this run's handshake, with get/post for the page and plan routes that throw ApiError. (The generated client only adds the token to operations with a security entry, so these add it themselves.) */
export function createApi(backend: Pick<Backend, "base_url" | "token">) {
  const auth = { Authorization: `Bearer ${backend.token}` };
  const api = createClient({ baseUrl: backend.base_url, token: backend.token });
  async function call<T>(run: Promise<{ data?: unknown; error?: unknown; response?: Response }>): Promise<T> {
    const r = await run;
    if (r.error !== undefined || !r.response?.ok) throw new ApiError(toProblem(r.error, (r.response?.status ?? 0)), (r.response?.status ?? 0));
    return r.data as T;
  }
  return {
    ...api,
    get: <T>(url: string) => call<T>(api.client.get({ url, headers: auth })),
    post: <T>(url: string, body: unknown = {}) =>
      call<T>(api.client.post({ url, body, headers: { ...auth, "Content-Type": "application/json" } })),
  };
}
