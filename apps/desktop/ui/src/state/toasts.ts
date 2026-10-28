import { toast as sonner } from 'sonner';

export type ToastKind = 'success' | 'info' | 'warn' | 'error';

export interface ToastInput {
  kind: ToastKind;
  title: string;
  detail?: string;
  action?: { label: string; run: () => void };
  /** Stay until closed. Errors always do. */
  sticky?: boolean;
}

/**
 * Show a toast through Sonner. Finished work fades after a few seconds
 * (longer when it offers Undo); errors stay until closed.
 */
export function toast({ kind, title, detail, action, sticky }: ToastInput): string | number {
  const duration = sticky || kind === 'error' ? Infinity : action ? 7000 : 4500;
  const opts = {
    description: detail,
    duration,
    closeButton: kind === 'error' || sticky,
    action: action ? { label: action.label, onClick: action.run } : undefined,
  };
  switch (kind) {
    case 'success': return sonner.success(title, opts);
    case 'warn': return sonner.warning(title, opts);
    case 'error': return sonner.error(title, opts);
    default: return sonner.info(title, opts);
  }
}
