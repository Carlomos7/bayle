// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ApiProvider } from '@/data/ApiProvider';
import { resetEngineState } from '@/data/engine';
import { createGateway } from '@/api/gateway/hub';
import { fakeTransport, flush } from '@/api/gateway/fakeTransport.test-util';
import { createMockApi } from '@/api/mock/mockApi';
import { useDialogs } from '@/state/dialogs';
import { Welcome } from './Welcome';

afterEach(() => { cleanup(); resetEngineState(); });

async function lookAround(existing: number) {
  const mock = createMockApi();
  const real = await mock.listProfiles('er');
  const api = {
    ...mock,
    listProfiles: async () => real.slice(0, existing),
    createProfile: vi.fn(async () => ({ message: 'made', profileId: 'new1' })),
    setActiveProfile: vi.fn(async () => {}),
  };
  render(<ApiProvider runtime={{ mode: 'preview', gateway: createGateway(fakeTransport({ state: 'ready', epoch: 1 })), api }}><Welcome /></ApiProvider>);
  await act(async () => { useDialogs.getState().show({ id: 'welcome' }); for (let i = 0; i < 20; i++) await flush(); });
  for (let i = 0; i < 2; i++) await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Next|Continue/ })); await flush(); });
  await act(async () => { fireEvent.click(screen.getByRole('button', { name: /Just look around/ })); for (let i = 0; i < 20; i++) await flush(); });
  return api;
}

describe('Welcome: Just look around', () => {
  it('makes an empty profile and picks it when the game has none', async () => {
    const api = await lookAround(0);
    expect(api.createProfile).toHaveBeenCalledWith('er', 'My mods');
    // picking it waits for the refresh that follows the create
    await waitFor(() => expect(api.setActiveProfile).toHaveBeenCalledWith('er', 'new1'));
  });

  it('makes nothing when there are profiles already', async () => {
    const api = await lookAround(1);
    expect(api.createProfile).not.toHaveBeenCalled();
  });
});
