// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ApiProvider } from '@/data/ApiProvider';
import { resetEngineState } from '@/data/engine';
import { createGateway } from '@/api/gateway/hub';
import { fakeTransport, flush } from '@/api/gateway/fakeTransport.test-util';
import { createMockApi } from '@/api/mock/mockApi';
import { LaunchPrompt } from './LaunchPrompt';

afterEach(() => { cleanup(); resetEngineState(); });

describe('Play questions', () => {
  it('shows the question in words, sends the chosen answer, and closes', async () => {
    const t = fakeTransport({ state: 'ready', epoch: 1 });
    render(<ApiProvider runtime={{ mode: 'preview', gateway: createGateway(t), api: createMockApi() }}><LaunchPrompt /></ApiProvider>);
    await act(async () => { await flush(); await flush(); });
    expect(screen.queryByRole('dialog')).toBeNull();
    await act(async () => {
      t.event({ seq: 1, type: 'started', job_id: 'p1', data: { title: 'Starting…', quiet: true } });
      t.event({ seq: 2, type: 'prompt', job_id: 'p1', data: { prompt_id: 'q1', kind: 'question', code: 'online_risk', facts: {}, options: [{ key: 'offline_instead', role: 'primary' }, { key: 'online_anyway', role: 'danger' }, { key: 'cancel', role: 'normal' }] } });
      await flush();
    });
    expect(screen.getByText('This setup can get you flagged online')).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Play offline' })); await flush(); });
    expect(t.calls.filter((c) => c.operation === 'answer_prompt').map((c) => c.params)).toEqual([{ prompt_id: 'q1', choice: 'offline_instead' }]);
    expect(screen.queryByText('This setup can get you flagged online')).toBeNull();
  });
});
