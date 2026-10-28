import { useEffect } from 'react';

type Handler = (e: KeyboardEvent) => void;

/**
 * Global keyboard shortcuts. Keys look like "ctrl+k", "ctrl+shift+l", "f1", "/".
 * Shortcuts without ctrl/alt are ignored while typing in a field.
 */
export function useShortcuts(map: Record<string, Handler>, enabled = true) {
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const typing = !!t?.closest('input,textarea,select,[contenteditable="true"]');
      const combo = [(e.ctrlKey || e.metaKey) && 'ctrl', e.shiftKey && 'shift', e.altKey && 'alt', e.key.toLowerCase()].filter(Boolean).join('+');
      const fn = map[combo];
      if (!fn) return;
      if (typing && !(e.ctrlKey || e.metaKey || e.altKey) && !/^f\d+$/.test(e.key.toLowerCase())) return;
      e.preventDefault();
      fn(e);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [map, enabled]);
}
