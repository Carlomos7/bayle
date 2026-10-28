import { CheckCircle2, CircleAlert, Info, TriangleAlert } from 'lucide-react';
import { useNavigate } from '@tanstack/react-router';
import { useDialogs } from '@/state/dialogs';
import { useAction, useBuild, useCurrent } from '@/data/hooks';
import { profileHealth, type HealthFix } from '@/features/mods/health';
import { Sheet } from '@/components/bayle/overlay';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/**
 * "Before you play": everything that needs the user for the active profile,
 * each with its one-click fix. Opens from the chip next to Launch, on any
 * page, so nobody has to know which page a problem lives on.
 */
export function HealthSheet() {
  const open = useDialogs((s) => s.open?.id === 'health');
  const close = useDialogs((s) => s.close);
  const { game, profile } = useCurrent();
  const build = useBuild(profile?.id);
  const health = profileHealth(game, profile, build.data);
  const navigate = useNavigate();
  const { run, pending } = useAction();

  const act = async (fix: HealthFix) => {
    if (!profile) return;
    switch (fix.kind) {
      case 'rebuild': await run((a) => a.rebuildMerged(profile.id)); return;
      case 'merge': close(); void navigate({ to: '/merge', search: {} }); return;
      case 'mod': close(); void navigate({ to: '/mods', search: { mod: fix.modId } }); return;
      case 'takeOver': case 'moveIn': close(); void navigate({ to: '/mods', search: { mod: undefined } }); return;
      case 'turnOff': await run((a) => a.setModsEnabled(profile.id, fix.modIds, false)); return;
    }
  };

  return (
    <Sheet open={open} onOpenChange={(o) => !o && close()} width={520} title="Before you play" subtitle={profile ? `${profile.name} · ${health.ok ? 'nothing needs you' : health.label}` : ''}
      footer={<Button className="ml-auto" variant={health.ok ? 'primary' : 'default'} onClick={close}>{health.ok ? 'Done' : 'Close'}</Button>}>
      {health.ok ? (
        <div className="flex items-start gap-3 rounded-lg border border-ok/35 bg-ok-bg/40 px-4 py-3 text-ui">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" />
          <div><b className="font-semibold">Nothing to fix.</b> Everything Bayle checks is in order. Launch when you like; how the mods behave in game is still theirs to prove.</div>
        </div>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {health.items.map((it) => {
            const Icon = it.tone === 'bad' ? CircleAlert : it.tone === 'warn' ? TriangleAlert : Info;
            return (
              <li key={it.id} className={cn('rounded-lg border bg-panel px-4 py-3', it.tone === 'bad' ? 'border-bad/35' : it.tone === 'warn' ? 'border-warn/35' : 'border-line2')}>
                <div className="flex items-start gap-3 max-[560px]:flex-wrap">
                  <Icon className={cn('mt-0.5 size-4 shrink-0', it.tone === 'bad' ? 'text-bad' : it.tone === 'warn' ? 'text-warn' : 'text-info')} />
                  <div className="min-w-0 flex-1 max-[560px]:basis-[calc(100%-28px)]">
                    <div className="text-body font-semibold">{it.title}</div>
                    <div className="mt-0.5 text-xs text-t3">{it.detail}</div>
                  </div>
                  <Button size="sm" className="max-[560px]:ml-7" variant={it.tone === 'info' ? 'ghost' : 'default'} disabled={pending} onClick={() => void act(it.fix)}>{it.fixLabel}</Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {!health.ok && <p className="m-0 mt-4 text-xs text-t3">Warnings don't stop Launch. Things marked red are left out of the game until fixed.</p>}
    </Sheet>
  );
}
