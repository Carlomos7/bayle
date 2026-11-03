import { useApi, useStatus } from '@/data/ApiProvider';
import { useCurrent, useSettings } from '@/data/hooks';
import { useUi } from '@/state/ui';
import { toast } from '@/state/toasts';
import { router } from '@/router';
import { hasOverhaul } from '@/features/mods/status';

/** Launch the active profile. Exported so menus and shortcuts can call it. */
export function useLaunch() {
  const api = useApi();
  const status = useStatus();
  const { game, profile } = useCurrent();
  const mode = useUi((s) => s.launchMode);
  const settings = useSettings();
  const busy = status.state === 'busy' || status.state === 'running';
  const launch = async () => {
    if (!game?.supported || !profile) return;
    if (busy) { toast({ kind: 'info', title: status.text }); return; }
    // A stale build is rebuilt first, so the game never starts with old merged data. The toast says why, with a way to see the details.
    const stale = mode !== 'Vanilla' && hasOverhaul(profile) && profile.merge === 'needs';
    if (stale && settings.data?.launch.autoRebuild !== false) {
      toast({ kind: 'info', title: 'Rebuilding merged game data first', detail: 'About 40 s. The game starts when it is done.', action: { label: 'What changed', run: () => void router.navigate({ to: '/merge' }) } });
    } else if (stale) {
      toast({ kind: 'warn', title: 'Starting with a stale build', detail: 'Rebuild on launch is off in Settings.', action: { label: 'Open Merge', run: () => void router.navigate({ to: '/merge' }) } });
    }
    try { await api.launch(game.id, profile.id, mode); } catch (e) { toast({ kind: 'error', title: (e as Error).message }); }
  };
  return { launch, disabled: !game?.supported || !profile || busy, mode };
}
