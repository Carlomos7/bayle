import { useEffect, useMemo } from 'react';
import { Outlet } from '@tanstack/react-router';
import { useQueryClient } from '@tanstack/react-query';
import { useCurrent, useSettings } from '@/data/hooks';
import { useUi } from '@/state/ui';
import { useDialogs } from '@/state/dialogs';
import { clearErrors } from '@/state/toasts';
import { Toaster } from '@/components/ui/sonner';
import { TooltipProvider } from '@/components/bayle/overlay';
import { MenuBar } from './shell/MenuBar';
import { TopBar } from './shell/TopBar';
import { Rail } from './shell/Rail';
import { CommandPalette } from './shell/CommandPalette';
import { GlobalDialogs } from './shell/GlobalDialogs';
import { LaunchPrompt } from './shell/LaunchPrompt';
import { HealthSheet } from './shell/HealthSheet';
import { Glossary, Welcome } from './shell/Welcome';
import { UnsupportedPage } from './UnsupportedPage';
import { EngineBanner } from './shell/EngineScreens';
import { useApplyAppearance } from './theme';
import { useShortcuts } from './useShortcuts';
import { useLaunch } from './useLaunch';
import { PAGE_IDS, useGo, usePage } from './nav';

/** The root route's layout: window chrome around whichever page the router shows. */
export function AppLayout() {
  const settings = useSettings();
  useApplyAppearance(settings.data?.appearance);
  const page = usePage();
  const go = useGo();
  const setCommandOpen = useUi((s) => s.setCommandOpen);
  const show = useDialogs((s) => s.show);
  const qc = useQueryClient();
  const { game } = useCurrent();
  const { launch } = useLaunch();
  const onboarded = useUi((s) => s.onboarded);
  // First run: the welcome flow opens once, after the stores have loaded.
  useEffect(() => { if (!onboarded && settings.data) show({ id: 'welcome' }); }, [onboarded, settings.data, show]);

  const shortcuts = useMemo(() => ({
    'ctrl+k': () => setCommandOpen(true),
    'ctrl+l': () => void launch(),
    'ctrl+n': () => show({ id: 'newProfile' }),
    'ctrl+o': () => show({ id: 'install' }),
    f1: () => show({ id: 'setup' }),
    f5: () => void qc.invalidateQueries(),
    ...Object.fromEntries(PAGE_IDS.map((p, i) => [`ctrl+${i + 1}`, () => go.page(p)])),
  }), [setCommandOpen, launch, show, qc, go]);
  useShortcuts(shortcuts);

  // Each page opens at its top, not where the previous page was scrolled to, and without the last page's errors.
  useEffect(() => { document.getElementById('scroll')?.scrollTo({ top: 0 }); clearErrors(); }, [page]);

  const gamePage = page === 'mods' || page === 'merge' || page === 'configs' || page === 'saves';

  return (
    <TooltipProvider>
      <div className="grid h-full grid-cols-[56px_1fr] grid-rows-[30px_48px_1fr]">
        <MenuBar />
        <TopBar />
        <Rail />
        <main className="app-main relative flex min-h-0 min-w-0 flex-col overflow-clip">
          <EngineBanner />
          <div id="scroll" className="relative z-[1] min-h-0 flex-1 overflow-auto">
            {game && !game.supported && gamePage ? <UnsupportedPage game={game} /> : <Outlet />}
          </div>
        </main>
      </div>
      <CommandPalette />
      <GlobalDialogs />
      <LaunchPrompt />
      <HealthSheet />
      <Welcome />
      <Glossary />
      <Toaster />
    </TooltipProvider>
  );
}
