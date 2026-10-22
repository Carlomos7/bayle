import type {
  CancelledEvent, FailedEvent, FinishedEvent, GameStateEvent, InvalidatedEvent, LogEvent, NavigateEvent,
  NoticeEvent, ProgressEvent, PromptEvent, ResyncEvent, StartedEvent,
} from "./generated";

/** The generator emits no `ApiEvent` alias and types the SSE stream `unknown`, so the union is declared here from the generated members (keep in step with `ApiEvent` in bayle/api/models.py). */
export type ApiEvent =
  | StartedEvent | ProgressEvent | LogEvent | PromptEvent | FinishedEvent | FailedEvent
  | CancelledEvent | ResyncEvent | GameStateEvent | InvalidatedEvent | NoticeEvent | NavigateEvent;

export interface StreamOptions {
  baseUrl: string;
  token: string;
  /** Resume after this seq (the `seq` of the last event handled). */
  lastEventId?: number;
  signal?: AbortSignal;
  fetch?: typeof fetch;
}

/** Events in server order. Ends when the server closes the stream; reconnect with `lastEventId: event.seq`. A `resync` event means the buffer no longer reaches back that far: refetch state, then keep reading. */
export async function* streamEvents(o: StreamOptions): AsyncGenerator<ApiEvent> {
  const headers: Record<string, string> = { Authorization: `Bearer ${o.token}`, Accept: "text/event-stream" };
  if (o.lastEventId !== undefined) headers["Last-Event-ID"] = String(o.lastEventId);
  const response = await (o.fetch ?? fetch)(`${o.baseUrl}/v1/events`, { headers, signal: o.signal });
  if (!response.ok || !response.body) throw new Error(`GET /v1/events: HTTP ${response.status}`);
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) return;
      buffer += value.replace(/\r\n?/g, "\n");
      for (let end = buffer.indexOf("\n\n"); end >= 0; end = buffer.indexOf("\n\n")) {
        const data = buffer.slice(0, end).split("\n")
          .filter((line) => line.startsWith("data:")) // comments (keepalive) and id/event/retry carry nothing the payload lacks
          .map((line) => line.slice(5).replace(/^ /, ""));
        buffer = buffer.slice(end + 2);
        if (data.length) yield JSON.parse(data.join("\n")) as ApiEvent;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
}
