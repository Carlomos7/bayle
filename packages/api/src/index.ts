import { createClient as createHeyClient, createConfig } from "./generated/client";
import { health } from "./generated";
import { streamEvents, type StreamOptions } from "./events";

export * from "./generated";
export * from "./events";

/** The one place that adds the base URL and the bearer token. */
export function createClient({ baseUrl, token }: { baseUrl: string; token: string }) {
  const client = createHeyClient(createConfig({ baseUrl, auth: () => token }));
  return {
    client,
    health: () => health({ client, throwOnError: true }).then((r) => r.data),
    events: (o: Pick<StreamOptions, "lastEventId" | "signal"> = {}) => streamEvents({ baseUrl, token, ...o }),
  };
}
