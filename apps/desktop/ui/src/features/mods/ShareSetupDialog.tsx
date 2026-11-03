import { FEATURES } from '@/lib/features';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Copy, FileDown, Users } from 'lucide-react';
import type { ManifestDifference, Profile } from '@/api';
import { useApi } from '@/data/ApiProvider';
import { useCall } from '@/data/hooks';
import { Dialog, Tabs } from '@/components/bayle/overlay';
import { Tag } from '@/components/bayle/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/bayle/layout';
import { toast } from '@/state/toasts';
import { cn } from '@/lib/utils';

const KIND_TONE: Record<ManifestDifference['kind'], 'warn' | 'bad' | 'neutral'> = {
  'missing-here': 'bad', 'missing-there': 'bad', version: 'warn', hash: 'warn', order: 'neutral', enabled: 'warn', config: 'warn', launch: 'warn', loader: 'neutral',
};

/**
 * Play with friends on the same setup without sending anyone your mod files:
 * a manifest of versions and hashes to share, and a comparison that says
 * where two setups disagree and what that means for playing together.
 */
export function ShareSetupDialog({ profile, open, onOpenChange }: { profile: Profile; open: boolean; onOpenChange: (o: boolean) => void }) {
  const api = useApi();
  const call = useCall();
  const manifest = useQuery({ queryKey: ['manifest', profile.id], queryFn: () => api.exportManifest(profile.id), enabled: open });
  const [tab, setTab] = useState('mine');
  const [cmp, setCmp] = useState<Awaited<ReturnType<typeof api.compareManifest>>>(null);
  const [comparing, setComparing] = useState(false);
  const m = manifest.data;

  const compare = async () => {
    setComparing(true);
    const r = await call((a) => a.compareManifest(profile.id));
    setComparing(false);
    if (r) { setCmp(r); setTab('compare'); }
  };
  const save = async () => {
    const p = await call((a) => a.saveManifest(profile.id));
    if (p) toast({ kind: 'success', title: 'Setup file saved', detail: `${p}. Send it to a friend; it holds versions and hashes, no mod files.` });
  };
  const copy = () => { if (m) void navigator.clipboard?.writeText(JSON.stringify(m, null, 2)); toast({ kind: 'success', title: 'Setup copied as text' }); };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} width={640} title={`Share ${profile.name} with friends`}
      description="A setup file lists what you have: mod names, versions and fingerprints, loader version and launch options. It holds no mod files, so nothing of anyone's gets redistributed."
      footer={<><Button variant="ghost" className="mr-auto" icon={<Users />} disabled={comparing} onClick={() => void compare()}>{comparing ? 'Comparing…' : 'Compare with a friend\'s file…'}</Button><Button variant="ghost" icon={<Copy />} onClick={copy} disabled={!m}>Copy</Button><Button variant="primary" icon={<FileDown />} onClick={() => void save()} disabled={!m}>Save setup file</Button></>}>
      <Tabs value={tab} onValueChange={setTab} tabs={[
        { value: 'mine', label: 'Your setup', content: !m ? <p className="text-t3">Reading…</p> : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-ui text-t3"><span>{m.game}</span><span>me3 {m.me3Version}</span><span>Launch: {m.launch.mode}, online {m.launch.online ? 'on' : 'off'}</span><span>made {m.madeOn}</span></div>
            <ul className="m-0 max-h-[320px] list-none divide-y divide-line overflow-auto rounded-lg border border-line2 p-0 text-ui">
              {m.mods.map((x) => (
                <li key={x.name} className="flex items-center gap-3 px-3 py-1.5">
                  <span className="w-5 text-right text-xs tabular-nums text-t4">{x.order}</span>
                  <span className={cn('flex-1 truncate', !x.enabled && 'text-t4 line-through')}>{x.name}</span>
                  {FEATURES.modVersions && <span className="font-mono text-xs text-t3">{x.version ? `v${x.version}` : ''}</span>}
                  <span className="font-mono text-micro text-t4">{x.hash.slice(0, 8)}</span>
                </li>
              ))}
            </ul>
            {m.configs.length > 0 && <p className="m-0 text-xs text-t3">Also fingerprinted: {m.configs.map((c) => c.file).join(', ')}. Contents stay private; only a fingerprint is shared, so a friend can tell whether yours match.</p>}
          </div>
        ) },
        { value: 'compare', label: 'Compare', count: cmp?.differences.length, content: !cmp ? (
          <EmptyState title="Pick a friend's setup file to compare" action={<Button icon={<Users />} onClick={() => void compare()}>Compare with a friend's file…</Button>}>
            Bayle lists every place the two setups disagree and what it means for playing together. Nothing is changed.
          </EmptyState>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="text-ui text-t3">Comparing with <b className="font-semibold text-t1">{cmp.theirs.profileName}</b>, made {cmp.theirs.madeOn}.{!cmp.differences.length && ' Everything matches.'}</div>
            {cmp.differences.length > 0 && (
              <ul className="m-0 max-h-[360px] list-none divide-y divide-line overflow-auto rounded-lg border border-line2 p-0">
                {cmp.differences.map((d, i) => (
                  <li key={i} className="px-3 py-2 text-ui">
                    <div className="flex flex-wrap items-center gap-2"><b className="font-semibold">{d.subject}</b><Tag tone={KIND_TONE[d.kind]}>{d.kind.replace('-', ' ')}</Tag></div>
                    <div className="mt-0.5 grid grid-cols-2 gap-3 text-xs max-[560px]:grid-cols-1"><span><span className="text-t4">You: </span>{d.mine}</span><span><span className="text-t4">Them: </span>{d.theirs}</span></div>
                    <div className="mt-0.5 text-xs text-t2">{d.effect}</div>
                  </li>
                ))}
              </ul>
            )}
            <p className="m-0 text-xs text-t3">Detected from the two files only. Bayle does not change anything here; fix differences on the Mods page, or send them your setup file.</p>
          </div>
        ) },
      ]} />
    </Dialog>
  );
}
