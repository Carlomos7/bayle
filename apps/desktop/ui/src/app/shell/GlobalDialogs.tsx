import { useEffect, useState } from 'react';
import { NameDialog } from '@/components/bayle/name-dialog';
import { CheckCircle2, CircleAlert } from 'lucide-react';
import { useDialogs } from '@/state/dialogs';
import { useRuntime } from '@/data/ApiProvider';
import { useAction, useAppInfo, useCall, useCurrent, useProfiles, useSettings } from '@/data/hooks';
import { Dialog, ConfirmDialog } from '@/components/bayle/overlay';
import { Button } from '@/components/ui/button';
import { Wordmark } from '@/components/bayle/layout';
import { InstallDialog } from '@/features/mods/InstallDialog';
import { LINKS } from '../links';

function AboutDialog() {
  const close = useDialogs((s) => s.close);
  const info = useAppInfo();
  const settings = useSettings();
  const call = useCall();
  return (
    <Dialog open onOpenChange={(o) => !o && close()} header={<Wordmark className="mb-3" />} title={<span className="sr-only">About Bayle</span>}
      description={`Version ${info.data?.version ?? ''} · ${settings.data?.updates.channel === 'beta' ? 'Beta' : 'Stable'} channel`}
      footer={<><Button variant="ghost" className="mr-auto" onClick={() => void call((a) => a.openUrl(LINKS.licence))}>Licence</Button><Button variant="ghost" onClick={() => void call((a) => a.openUrl(LINKS.thirdParty))}>Third-party notices</Button><Button onClick={close}>OK</Button></>}>
      <p className="mt-0 text-ui text-t3">A mod launcher and save toolkit for Elden Ring and Nightreign, built on me3. GPLv3.</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-ui">
        <dt className="text-t3">me3</dt><dd className="m-0">{info.data?.me3Version}</dd>
        <dt className="text-t3">Data folder</dt><dd className="m-0 font-mono">{info.data?.dataFolder}</dd>
        <dt className="text-t3">Platform</dt><dd className="m-0">{info.data?.platform}</dd>
      </dl>
    </Dialog>
  );
}

/** F1: what the launcher needs, green when found. */
function SetupDialog() {
  const close = useDialogs((s) => s.close);
  const settings = useSettings();
  const info = useAppInfo();
  const { game } = useCurrent();
  const checks = [
    { ok: !!settings.data?.paths.games[game?.id ?? ''], title: `${game?.name ?? 'The game'} found`, detail: settings.data?.paths.games[game?.id ?? ''] ?? 'Pick its folder in Settings' },
    { ok: !!info.data?.me3Version, title: `me3 ${info.data?.me3Version ?? ''}`, detail: info.data?.me3Latest && info.data.me3Latest !== info.data.me3Version ? `${info.data.me3Latest} is available` : 'up to date' },
    { ok: true, title: 'A profile with mods', detail: 'Install a mod from a .zip, .7z, .rar, a .dll or a folder' },
    { ok: true, title: 'Saves found', detail: 'Bayle repairs them after every session' },
  ];
  return (
    <Dialog open onOpenChange={(o) => !o && close()} width={520} header={<Wordmark className="mb-3" />} title="Set up to play"
      description={`What the launcher needs for ${game?.name ?? 'your game'}. Green means found; fix the rest and Launch lights up.`}
      footer={<Button variant="primary" onClick={close}>Done</Button>}>
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {checks.map((c) => (
          <li key={c.title} className="flex items-start gap-3 rounded-lg border border-line bg-t1/2 p-3">
            {c.ok ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" /> : <CircleAlert className="mt-0.5 size-4 shrink-0 text-warn" />}
            <div className="min-w-0"><div className="font-medium">{c.title}</div><div className="truncate font-mono text-xs text-t3">{c.detail}</div></div>
          </li>
        ))}
      </ul>
    </Dialog>
  );
}

function UpdatesDialog() {
  const close = useDialogs((s) => s.close);
  const call = useCall();
  const { gateway } = useRuntime();
  const [state, setState] = useState<'checking' | 'done'>('checking');
  const [found, setFound] = useState<string | undefined>();
  useEffect(() => { void call((a) => a.checkForUpdates()).then((i) => { setFound(i?.update?.version); setState('done'); }); }, [call]);
  return (
    <Dialog open onOpenChange={(o) => !o && close()} title="Updates"
      description={state === 'checking' ? 'Checking GitHub…' : found ? `Bayle ${found} is available. One click, then a restart. Your settings stay.` : 'You have the latest version.'}
      footer={<><Button variant="ghost" onClick={close}>Later</Button>{found && gateway.app && <Button variant="primary" onClick={() => void call(() => gateway.app!.installUpdate())}>Update now</Button>}</>} />
  );
}

function NewProfileDialog({ copyFrom }: { copyFrom?: string }) {
  const close = useDialogs((s) => s.close);
  const { game } = useCurrent();
  const profiles = useProfiles(game?.id ?? '');
  const src = profiles.data?.find((p) => p.id === copyFrom);
  const call = useCall();
  const { run } = useAction();
  const create = async (name: string) => {
    if (!game) return;
    const r = await run((a) => a.createProfile(game.id, name, copyFrom));
    if (r) await call((a) => a.setActiveProfile(game.id, r.profileId));
  };
  return (
    <NameDialog onOpenChange={(o) => !o && close()} title={src ? `Duplicate ${src.name}` : 'New profile'}
      description={src ? 'Same mods and load order. Shared mods stay shared, nothing is copied twice.' : `An empty profile for ${game?.name}. Add mods to it after.`}
      initial={src ? `${src.name} copy` : ''} placeholder="e.g. Co-op night" submitLabel="Create"
      taken={profiles.data?.map((p) => p.name)} takenMessage="There is already a profile with that name."
      onSubmit={(name) => void create(name)} />
  );
}

function RenameProfileDialog({ profileId }: { profileId: string }) {
  const close = useDialogs((s) => s.close);
  const { game } = useCurrent();
  const profiles = useProfiles(game?.id ?? '');
  const p = profiles.data?.find((x) => x.id === profileId);
  const { run } = useAction();
  return (
    <NameDialog onOpenChange={(o) => !o && close()} title={`Rename ${p?.name ?? 'profile'}`} label="New name" initial={p?.name} submitLabel="Rename" rename
      taken={profiles.data?.map((x) => x.name)} takenMessage="There is already a profile with that name."
      onSubmit={(name) => void run((a) => a.renameProfile(profileId, name))} />
  );
}

function DeleteProfileDialog({ profileId }: { profileId: string }) {
  const close = useDialogs((s) => s.close);
  const { game } = useCurrent();
  const profiles = useProfiles(game?.id ?? '');
  const p = profiles.data?.find((x) => x.id === profileId);
  const { run } = useAction();
  const call = useCall();
  return (
    <ConfirmDialog open onOpenChange={(o) => !o && close()} title={`Delete ${p?.name}?`} danger confirmLabel="Delete profile"
      description="Its mods stay in the library if other profiles use them. Restore it from Activity."
      onConfirm={() => void (async () => {
        const other = profiles.data?.find((x) => x.id !== profileId);
        if (game && other) await call((a) => a.setActiveProfile(game.id, other.id));
        await run((a) => a.deleteProfile(profileId));
      })()} />
  );
}

/** Renders whichever app-wide dialog is open. */
export function GlobalDialogs() {
  const open = useDialogs((s) => s.open);
  if (!open) return null;
  switch (open.id) {
    case 'about': return <AboutDialog />;
    case 'setup': return <SetupDialog />;
    case 'updates': return <UpdatesDialog />;
    case 'install': return <InstallDialog path={open.path} />;
    case 'newProfile': return <NewProfileDialog copyFrom={open.copyFrom} />;
    case 'renameProfile': return <RenameProfileDialog profileId={open.profileId} />;
    case 'deleteProfile': return <DeleteProfileDialog profileId={open.profileId} />;
  }
}
