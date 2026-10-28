import type { ReactNode } from 'react';
import { ExternalLink, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tag } from '@/components/bayle/badge';
import { Wordmark } from '@/components/bayle/layout';
import { useCall } from '@/data/hooks';
import { useDialogs } from '@/state/dialogs';
import { toast } from '@/state/toasts';
import { useSettingsCtx } from './context';
import { LINKS } from '@/app/links';
import type { RowDef } from './schema';

/** The controls for action rows, keyed by row id. */
export function ActionControl({ row }: { row: RowDef }): ReactNode {
  const call = useCall();
  const { askResetAll } = useSettingsCtx();
  switch (row.id) {
    case 'steamShortcut': return <Button size="sm" onClick={() => toast({ kind: 'success', title: 'Steam shortcuts point at Bayle', detail: 'Restart Steam to see the change.' })}>Point shortcuts here</Button>;
    case 'tips': return <Button size="sm" variant="ghost" onClick={() => toast({ kind: 'info', title: 'Tips will show again on the Mods page' })}>Show them again</Button>;
    case 'installed': return <>
      <Button size="sm" variant="ghost" onClick={() => void call((a) => a.openUrl(LINKS.releases))}>Releases</Button>
      <Button size="sm" icon={<RefreshCw />} onClick={() => void call((a) => a.checkForUpdates()).then((i) => i && toast({ kind: 'info', title: i.update ? `Bayle ${i.update.version} is available` : 'You have the latest version' }))}>Check now</Button>
    </>;
    case 'supportLogs': return <Button size="sm" onClick={() => void call((a) => a.saveSupportLogs()).then((p) => p && toast({ kind: 'success', title: 'Logs saved for support', detail: p }))}>Save logs…</Button>;
    case 'clearCache': return <Button size="sm" onClick={() => void call((a) => a.clearBootBoostCache(), { title: 'Boot boost cache cleared' })}>Clear cache</Button>;
    case 'resetAll': return <Button size="sm" variant="danger" onClick={askResetAll}>Reset all…</Button>;
    default: return null;
  }
}

/** A tag after the label, for rows whose label needs live info. */
export function LabelExtra({ row }: { row: RowDef }): ReactNode {
  const { info } = useSettingsCtx();
  if (row.tag) return <Tag tone="vio">{row.tag}</Tag>;
  if (row.id === 'me3' && info?.me3Latest && info.me3Latest !== info.me3Version) return <Tag tone="warn">{info.me3Latest} available</Tag>;
  if (row.id === 'installed' && info) return <Tag>{info.version}</Tag>;
  return null;
}

/** The About card. */
export function AboutCard() {
  const { info } = useSettingsCtx();
  const show = useDialogs((s) => s.show);
  const call = useCall();
  return (
    <div className="flex flex-wrap items-center gap-3.5 rounded-lg border border-line2 bg-panel px-[18px] py-4">
      <Wordmark width={170} className="mr-1" />
      <div className="flex min-w-0 flex-col gap-0.5 border-l border-line pl-4">
        <b className="font-semibold">Version {info?.version}</b>
        <span className="text-ui text-t3">GPLv3 · Windows, Linux and Steam Deck · by Carlomos7</span>
      </div>
      <span className="flex-1" />
      <Button size="sm" variant="ghost" onClick={() => show({ id: 'setup' })}>How to use</Button>
      <Button size="sm" variant="ghost" onClick={() => void call((a) => a.openUrl(LINKS.thirdParty))}>Third-party notices</Button>
      <Button size="sm" icon={<ExternalLink />} onClick={() => void call((a) => a.openUrl(LINKS.repo))}>GitHub</Button>
    </div>
  );
}
