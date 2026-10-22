import { invoke } from "@tauri-apps/api/core";

// Temporary hand-written client; WP30 swaps it for the generated one in packages/api.

/** What the Rust shell learned from the engine's handshake line. */
export interface Backend {
  base_url: string;
  token: string;
  app_version: string;
  contract_version: string;
}

/** The backend's error body (application/problem+json). */
export interface Problem {
  code: string;
  message: string;
  details: Record<string, unknown>;
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

async function toProblem(response: Response): Promise<Problem> {
  try {
    const body = (await response.json()) as Partial<Problem>;
    if (typeof body.code === "string" && typeof body.message === "string") {
      return { code: body.code, message: body.message, details: body.details ?? {} };
    }
  } catch {
    // not JSON: fall through
  }
  return { code: "http_error", message: `HTTP ${response.status}`, details: {} };
}

export type Api = ReturnType<typeof createApi>;

/** The one place that adds the bearer header and the base URL. */
export function createApi(backend: Pick<Backend, "base_url" | "token">) {
  const headers = (extra?: HeadersInit) => ({ ...extra, Authorization: `Bearer ${backend.token}` });

  async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(`${backend.base_url}${path}`, { ...init, headers: headers(init.headers) });
    if (!response.ok) throw new ApiError(await toProblem(response), response.status);
    return (await response.json()) as T;
  }
  return {
    backend,
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body: unknown = {}) =>
      request<T>(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }),
    /** Open the SSE stream. fetch, not EventSource: the stream needs the bearer header. */
    stream: (lastEventId: number | null, signal: AbortSignal) =>
      fetch(`${backend.base_url}/v1/events`, {
        signal,
        headers: headers({
          Accept: "text/event-stream",
          ...(lastEventId === null ? {} : { "Last-Event-ID": String(lastEventId) }),
        }),
      }),
  };
}
