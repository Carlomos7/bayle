# 0011 The interface talks to the backend over loopback HTTP and server-sent events

**Status:** Proposed. Waiting for the spikes below; the owner has not yet chosen the transport.

## Context

If the front end is a web view in its own process (Tauri), it needs a way to call about 200 operations, receive job
progress and pushes (game state, update state), and cancel jobs. Bulk data is mostly paths on the same machine, not bytes.
A bare "progress: 45" message is not enough: jobs need an id, ordering and a guaranteed final event.

## Decision

The backend runs as a local server (FastAPI under uvicorn) and the front end uses it like this:

- **Calls:** JSON over HTTP under `/v1`. Reads are `GET`; operations are `POST` and return a result, a job id (202), or a
  plan. Busy or game-running answers are 409.
- **Events:** one server-sent-events stream, `GET /v1/events`, with an envelope `{seq, job_id, type, data}`. Progress is
  rate-limited; terminal events and prompts are never dropped; a ring buffer of 1000 events supports `Last-Event-ID`
  replay, and `GET /v1/jobs/{id}` recovers a missed ending. The client reads the stream with `fetch`, not `EventSource`,
  because `EventSource` cannot send a header.
- **Port:** the backend binds port 0 on the literal `127.0.0.1` and prints one JSON line on stdout with the port and the
  contract version. The shell never picks the port, which avoids a race.
- **Token:** 32 random bytes per launch, passed in an environment variable (not on the command line), required on every
  route, health included, compared in constant time. Never in a URL or a log.
- **Origin and host:** CORS with the exact web-view origins and no credentials, `TrustedHostMiddleware` for `127.0.0.1`
  only (blocks DNS rebinding), no `/docs` or `/openapi.json` in release builds, no access log.
- **Contract:** the OpenAPI document is committed as a snapshot and checked in CI; the TypeScript client is generated
  from it. The event union is declared by hand.
- **Version:** `/v1/health` returns the contract version; the shell refuses a different major version.

**Fallback:** JSON-RPC over the sidecar's stdin and stdout, relayed by the Rust shell. It opens no port. The operation,
job and event model is unchanged; only the framing is.

## Why

HTTP gives routing, validation, OpenAPI and a generated client for free; a stdio relay would mean writing that glue in
Rust and could not use the generated client as is. The risk of an open port is small and listed: token, exact origins and
host check cover other local processes and web pages. WebSocket was not chosen because nothing needs client-to-server
streaming and it would need its own origin check.

## Consequences

- Another process of the same user can still reach the port; only the token guards it.
- The CSP must allow `connect-src http://127.0.0.1:*`.
- A cancel is a separate request, so it works while the event stream is open.

## Alternatives considered

- **stdio JSON-RPC through the shell:** best security, most glue; kept as the fallback.
- **Tauri's own IPC for everything:** needs a Rust command per operation or a generic proxy, so it equals the fallback.
- **WebSocket:** more code, same result.
- **Named pipe or Unix socket:** a web view cannot open them without a Rust proxy.

## Evidence and open points

Tauri and FastAPI documentation: https://v2.tauri.app/develop/calling-rust/ , https://v2.tauri.app/security/csp/ ,
https://fastapi.tiangolo.com/tutorial/server-sent-events/ , https://fastapi.tiangolo.com/tutorial/cors/ ,
https://starlette.dev/middleware/ , https://uvicorn.dev/settings/ , OWASP WebSocket cheat sheet. No latency was measured.
Not yet verified: the exact CSP syntax and the origin value on WebKitGTK (Steam Deck), and that a generated client
handles the event union under Python 3.14.

## Reopen if

The Steam Deck spike shows loopback HTTP or the CSP does not work there, or the owner wants no open port; then the
fallback becomes the decision.
