import { create } from 'zustand';

/**
 * App-wide dialogs that menus, shortcuts and pages can all open.
 * Page-local dialogs stay inside their page component.
 */
export type GlobalDialog =
  | { id: 'about' }
  | { id: 'setup' }
  | { id: 'install'; path?: string }
  | { id: 'newProfile'; copyFrom?: string }
  | { id: 'renameProfile'; profileId: string }
  | { id: 'deleteProfile'; profileId: string }
  | { id: 'updates' }
  | { id: 'health' }
  | { id: 'welcome' }
  | { id: 'glossary' };

interface DialogStore {
  open: GlobalDialog | null;
  show: (d: GlobalDialog) => void;
  close: () => void;
}

export const useDialogs = create<DialogStore>((set) => ({
  open: null,
  show: (open) => set({ open }),
  close: () => set({ open: null }),
}));
