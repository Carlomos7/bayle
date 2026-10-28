import { useState } from 'react';
import { useRuntime } from '@/data/ApiProvider';
import { useJobStore } from '@/data/engine';
import { answerPrompt } from '@/api/gateway/adapters/shell';
import { Dialog } from '@/components/bayle/overlay';
import { Button } from '@/components/ui/button';
import { toast } from '@/state/toasts';

/** The question Play is waiting on (a prompt event of kind "question"), if any. */
interface Question { prompt_id: string; code: string; facts: Record<string, unknown>; options: { key: string; role: 'primary' | 'danger' | 'normal' }[] }

const list = (v: unknown) => (Array.isArray(v) ? v.map(String) : []);

/** What the player reads for each question code (modules/launch/service.py), and the verb on each answer. */
function wording(q: Pick<Question, 'code' | 'facts'>): { title: string; lines: string[] } {
  const f = q.facts;
  switch (q.code) {
    case 'backup_failed': return { title: "Your saves couldn't be backed up", lines: ['Bayle backs your saves up before every launch, and this time it failed:', ...list(f.failed)] };
    case 'stale_blocked': return { title: "The merged game data can't be rebuilt", lines: [String(f.reason ?? ''), String(f.detail ?? ''), 'You can play anyway, but the game will use the old data.'].filter(Boolean) };
    case 'stale_rebuild': return { title: 'The merged game data is out of date', lines: [String(f.reason ?? ''), 'Rebuilding takes about 40 seconds. Playing now uses the old data.'].filter(Boolean) };
    case 'rebuild_failed': return { title: "The merged game data couldn't be rebuilt", lines: [String(f.message ?? ''), 'You can play anyway with the old data.'].filter(Boolean) };
    case 'online_risk': return { title: 'This setup can get you flagged online', lines: ["Natives and changed game data can be caught by the game's online checks.", 'Playing offline keeps your account safe.'] };
    case 'offline_confirm': return {
      title: 'Play offline?',
      lines: ['The game starts without online play.', ...(f.strip_overhaul ? ["Overhaul files are left out of this run."] : []), ...(f.start_steam ? ['Bayle starts Steam if it is not running.'] : [])],
    };
    default: return { title: 'Play needs an answer', lines: [] };
  }
}

const LABELS: Record<string, string> = {
  retry: 'Try again', without_backup: 'Play without a backup', play_anyway: 'Play anyway', rebuild: 'Rebuild first',
  offline_instead: 'Play offline', online_anyway: 'Play online anyway', go: 'Play offline', cancel: 'Cancel',
};

/** Asks the questions Play raises, wherever the player is, and sends the answer back to the waiting job. */
export function LaunchPrompt() {
  const { gateway } = useRuntime();
  const q = useJobStore((s) => Object.values(s.jobs).find((j) => j.phase === 'running' && j.prompt?.kind === 'question')?.prompt) as Question | undefined;
  const [answered, setAnswered] = useState<string>();
  if (!q || q.prompt_id === answered) return null;
  const answer = (choice: string) => {
    setAnswered(q.prompt_id);
    answerPrompt(gateway, q.prompt_id, choice).catch((e: Error) => toast({ kind: 'error', title: e.message }));
  };
  const w = wording(q);
  const options = q.options.filter((o) => o.key !== 'cancel');
  return (
    <Dialog open onOpenChange={(o) => !o && answer('cancel')} title={w.title} description={w.lines[0]}
      footer={<>
        <Button variant="ghost" onClick={() => answer('cancel')}>Cancel</Button>
        {options.map((o) => <Button key={o.key} variant={o.role === 'primary' ? 'primary' : o.role === 'danger' ? 'danger' : 'default'} onClick={() => answer(o.key)}>{LABELS[o.key] ?? o.key}</Button>)}
      </>}>
      <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-ui text-t2">
        {w.lines.slice(1).map((l) => <li key={l}>{l}</li>)}
      </ul>
    </Dialog>
  );
}
