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

const errors = new Set<string | number>();

/** Close the error toasts: they are about the page they came from (AppLayout calls this when the page changes). */
export function clearErrors() {
  for (const id of errors) sonner.dismiss(id);
  errors.clear();
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
    case 'error': { const id = sonner.error(title, opts); errors.add(id); return id; }
    default: return sonner.info(title, opts);
  }
}
