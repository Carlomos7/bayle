import { useState } from 'react';
import type { OverhaulSetup } from '@/api';
import { useAction, useCurrent, useSetup, useSetupUsers } from '@/data/hooks';
import { Sheet, ConfirmDialog } from '@/components/bayle/overlay';
import { Button } from '@/components/ui/button';
import { Tag } from '@/components/bayle/badge';
import { cn, plural } from '@/lib/utils';
import { fromDraft, sameSetup, toDraft, type Draft } from './actions';
import { FilesStep } from './FilesStep';
import { DllStep } from './DllStep';
import { ReviewStep } from './ReviewStep';

const STEPS = ['Plan', 'Natives', 'Advanced'] as const;

export interface OverhaulSheetProps {
  setupId: string;
  profileId: string;
  /** edit: change the saved setup every profile follows; install: add it to profileId. */
  mode: 'edit' | 'install';
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Plan, Natives, Advanced: three views of the same setup, not a sequence. Install works from any of them. */
function Steps({ step, onStep }: { step: number; onStep: (i: number) => void }) {
  return (
    <div role="tablist" aria-label="Setup views" className="flex items-center gap-0.5 rounded-sm border border-line p-0.5 max-[700px]:hidden">
      {STEPS.map((s, i) => (
        <button key={s} type="button" role="tab" aria-selected={i === step} onClick={() => onStep(i)}
          className={cn('h-6 rounded-xs px-2.5 text-xs transition-colors', i === step ? 'bg-t1/10 font-semibold text-t1' : 'text-t3 hover:bg-hover hover:text-t1')}>
          {s}
        </button>
      ))}
    </div>
  );
}

/** How Bayle installs an overhaul: the plan first, its natives to confirm, and the file-by-file recipe under Advanced. */
export function OverhaulSheet({ setupId, profileId, mode, open, onOpenChange }: OverhaulSheetProps) {
  const setup = useSetup(open ? setupId : undefined);
  const users = useSetupUsers(open && mode === 'edit' ? setupId : undefined);
  const { profile } = useCurrent();
  const { run, pending } = useAction();
  const [session, setSession] = useState<{ base: OverhaulSetup | null; open: boolean; draft: Draft | null; step: number }>({ base: null, open: false, draft: null, step: 0 });
  const [confirmClose, setConfirmClose] = useState(false);

  // Start a fresh draft each time the sheet opens, or when the saved setup reloads.
  if (open && setup.data && (session.base !== setup.data || !session.open)) {
    setSession({ base: setup.data, open: true, draft: toDraft(setup.data), step: 0 });
  } else if (!open && session.open) {
    setSession({ base: null, open: false, draft: null, step: 0 });
  }
  const { draft, step } = session;
  const setDraft = (d: Draft) => setSession((s) => ({ ...s, draft: d }));
  const setStep = (n: number) => setSession((s) => ({ ...s, step: n }));

  const dirty = !!draft && !!setup.data && !sameSetup(setup.data, draft);
  const liveUsers = (users.data ?? []).filter((u) => !u.running);
  const neededOut = draft?.files.filter((f) => f.needed && f.action === 'leave').length ?? 0;
  const blocked = mode === 'install' && draft?.recipe?.check === 'mismatch';

  const requestClose = (o: boolean) => {
    if (!o && dirty && mode === 'edit') { setConfirmClose(true); return; }
    onOpenChange(o);
  };

  const finish = async () => {
    if (!draft) return;
    const s = fromDraft(draft);
    const r = mode === 'install' ? await run((a) => a.installOverhaul(profileId, s)) : await run((a) => a.saveSetup(s));
    if (r) onOpenChange(false);
  };

  const primary = mode === 'install' ? 'Install' : liveUsers.length ? `Save to ${plural(liveUsers.length, 'profile')}` : 'Save setup';
  const title = draft ? `${mode === 'install' ? 'Install' : 'Set up'} ${draft.name}` : 'Overhaul setup';
  const subtitle = draft ? `${draft.version}${draft.savedOn ? ` · saved ${draft.savedOn}` : ' · not saved yet'}${mode === 'install' ? ` · into ${profile?.name ?? 'this profile'}` : ''}` : 'Loading…';

  return (
    <>
      <Sheet open={open} onOpenChange={requestClose} width={780} title={title} subtitle={subtitle} headerExtra={<Steps step={step} onStep={setStep} />}
        footer={draft && (
          <>
            {dirty && mode === 'edit' && <Tag tone="accent" className="mr-1">Changed</Tag>}
            {neededOut > 0 && <span className="text-xs text-warn">{plural(neededOut, 'needed file')} left out</span>}
            <span className="flex-1" />
            {step > 0 && <Button variant="ghost" onClick={() => setStep(step - 1)}>Back</Button>}
            {step < STEPS.length - 1 && <Button variant="ghost" onClick={() => setStep(step + 1)}>{step === 0 ? 'Check natives' : 'Advanced: files'}</Button>}
            <Button variant="primary" disabled={pending || blocked || (mode === 'edit' && !dirty)} title={blocked ? `The download is not ${draft.name} ${draft.recipe?.forVersion}` : mode === 'edit' && !dirty ? 'Change something to save' : undefined} onClick={() => void finish()}>{primary}</Button>
          </>
        )}>
        {setup.isError && <p className="text-bad">{(setup.error as Error).message}</p>}
        {!draft ? <p className="text-t3">Loading the setup…</p>
          : step === 0 ? <ReviewStep draft={draft} mode={mode} profileName={profile?.name} users={users.data ?? []} />
          : step === 1 ? <DllStep draft={draft} onChange={setDraft} />
          : <FilesStep draft={draft} onChange={setDraft} />}
      </Sheet>
      <ConfirmDialog open={confirmClose} onOpenChange={setConfirmClose} title="Close without saving?" danger confirmLabel="Discard changes"
        description="Your changes to this setup are not saved. Every profile keeps the setup it has now."
        onConfirm={() => onOpenChange(false)} />
    </>
  );
}
