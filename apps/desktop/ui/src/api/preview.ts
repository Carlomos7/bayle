/**
 * The browser preview: the mock engine and the mock BayleApi on top of it.
 * Imported only through '@/api/preview', which vite.config.ts points at
 * preview.disabled.ts for desktop builds, so the mock (and its made-up data)
 * can't ship in the desktop app.
 */
import { createGateway } from './gateway/hub';
import { createMockEngine, scenarioFromLocation, type MockEngine } from './gateway/mock';
import { createMockApi } from './mock/mockApi';
import { guardApi } from './guard';
import type { Runtime } from './index';

export function createPreviewRuntime(): Runtime {
  const mockEngine = createMockEngine({ scenario: scenarioFromLocation() });
  const gateway = createGateway(mockEngine);
  if (import.meta.env.DEV) (window as unknown as { __bayleEngine?: MockEngine['controls'] & { restart: () => Promise<void> } }).__bayleEngine = { ...mockEngine.controls, restart: () => mockEngine.restart() };
  return { mode: 'preview', gateway, mockEngine, api: guardApi(createMockApi(mockEngine), gateway) };
}
