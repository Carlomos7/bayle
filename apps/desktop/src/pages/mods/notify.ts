import { toast } from "sonner";

/** A toast with one action (Undo, Edit options). Errors stay until closed, like the shell's. */
export function sayAction(text: string, label: string, onClick: () => void, error = false): void {
  (error ? toast.error : toast)(text, {
    action: { label, onClick },
    duration: error ? Infinity : 10000,
    closeButton: error,
  });
}

export const say = (text: string): void => void toast(text, { duration: 4500 });
export const sayError = (text: string): void => void toast.error(text, { duration: Infinity, closeButton: true });
