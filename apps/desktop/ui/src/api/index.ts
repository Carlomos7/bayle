/**
 * Picks how the app reaches Bayle's engine, once, at startup:
 *
 * - desktop: inside the Tauri app. Always the real gateway (Rust). The mock
 *   cannot be selected here, whatever the build flags say.
 * - preview: a browser during development (vite dev), or a build made on
 *   purpose with VITE_BAYLE_DEMO=1. Uses the in-memory mock engine, and the UI
 *   says "Preview data" so it is never mistaken for the real thing.
 * - outside-desktop: a production build opened in a plain browser. No data at
 *   all; the app says to open Bayle from its desktop app.
 *
 * The preview lives behind '@/api/preview', which desktop builds replace
 * with an empty stub (vite.config.ts), so they can't carry the mock or its
 * data (checked by src/api/boundary.test.ts against dist/).
 */
import type { BayleApi } from './BayleApi';
import { createGateway, type Gateway } from './gateway/hub';
import { createGatewayApi } from './gateway/gatewayApi';
import { isTauri, tauriTransport } from './gateway/tauri';
import type { MockEngine } from './gateway/mock';
import { guardApi } from './guard';

export type RuntimeMode = 'desktop' | 'preview' | 'outside-desktop';

export interface Runtime {
  mode: Exclude<RuntimeMode, 'outside-desktop'>;
  api: BayleApi;
  gateway: Gateway;
  /** Preview only: drive the mock engine (crash, fail…) from tests and the console. */
  mockEngine?: MockEngine;
}

export function selectMode(o: { inTauri: boolean; dev: boolean; demoBuild: boolean }): RuntimeMode {
  if (o.inTauri) return 'desktop';
  if (o.dev || o.demoBuild) return 'preview';
  return 'outside-desktop';
}

export async function createRuntime(): Promise<Runtime | { mode: 'outside-desktop' }> {
  const mode = selectMode({ inTauri: isTauri(), dev: import.meta.env.DEV, demoBuild: import.meta.env.VITE_BAYLE_DEMO === '1' });
  if (mode === 'desktop') {
    const gateway = createGateway(tauriTransport());
    return { mode, gateway, api: guardApi(createGatewayApi(gateway), gateway) };
  }
  if (mode === 'preview') {
    const { createPreviewRuntime } = await import('@/api/preview');
    return createPreviewRuntime();
  }
  return { mode: 'outside-desktop' };
}

export type { BayleApi } from './BayleApi';
export * from './types';
export { uiReady } from './gateway/tauri';
