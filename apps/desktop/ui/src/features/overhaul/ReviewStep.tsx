import { BookCheck, Box, CircleAlert, Cpu, Layers, PlayCircle, RefreshCw, Users } from 'lucide-react';
import type { ReactNode } from 'react';
import { plural } from '@/lib/utils';
import { FirstVisit } from '@/components/bayle/first-visit';
import { countByAction, ACTION_SHORT, type Draft } from './actions';
import { cn } from '@/lib/utils';

export interface SetupUser { profileId: string; name: string; running: boolean }

function Item({ icon, title, children }: { icon: ReactNode; title: ReactNode; children?: ReactNode }) {
  return (
    <li className="flex items-start gap-3 border-b border-line px-4 py-3 last:border-b-0">
      <span className="mt-0.5 text-t3 [&_svg]:size-4">{icon}</span>
      <div className="min-w-0"><div className="text-body font-medium">{title}</div>{children && <div className="mt-0.5 text-xs text-t3">{children}</div>}</div>
    </li>
  );
}

const SOURCE = { bundled: 'Bayle ships this recipe', community: 'From the community recipe list', yours: 'Your saved recipe' };

/** Where the recipe came from and whether this download matches it. Most people only need to read this line. */
function RecipeCard({ draft }: { draft: Draft }) {
  const r = draft.recipe;
  if (!r) {
    return (
      <div className="flex items-start gap-3 rounded-lg border border-warn/35 bg-warn-bg/40 px-4 py-3 text-ui">
        <CircleAlert className="mt-0.5 size-4 shrink-0 text-warn" />
        <div><b className="font-semibold">No recipe for {draft.name} yet.</b> Bayle proposed one from the download. Check the files under Advanced before installing; the recipe is saved for next time.</div>
      </div>
    );
  }
  const tone = r.check === 'match' ? 'ok' : r.check === 'soft' ? 'warn' : 'bad';
  const title = r.check === 'match' ? `Recipe for ${draft.name} ${r.forVersion}, and the download matches it.`
    : r.check === 'soft' ? `Recipe for ${draft.name} ${r.forVersion}. The download differs a little; Bayle allowed for it.`
    : `This download is not ${draft.name} ${r.forVersion}, which the recipe was written for.`;
  return (
    <div className={cn('flex items-start gap-3 rounded-lg border px-4 py-3 text-ui', tone === 'ok' ? 'border-ok/35 bg-ok-bg/40' : tone === 'warn' ? 'border-warn/35 bg-warn-bg/40' : 'border-bad/35 bg-bad-bg/40')}>
      {tone === 'ok' ? <BookCheck className="mt-0.5 size-4 shrink-0 text-ok" /> : <CircleAlert className={cn('mt-0.5 size-4 shrink-0', tone === 'warn' ? 'text-warn' : 'text-bad')} />}
      <div className="min-w-0">
        <b className="font-semibold">{title}</b> <span className="text-t3">{SOURCE[r.source]}.</span>
        <div className="mt-0.5 text-t2">{r.base === 'vanilla' ? 'Made against the game\'s own files, so its changes merge with your other mods as intended.' : r.base === 'unknown' ? 'It does not say what it was made against. Bayle compares it against the game\'s own files anyway and says so in the report.' : `Made against ${r.base.mod}. It is compared against that, not against the game's own files.`}</div>
        {r.differences?.length ? <ul className="m-0 mt-1 list-disc pl-4 text-t2">{r.differences.map((d) => <li key={d} className="font-mono text-caption">{d}</li>)}</ul> : null}
        {r.check === 'mismatch' && <div className="mt-1 text-t2">Pick the matching download, or write a recipe for this one under Advanced.</div>}
      </div>
    </div>
  );
}

/** Step 1: what will happen, in plain words, before anything is written. Natives and Files are there to change it. */
export function ReviewStep({ draft, mode, profileName, users }: { draft: Draft; mode: 'edit' | 'install'; profileName?: string; users: SetupUser[] }) {
  const included = draft.files.filter((f) => f.action !== 'leave');
  const summary = countByAction(included).map(([a, n]) => `${n.toLocaleString()} ${ACTION_SHORT[a]}`).join(', ');
  const live = users.filter((u) => !u.running);
  const skipped = users.filter((u) => u.running);
  const natives = draft.dlls.map((d) => `${d.name}${d.loadEarly ? ', starts early' : ''}${d.loadAfterOthers ? ', after the other natives' : ''}`).join('; ');

  return (
    <div className="flex flex-col gap-3">
      {mode === 'install' && (
        <FirstVisit tipKey="install-plan" title="You don't need to understand this screen">
          It lists what Bayle is about to do, so you can check it if you want. Most people just press Install. If something goes wrong, Undo in Activity puts it all back.
        </FirstVisit>
      )}
      <RecipeCard draft={draft} />
      <p className="m-0 text-ui text-t3">Nothing is written until you press {mode === 'install' ? 'Install' : 'Save'}. Undo in Activity puts everything back. Natives and Advanced are there if the recipe got something wrong.</p>
      <ul className="m-0 list-none overflow-hidden rounded-lg border border-line2 bg-panel p-0">
        <Item icon={<Box />} title={`Uses ${plural(included.length, 'file')} from ${draft.gameDir}`}>{summary || 'No files are included.'}</Item>
        {draft.dlls.length > 0 && <Item icon={<Cpu />} title={plural(draft.dlls.length, 'native')}>{natives}</Item>}
        {mode === 'install' ? (
          <>
            <Item icon={<Layers />} title={`Adds it to ${profileName ?? 'this profile'}`}>Kept last in the load order, with its natives loading after the others.</Item>
            <Item icon={<RefreshCw />} title="Builds the merged game data">The game's rules{draft.languages ? `, animations and menu text in ${draft.languages} languages` : ' and animations'} are merged with the mods above it. Clashes and anything left out show on Merge.</Item>
            {draft.ownInstaller && <Item icon={<PlayCircle />} title={`Does not run ${draft.ownInstaller}`}>Bayle installs it its own way, so it can be updated and undone.</Item>}
          </>
        ) : (
          <>
            <Item icon={<Users />} title={live.length ? `Saves to ${plural(live.length, 'profile')} and rebuilds them` : 'No profile uses this setup yet'}>
              {live.map((u) => u.name).join(', ') || 'It is saved for the next install.'}
            </Item>
            {skipped.length > 0 && <Item icon={<PlayCircle />} title={`Skips ${skipped.map((u) => u.name).join(', ')}`}>In use right now. It picks up the change at its next launch.</Item>}
          </>
        )}
      </ul>
    </div>
  );
}
