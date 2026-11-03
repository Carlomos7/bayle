import { Toaster as Sonner, type ToasterProps } from 'sonner';
import { CheckCircle2, Info, Loader2, TriangleAlert, XCircle } from 'lucide-react';

/**
 * shadcn/ui Sonner, themed with Bayle's variables. Toasts sit bottom right,
 * and move up while the bulk bar or a side panel is open (see index.css).
 */
function Toaster(props: ToasterProps) {
  return (
    <Sonner
      className="toaster group"
      position="bottom-right"
      visibleToasts={3}
      gap={8}
      icons={{
        success: <CheckCircle2 className="size-4 text-ok" />,
        info: <Info className="size-4 text-info" />,
        warning: <TriangleAlert className="size-4 text-warn" />,
        error: <XCircle className="size-4 text-bad" />,
        loading: <Loader2 className="size-4 animate-spin text-t3" />,
      }}
      toastOptions={{
        classNames: {
          toast: 'items-start! gap-3! rounded-lg! border-line2! bg-raise! p-3! text-t1! shadow-pop! font-sans!',
          title: 'text-body! font-medium! text-t1!',
          description: 'text-xs! text-t3!',
          actionButton: 'h-auto! bg-transparent! p-0! text-xs! font-semibold! text-accent! hover:underline!',
          closeButton: 'border-line2! bg-raise! text-t3! hover:text-t1!',
          error: 'border-bad/40!',
          icon: 'mt-0.5!',
        },
      }}
      {...props}
    />
  );
}

export { Toaster };
