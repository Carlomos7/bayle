// @vitest-environment jsdom
// The real toasts (no mock): a recovery screen replaces the app, so its actions' toasts must still show.
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ApiProvider } from '@/data/ApiProvider';
import { resetEngineState } from '@/data/engine';
import { createGateway } from '@/api/gateway/hub';
import { fakeTransport, flush } from '@/api/gateway/fakeTransport.test-util';
import { createMockApi } from '@/api/mock/mockApi';
import type { EngineStatus } from '@/api/gateway/protocol';
import { EngineGate } from './EngineScreens';

afterEach(() => { cleanup(); resetEngineState(); });

const app = () => ({
  checkUpdate: vi.fn(async () => null),
  installUpdate: vi.fn(async () => {}),
  openLogs: vi.fn(async () => {}),
  reportIssue: vi.fn(async () => {}),
  openUrl: vi.fn(async () => {}),
});

async function checkOn(status: EngineStatus) {
  const gateway = createGateway(Object.assign(fakeTransport(status), { app: app() }));
  render(
    <ApiProvider runtime={{ mode: 'preview', gateway, api: createMockApi() }}>
      <EngineGate><p>The app</p></EngineGate>
    </ApiProvider>,
  );
  await act(async () => { await flush(); await flush(); });
  expect(screen.queryByText('The app')).toBeNull();
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Check for updates/ })); await flush(); });
  expect(await screen.findByText('Bayle is up to date')).toBeTruthy();
}

describe('toasts on the engine screens', () => {
  it('shows the update check result on the incompatible screen', async () => {
    await checkOn({ state: 'incompatible', epoch: 1, contract: '2', expectedContract: '1' });
  });

  it('shows the update check result on the failed screen', async () => {
    await checkOn({ state: 'failed', epoch: 1, problem: { code: 'engine_exited', message: 'It stopped while starting.' } });
  });
});
