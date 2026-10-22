import { createContext, use, useMemo, type ReactNode } from "react";
import { createApi, type Api, type Backend } from "./client";

const ApiContext = createContext<Api | null>(null);

export function BackendProvider({ backend, children }: { backend: Backend; children: ReactNode }) {
  const api = useMemo(() => createApi(backend), [backend]);
  return <ApiContext value={api}>{children}</ApiContext>;
}

export function useApi(): Api {
  const api = use(ApiContext);
  if (!api) throw new Error("useApi outside BackendProvider");
  return api;
}
