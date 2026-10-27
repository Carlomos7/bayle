# Bayle desktop (Tauri), Phase 0

Not shipped. The Qt app in `apps/qt-desktop` is still the product.

- `gateway/`: the Rust gateway of [ADR 0015](../../docs/decisions/0015-rust-gateway.md). It starts and supervises the engine,
  holds its port and token, forwards only operations listed in `gateway/allowlist.txt` (checked against
  `docs/api/openapi.json` at build time), and relays the engine's events in order.
- `src-tauri/`: the Tauri shell. For now it serves `dev-ui/`, a throwaway page that drives the gateway; the React UI
  replaces it.

Run (needs Rust and `uv`): `cargo run -p bayle-desktop` from this folder. The engine runs from source with a scratch
data folder (`%TEMP%\bayle-gateway-dev`, or `BAYLE_GATEWAY_DATA`), never the real one.

Test: `cargo test -p bayle-gateway`. The engine test starts the real engine on a temporary folder and runs ADR 0015's
Phase 0 checks: health, Activity data, a job's ordered events and cancel, restart after a kill, and isolation.
