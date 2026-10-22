import { invoke } from "@tauri-apps/api/core";
import { createClient } from "@bayle/api";

/** What the Rust shell learned from the engine's handshake line. */
export interface Backend {
  base_url: string;
  token: string;
  app_version: string;
  contract_version: string;
}

export const getBackend = () => invoke<Backend>("get_backend");

/** Typed client for the engine (packages/api), bound to this run's handshake. */
export const createApi = (backend: Pick<Backend, "base_url" | "token">) =>
  createClient({ baseUrl: backend.base_url, token: backend.token });
