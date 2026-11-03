import { describe, expect, it, vi } from 'vitest';

const sonner = vi.hoisted(() => {
  let n = 0;
  const show = vi.fn(() => ++n);
  return { toast: { success: show, info: show, warning: show, error: show, dismiss: vi.fn() } };
});
vi.mock('sonner', () => sonner);

import { clearErrors, toast } from './toasts';

describe('toasts', () => {
  it('closes only the error toasts when the page changes, once each', () => {
    toast({ kind: 'success', title: 'Done' });
    const e = toast({ kind: 'error', title: 'It failed' });
    toast({ kind: 'info', title: 'Update', sticky: true });
    clearErrors();
    expect(sonner.toast.dismiss.mock.calls).toEqual([[e]]);
    clearErrors();
    expect(sonner.toast.dismiss).toHaveBeenCalledTimes(1);
  });
});
