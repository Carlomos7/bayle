# 0015 The web view reaches the engine only through an allowlisted Rust gateway

**Status:** Accepted for the communication architecture (owner, 2026-10-27). The Rust libraries and the code-generation
tooling are not chosen here; Phase 0 picks them by evaluation. Supersedes the web-view side of
[0011](0011-transport.md); the engine side of 0011 (loopback HTTP and SSE, token, handshake, contract) stands.

## Context

[0011](0011-transport.md) had the React front end call the engine's HTTP API directly, with the per-launch token in the
web view and `connect-src http://127.0.0.1:*` in its content security policy. The owner chose instead that the web view
never holds the engine's address or token. Three gateway shapes were compared: one handwritten Rust command per
operation (the contract has 150), a single generic proxy the web view can point anywhere, and a custom URI scheme. The
first is a second contract to maintain by hand; the second gives the web view the same reach as holding the token.

## Decision

**Path:** React (Vite, TypeScript) → Tauri IPC (commands and a Channel) → Rust gateway → loopback HTTP and SSE with the
per-launch token → the Python engine (FastAPI). The Qt app keeps calling the engine in-process and is unchanged.

**Who owns what:**

- **React:** presentation only. No engine port, no token, no file paths it was not given by the engine, no network
  access to the engine. Its CSP allows Tauri IPC and nothing on `127.0.0.1`.
- **Rust gateway:** starts and supervises the engine ([0012](0012-process-lifecycle.md)), holds its port and token,
  checks every call against the allowlist, forwards it, and relays events. It holds no Bayle logic: no merging, no job
  state of its own, no file operations on Bayle's behalf.
- **Python engine:** the only authority for application logic, jobs, merging, persistence and file operations, and for
  validating request bodies.

**The gateway surface is the contract, filtered by an allowlist:**

- One gateway command takes an operation id from `docs/api/openapi.json` (for example `activity`, `get_job`,
  `cancel_job`) plus its path parameters, query and body. The HTTP method and path come from the contract, never from
  the web view, and the web view cannot set headers.
- An operation is callable only if it is on an allowlist checked into the repository. The list grows page by page as
  screens move to React. An id that is not on it is refused with `gateway.not_allowed` and never reaches the engine.
- The gateway checks the parameter names against the contract and builds the URL itself; the engine validates the
  values. Building the URL is the gateway's job, not the engine's, because a value must never change which route is
  called:
  - each path parameter fills exactly one path segment and is percent-encoded as one (`/`, `?`, `#`, `%` and `\`
    included); an empty value, `.` or `..` is refused with `gateway.bad_parameter`;
  - query parameters are encoded as query pairs by a URL library, never joined as text;
  - a parameter the contract does not list for that operation is refused, not dropped;
  - the scheme, host, port, `/v1` prefix and every header are fixed by the gateway; the body is sent as JSON.
  Tests cover values that try to escape their segment (`../health`, `a/b`, `%2e%2e`, `?x=1`, `#`, an encoded slash).
- The Rust operation table and the TypeScript request and response types are generated from, or mechanically checked
  against, the same `openapi.json` snapshot that CI already checks (`apps/engine/scripts/export_openapi.py --check`).
  A contract change that the gateway or the front end does not match fails CI.

**Events:**

- The gateway holds one SSE connection to `GET /v1/events` and forwards each envelope `{seq, job_id, type, data}`
  unchanged over a Tauri Channel, in the order received.
- It adds the engine generation (below) to what it forwards, and on reconnect to the same engine process sends
  `Last-Event-ID` so the engine's ring buffer replays what was missed. The ring buffer lives in that process's memory,
  so replay never crosses a restart: after one, the gateway starts the stream fresh.
- Job ids are the engine's. While the same engine process runs, `GET /v1/jobs/{id}` is the snapshot the front end uses
  to recover a job whose events it missed.

**Cancellation:** `cancel_job` is an allowlisted operation like any other. The front end shows the engine's answer.
If the connection breaks before an answer, the outcome is reported as unknown, never as cancelled.

**Errors:** engine errors pass through unchanged, with their HTTP status and the engine's `Problem` body
(`code`, `message`, `details`). The gateway's own errors use the same shape with `gateway.*` codes: `engine_unavailable`, `not_allowed`, `bad_parameter`,
`timeout`, `contract_mismatch`. The engine's start-up exits 2 (bad settings) and 3 (data folder in use) are shown as they are and
not retried.

**Restarts:** each engine start has a generation number, raised by the gateway. When the engine exits, every pending
call fails with `gateway.engine_unavailable`, the gateway restarts it with backoff, and it tells the front end the new
generation. The front end then drops events of the old generation and reloads the state it shows.

What a restart does not recover: the engine's `JobManager` keeps live job snapshots in memory only
(`work/jobs.py`, `_records`), so after a restart the old job ids are unknown and `get_job` answers 404. A job that was
running is shown as interrupted by the restart, with its outcome unknown, never as finished or resumed. Its effects on
disk are whatever the engine's staged writes left: a build that did not commit leaves the previous output in place.
Recovering or resuming interrupted jobs needs persisted job state and its own tests; that is later work under decision 4
(jobs), not something this gateway provides.

**Libraries and code generation** are chosen in Phase 0 on these criteria: maintained, works on Windows and Linux,
licence compatible with GPL-3.0, small surface. Candidates to evaluate: `tokio`, `reqwest` and an SSE client crate for
the gateway; `openapi-typescript` or the existing Hey API setup for TypeScript types; a build-time generator, or
`typify`/`progenitor`, for the Rust operation table. Other applications' gateways are studied, not copied.

**Phase 0 validation**, with the engine on a scratch data folder and Qt untouched:

1. Health: the gateway starts the engine, reads the handshake, checks the contract major version, calls `health`.
2. Activity data: the Activity page renders `activity` through the gateway.
3. Job progress: a job started through the gateway reports ordered progress events and a final event; cancel is
   answered by the engine.
4. Restart: killing the engine fails the pending call with `gateway.engine_unavailable`, the gateway restarts it, the
   page reloads its state, and a job that was running shows as interrupted, not finished.
5. Isolation: the web view has neither the port nor the token, a call outside the allowlist is refused, and parameter
   values cannot change the route called.

## Why

The web view is the part most exposed to untrusted content (mod names, descriptions, changelogs). Keeping the token and
the engine's address in Rust means a script injected there can only ask for allowlisted operations. Generating from the
existing contract keeps one source of truth without writing 150 Rust wrappers, and the allowlist keeps the gateway from
being an open proxy.

## Consequences

- A screen moves to React only with its operations added to the allowlist; the list documents what the new front end
  can reach.
- The TypeScript client in `packages/api` is no longer called by React over HTTP; its types, or newly generated ones,
  describe the gateway's calls.
- 0011's `connect-src http://127.0.0.1:*` no longer applies to the web view.
- The gateway adds one hop of latency to every call; it has not been measured.

## Alternatives considered

- **One handwritten Rust command per operation:** 150 commands kept in step with Python by hand.
- **A generic proxy:** the web view could reach any route; the token in Rust would protect little.
- **A custom URI scheme:** keeps the generated HTTP client, but it is still a proxy unless it carries the same
  allowlist, and Tauri's custom-protocol responses may not stream, so events would need a Channel anyway.
- **The web view calling FastAPI directly (0011):** the token would live in the web view.
- **stdio JSON-RPC:** no port at all, but replaces the existing HTTP contract and its tooling.

## Reopen if

Phase 0 shows the gateway cannot keep event order or recover after restarts, the generated table cannot follow the
contract, or the added latency is felt in the UI.
