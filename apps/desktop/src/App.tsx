import { getVersion } from "@tauri-apps/api/app";
import { useEffect, useState } from "react";
import type { Health } from "@bayle/api";
import { createApi, getBackend } from "./api";

type State = { error: string } | { health: Health; shell: string } | null;

export function App() {
  const [state, setState] = useState<State>(null);

  useEffect(() => {
    getBackend()
      .then(async (backend) => ({
        health: await createApi(backend).health(),
        shell: await getVersion(),
      }))
      .then(setState, (e: unknown) => setState({ error: String(e) }));
  }, []);

  if (!state) return <main>Connecting to the engine...</main>;
  if ("error" in state) return <main role="alert">Engine unavailable: {state.error}</main>;
  return (
    <main>
      <h1>Bayle</h1>
      <p>Engine: {state.health.ready ? "ready" : "starting"}</p>
      <p>Engine version: {state.health.app_version}</p>
      <p>API contract: {state.health.contract_version}</p>
      <p>Shell version: {state.shell}</p>
    </main>
  );
}
