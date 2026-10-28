/**
 * The production transport: Tauri IPC to the Rust gateway. The only file in
 * the app that imports @tauri-apps/api. It knows command names, never the
 * engine's port, token or URLs (Rust owns those).
 *
 * Command names and payloads follow protocol.ts, which is a PROPOSAL until the
 * Rust workstream agrees it.
 */
import { Channel, invoke, isTauri } from '@tauri-apps/api/core';
import { COMMANDS, type AppUpdate, type EngineStatus, type GatewayMessage } from './protocol';
import { toGatewayError, type GatewayTransport } from './transport';

export { isTauri };

export function tauriTransport(): GatewayTransport {
  const call = async <T,>(cmd: string, args?: Record<string, unknown>): Promise<T> => {
    try {
      return await invoke<T>(cmd, args);
    } catch (e) {
      throw toGatewayError(e); // Rust rejects with a Problem {code, message, details}
    }
  };

  return {
    kind: 'tauri',
    status: () => call<EngineStatus>(COMMANDS.status),
    restart: () => call<void>(COMMANDS.restart),
    call: <T,>(operation: string, params?: Record<string, unknown>, opts?: { epoch?: number }) =>
      call<T>(COMMANDS.call, { operation, params: params ?? {}, epoch: opts?.epoch ?? null }),
    async subscribe(onMessage) {
      let open = true;
      // A Channel delivers in order and belongs to this webview; Rust stops sending when it is dropped.
      const channel = new Channel<GatewayMessage>((m) => { if (open) onMessage(m); });
      await call<void>(COMMANDS.subscribe, { channel });
      return () => {
        if (!open) return;
        open = false;
        void call<void>(COMMANDS.unsubscribe, { channelId: channel.id }).catch(() => { /* already gone with the engine */ });
      };
    },
    app: {
      checkUpdate: () => call<AppUpdate | null>(COMMANDS.updateCheck),
      installUpdate: () => call<void>(COMMANDS.updateInstall),
      openLogs: () => call<void>(COMMANDS.openLogs),
      reportIssue: () => call<void>(COMMANDS.reportIssue),
      openUrl: (url: string) => call<void>(COMMANDS.openUrl, { url }),
    },
  };
}
