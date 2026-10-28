import { FolderX, FolderInput, GitMerge, RefreshCw, Wrench } from 'lucide-react';
import { dllLabel } from './identity';
import type { Game, Profile } from '@/api';
import { Notice } from '@/components/bayle/layout';
import { Button } from '@/components/ui/button';
import { useAction, useBuild } from '@/data/hooks';
import { hasOverhaul } from './status';

export interface AttentionProps {
  game: Game;
  profile: Profile;
  onWhy: () => void;
  onMoveIn: () => void;
  onTakeOver: () => void;
  onShowMod: (id: string) => void;
  onReinstall: (id: string) => void;
  onRemove: (id: string) => void;
}

/** One line per thing that needs a look, each with its fix right there. */
export function Attention({ game, profile, onWhy, onMoveIn, onTakeOver, onShowMod, onReinstall, onRemove }: AttentionProps) {
  const { run, pending } = useAction();
  const build = useBuild(profile.id);
  const rows = [];
  const updated = !!(game.build && game.lastRunBuild && game.build !== game.lastRunBuild);
  const stale = hasOverhaul(profile) && profile.merge === 'needs';
  const natives = profile.mods.filter((m) => m.kind === 'native' && m.enabled);
  const risky = natives.filter((m) => m.native?.afterUpdate === 'may-fail').map(dllLabel);
  const fine = natives.filter((m) => m.native?.afterUpdate === 'ok').map(dllLabel);
  const unknown = natives.filter((m) => !m.native?.afterUpdate || m.native.afterUpdate === 'unknown').map(dllLabel);
  const rebuild = <Button size="sm" disabled={pending} onClick={() => void run((a) => a.rebuildMerged(profile.id))}>Rebuild now</Button>;
  if (updated) {
    // One notice for everything a game update causes: DLLs that may fail, and merges that start from new originals.
    rows.push(
      <Notice key="build" tone={stale || risky.length ? 'warn' : 'info'} icon={<RefreshCw />} title={`${game.name} updated ${game.lastRunBuild} → ${game.build}`}
        actions={stale ? <><Button size="sm" variant="ghost" onClick={onWhy}>What changed</Button>{rebuild}</> : undefined}>
        {risky.length ? `${risky.join(', ')} ${risky.length === 1 ? 'hooks' : 'hook'} into code that moved, so ${risky.length === 1 ? 'it' : 'they'} may fail until updated.` : ''}
        {fine.length ? ` ${fine.join(', ')} still ${fine.length === 1 ? 'matches' : 'match'}.` : ''}
        {unknown.length ? ` ${unknown.join(', ')}: no evidence for this build.` : ''}
        {stale ? ' The merged build is stale.' : ''}
      </Notice>,
    );
  } else if (stale) {
    const changes = build.data?.changes ?? [];
    const toCheck = build.data?.clashes.filter((c) => c.needsReview).length ?? 0;
    rows.push(
      <Notice key="merge" tone="warn" icon={<GitMerge />} title="Merged game data needs a rebuild"
        actions={<><Button size="sm" variant="ghost" onClick={onWhy}>What changed</Button>{rebuild}</>}>
        {changes.length ? `${changes.length === 1 ? changes[0]!.title : `${changes.length} things changed: ${changes.map((c) => c.title.replace(/^You /, 'you ')).join('; ')}`}.` : 'Something it was built from changed.'}
        {toCheck ? ` ${toCheck} of your picks ${toCheck === 1 ? 'deserves' : 'deserve'} a look.` : ' Launch rebuilds for you, about 40 s.'}
      </Notice>,
    );
  }
  if (profile.outsidePath) {
    rows.push(
      <Notice key="outside" tone="info" icon={<FolderInput />} title="This profile is outside Bayle's folder" actions={<Button size="sm" onClick={onMoveIn}>Move in…</Button>}>
        {profile.outsidePath}. Move it in to keep its mods together and every change undoable.
      </Notice>,
    );
  }
  if (profile.installer) {
    rows.push(
      <Notice key="installer" tone="warn" icon={<Wrench />} title={`${profile.installer.name} was set up by its own installer`} actions={<Button size="sm" onClick={onTakeOver}>Take over…</Button>}>
        Bayle can't update or undo it until you take it over.
      </Notice>,
    );
  }
  profile.mods.filter((m) => m.missing).forEach((m) => {
    rows.push(
      <Notice key={`missing:${m.id}`} tone="bad" icon={<FolderX />} title={`${m.name}'s folder is missing`}
        actions={<><Button size="sm" variant="ghost" onClick={() => onShowMod(m.id)}>Show</Button><Button size="sm" variant="ghost" onClick={() => onReinstall(m.id)}>Install again</Button><Button size="sm" variant="danger" onClick={() => onRemove(m.id)}>Remove</Button></>}>
        {m.folder} is not there, so Launch leaves it out.
      </Notice>,
    );
  });
  if (!rows.length) return null;
  return <div role="region" aria-label="Things to look at" className="overflow-hidden rounded-lg border border-line2">{rows}</div>;
}
