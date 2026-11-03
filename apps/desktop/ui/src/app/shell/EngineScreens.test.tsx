// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ApiProvider } from '@/data/ApiProvider';
import { resetEngineState } from '@/data/engine';
import { createGateway } from '@/api/gateway/hub';
import { fakeTransport, flush } from '@/api/gateway/fakeTransport.test-util';
import { createMockApi } from '@/api/mock/mockApi';
import type { EngineStatus } from '@/api/gateway/protocol';
import type { DesktopActions } from '@/api/gateway/transport';
import { toast } from '@/state/toasts';
import { EngineBanner, EngineGate } from './EngineScreens';

vi.mock('@/state/toasts', () => ({ toast: vi.fn() }));

afterEach(() => { cleanup(); resetEngineState(); vi.clearAllMocks(); });

async function mount(initial: EngineStatus, app?: DesktopActions) {
  const t = Object.assign(fakeTransport(initial), app ? { app } : {});
  const gateway = createGateway(t);
  render(
    <ApiProvider runtime={{ mode: 'preview', gateway, api: createMockApi() }}>
      <EngineGate><EngineBanner /><p>The app</p></EngineGate>
    </ApiProvider>,
  );
  await act(async () => { await flush(); await flush(); });
  const push = async (s: EngineStatus) => { await act(async () => { t.setStatus(s); await flush(); }); };
  return { t, push };
}

describe('engine screens', () => {
  it('shows a start screen until the engine is ready, then the app', async () => {
    const { push } = await mount({ state: 'starting', epoch: 1 });
    expect(screen.getByText('Starting Bayle…')).toBeTruthy();
    expect(screen.queryByText('The app')).toBeNull();
    await push({ state: 'ready', epoch: 1 });
    expect(screen.getByText('The app')).toBeTruthy();
  });

  it('says what went wrong when the first start fails, and Try again asks Rust to restart it', async () => {
    const { t } = await mount({ state: 'failed', epoch: 1, problem: { code: 'engine_exited', message: 'It stopped while starting (exit code 1).' } });
    expect(screen.getByText("Bayle's engine didn't start")).toBeTruthy();
    expect(screen.getByText('It stopped while starting (exit code 1).')).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Try again/ })); await flush(); });
    expect(t.restarts()).toBe(1);
  });

  it('explains an incompatible engine without offering a retry', async () => {
    await mount({ state: 'incompatible', epoch: 1, contract: '2', expectedContract: '1' });
    expect(screen.getByText("This engine doesn't match this app")).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Try again/ })).toBeNull();
  });

  it('keeps the app on screen with a banner when a ready engine restarts, then clears it', async () => {
    const { push } = await mount({ state: 'ready', epoch: 1 });
    await push({ state: 'restarting', epoch: 1 });
    expect(screen.getByText('The app')).toBeTruthy();
    expect(screen.getByText("Bayle's engine is restarting…")).toBeTruthy();
    await push({ state: 'starting', epoch: 2 });
    await push({ state: 'ready', epoch: 2 });
    expect(screen.queryByText("Bayle's engine is restarting…")).toBeNull();
  });

  it('offers Try again in the banner when a ready engine stops for good', async () => {
    const { push, t } = await mount({ state: 'ready', epoch: 1 });
    await push({ state: 'failed', epoch: 1, problem: { code: 'engine_exited', message: 'It stopped and could not be started again.' } });
    expect(screen.getByText('It stopped and could not be started again.')).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Try again/ })); await flush(); });
    expect(t.restarts()).toBe(1);
  });

  describe('recovery actions', () => {
    const failed: EngineStatus = { state: 'failed', epoch: 1, problem: { code: 'engine_exited', message: 'It stopped while starting.' } };
    const fakeApp = (update: { version: string; current: string } | null = null) => ({
      checkUpdate: vi.fn(async () => update),
      installUpdate: vi.fn(async () => {}),
      openLogs: vi.fn(async () => {}),
      reportIssue: vi.fn(async () => {}),
      openUrl: vi.fn(async () => {}),
    });

    it('offers updates, logs and a report on the failed screen, and they call the app', async () => {
      const app = fakeApp();
      await mount(failed, app);
      expect(screen.getByRole('button', { name: /Check for updates/ })).toBeTruthy();
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Open logs/ })); await flush(); });
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Report issue/ })); await flush(); });
      expect(app.openLogs).toHaveBeenCalledTimes(1);
      expect(app.reportIssue).toHaveBeenCalledTimes(1);
    });

    it('turns Check for updates into Install Bayle <version> when there is one, and installs it', async () => {
      const app = fakeApp({ version: '0.4.1', current: '0.4.0' });
      await mount(failed, app);
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Check for updates/ })); await flush(); });
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Install Bayle 0.4.1' })); await flush(); });
      expect(app.installUpdate).toHaveBeenCalledTimes(1);
    });

    it('says Bayle is up to date, and offers no install, when there is no update', async () => {
      await mount(failed, fakeApp());
      await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Check for updates/ })); await flush(); });
      expect(toast).toHaveBeenCalledWith(expect.objectContaining({ kind: 'success', title: 'Bayle is up to date' }));
      expect(screen.queryByRole('button', { name: /Install Bayle/ })).toBeNull();
    });

    it('is also on the incompatible screen and the stopped banner', async () => {
      await mount({ state: 'incompatible', epoch: 1, contract: '2', expectedContract: '1' }, fakeApp());
      expect(screen.getByRole('button', { name: /Check for updates/ })).toBeTruthy();
      cleanup();
      const { push } = await mount({ state: 'ready', epoch: 1 }, fakeApp());
      expect(screen.queryByRole('button', { name: /Open logs/ })).toBeNull();
      await push(failed);
      expect(screen.getByRole('button', { name: /Open logs/ })).toBeTruthy();
    });

    it('renders nothing extra when the transport has no app actions', async () => {
      await mount(failed);
      expect(screen.getByRole('button', { name: /Try again/ })).toBeTruthy();
      expect(screen.queryByRole('button', { name: /Check for updates|Open logs|Report issue/ })).toBeNull();
    });
  });
});
