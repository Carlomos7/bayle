# Bayle desktop (Tauri), Phase 0

Not shipped. The Qt app in `apps/qt-desktop` is still the product.

- `gateway/`: the Rust gateway of [ADR 0015](../../docs/decisions/0015-rust-gateway.md). It starts and supervises the engine,
  holds its port and token, forwards only operations listed in `gateway/allowlist.txt` (checked against
  `docs/api/openapi.json` at build time), and relays the engine's events in order.
- `ui/`: the React UI (Vite, TanStack, Tailwind; see `ui/README.md`). `pnpm install` then `pnpm dev` (port 5173) or
  `pnpm verify` (typecheck, lint, build, test) from that folder. In the app it reaches the engine only through the
  gateway commands; the browser-only preview and mock are stubbed out of desktop builds.
- `src-tauri/`: the Tauri shell. It serves `ui/dist` (`devUrl` is `http://localhost:5173` for the dev server) and
  implements the UI's gateway commands (`engine_*`, `app_*`). `cargo tauri dev` / `cargo tauri build` start the UI
  dev server / build it first (`beforeDevCommand` / `beforeBuildCommand`, run in `ui/`).
  `dev-ui/` is a throwaway page that drives the same commands; run it with
  `cargo run -p bayle-desktop -- --config '{"build":{"frontendDist":"../dev-ui"}}'`.

Run (needs Rust, `uv` and `pnpm`): `cargo tauri dev` from this folder (or `cargo run -p bayle-desktop` with `pnpm dev` already running in `ui/`). The engine runs from source with a scratch
data folder (`%TEMP%\bayle-gateway-dev`, or `BAYLE_GATEWAY_DATA`), never the real one. A release build bundles the
frozen engine: run `uv run --project apps/engine python apps/desktop/scripts/build_engine.py` from the repo root first.

Test: `cargo test -p bayle-gateway`. The engine test starts the real engine on a temporary folder and runs ADR 0015's
Phase 0 checks: health, Activity data, a job's ordered events and cancel, restart after a kill, and isolation.
