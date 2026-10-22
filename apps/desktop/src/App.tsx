import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { Toaster } from "sonner";
import { BackendProvider } from "@/api/backend";
import { getBackend, type Backend } from "@/api/client";
import { EventsProvider } from "@/api/EventsProvider";
import { PromptHost, usePrompts } from "@/components/PromptHost";
import { sonnerToasts, toProblem } from "@/components/toasts";
import { buildRouter } from "@/router";
import { pathForPage } from "@/shell/pages";
import { ThemeProvider, useTheme } from "@/theme/ThemeProvider";

type Router = ReturnType<typeof buildRouter>;

function Events({ router }: { router: Router }) {
  const { askPrompt } = usePrompts();
  const deps = useMemo(
    () => ({
      toasts: sonnerToasts,
      ask: askPrompt,
      navigate: (page: string) => {
        const to = pathForPage(page);
        if (to) void router.navigate({ to });
      },
    }),
    [askPrompt, router],
  );
  return (
    <EventsProvider deps={deps}>
      <RouterProvider router={router} />
    </EventsProvider>
  );
}

function Themed({ children }: { children: React.ReactNode }) {
  const { resolved } = useTheme();
  return (
    <>
      {children}
      <Toaster theme={resolved === "light" ? "light" : "dark"} position="bottom-right" />
    </>
  );
}

/** Everything under the backend handshake. `backend` is injectable for tests; the shell supplies it otherwise. */
export function AppWithBackend({ backend, router }: { backend: Backend; router?: Router }) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } }),
  );
  const [defaultRouter] = useState(() => buildRouter());
  const r = router ?? defaultRouter;
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BackendProvider backend={backend}>
          <PromptHost>
            <Themed>
              <Events router={r} />
            </Themed>
          </PromptHost>
        </BackendProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export function App() {
  const [state, setState] = useState<Backend | { error: string } | null>(null);
  useEffect(() => {
    getBackend().then(setState, (e: unknown) => setState({ error: toProblem(e).message }));
  }, []);
  if (!state) return <main className="p-6">Connecting to the engine...</main>;
  if ("error" in state) return <main role="alert" className="p-6 text-status-danger">Engine unavailable: {state.error}</main>;
  return <AppWithBackend backend={state} />;
}
