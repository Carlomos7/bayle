import { useState } from 'react';
import { CheckCircle2, Download, FolderOpen, Package, Search } from 'lucide-react';
import { useDialogs } from '@/state/dialogs';
import { useUi } from '@/state/ui';
import { useAppInfo, useCall, useGames, useSettings } from '@/data/hooks';
import { Dialog } from '@/components/bayle/overlay';
import { Button } from '@/components/ui/button';
import { Wordmark } from '@/components/bayle/layout';
import { toast } from '@/state/toasts';
import { cn } from '@/lib/utils';

/**
 * First run: three short screens, each one question, all skippable.
 * 1 Where is the game  2 me3  3 What do you want to do first.
 * Ends on Mods. Reopen it any time from Help › Welcome tour.
 */
export function Welcome() {
  const open = useDialogs((s) => s.open?.id === 'welcome');
  const close = useDialogs((s) => s.close);
  const show = useDialogs((s) => s.show);
  const setOnboarded = useUi((s) => s.setOnboarded);
  const games = useGames();
  const settings = useSettings();
  const info = useAppInfo();
  const call = useCall();
  const [step, setStep] = useState(0);
  const supported = (games.data ?? []).filter((g) => g.supported);
  const folderOf = (id: string) => settings.data?.paths.games[id];

  const finish = (then?: () => void) => { setOnboarded(true); close(); setStep(0); then?.(); };
  // The engine wants the game's program, not its folder.
  const pickGame = async (gameId: string, name: string) => {
    const p = await call((a) => a.pickFile({ title: `Where is ${name} installed?`, filters: [{ name: 'Game program', extensions: ['exe'] }] }));
    if (p) await call((a) => a.updateSettings({ paths: { games: { [gameId]: p } } } as never), { title: `${name} folder set` });
  };

  const steps = [
    {
      title: 'Where are your games?',
      body: (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {supported.map((g) => {
            const f = folderOf(g.id);
            return (
              <li key={g.id} className="flex items-center gap-3 rounded-lg border border-line2 bg-panel px-4 py-3">
                {f ? <CheckCircle2 className="size-4 shrink-0 text-ok" /> : <FolderOpen className="size-4 shrink-0 text-warn" />}
                <div className="min-w-0 flex-1">
                  <div className="text-body font-medium">{g.name}{f ? ' found' : ''}</div>
                  <div className="truncate font-mono text-xs text-t3">{f ?? 'Not found. Pick the game\'s .exe.'}</div>
                </div>
                <Button size="sm" variant="ghost" onClick={() => void pickGame(g.id, g.name)}>{f ? 'Change' : 'Pick game'}</Button>
              </li>
            );
          })}
        </ul>
      ),
      note: 'Bayle looked in the usual Steam folders. Nothing in the game folder is changed by this.',
    },
    {
      title: 'The mod loader',
      body: (
        <div className="flex items-center gap-3 rounded-lg border border-line2 bg-panel px-4 py-3">
          <CheckCircle2 className="size-4 shrink-0 text-ok" />
          <div className="min-w-0 flex-1">
            <div className="text-body font-medium">me3 {info.data?.me3Version ?? ''} is installed</div>
            <div className="text-xs text-t3">It starts the game with your mods, without touching the game's own files. Bayle keeps it up to date.</div>
          </div>
        </div>
      ),
      note: 'If it were missing, Bayle would install it here. Nothing else is needed.',
    },
    {
      title: 'What first?',
      body: (
        <div className="grid grid-cols-3 gap-3 max-[640px]:grid-cols-1">
          {[
            { icon: <Download />, title: 'Add a mod', hint: 'From a download: a .zip, .7z, .rar, a .dll or a folder.', run: () => finish(() => show({ id: 'install' })) },
            { icon: <Package />, title: 'Import a modpack', hint: 'A recipe someone shared. Everything in it is set up for you.', run: () => finish(() => toast({ kind: 'info', title: 'Import a modpack', detail: 'Pick a .bayle-pack file. Coming with the modpack feature.' })) },
            { icon: <Search />, title: 'Just look around', hint: 'Start on Mods with an empty profile. Add things when you like.', run: () => finish() },
          ].map((c) => (
            <button key={c.title} type="button" onClick={c.run} className="flex flex-col items-start gap-2 rounded-lg border border-line2 bg-panel p-4 text-left transition-colors hover:border-t4 hover:bg-hover">
              <span className="text-accent [&_svg]:size-5">{c.icon}</span>
              <b className="font-semibold">{c.title}</b>
              <span className="text-xs leading-snug text-t3">{c.hint}</span>
            </button>
          ))}
        </div>
      ),
      note: 'Whatever you pick, everything Bayle does can be undone from Activity.',
    },
  ];
  const s = steps[step]!;
  const last = step === steps.length - 1;

  return (
    <Dialog open={open} onOpenChange={(o) => !o && finish()} width={640} header={<Wordmark className="mb-3" />}
      title={<span className="flex items-center gap-3">{s.title}<span className="text-xs font-normal text-t4">{step + 1} of {steps.length}</span></span>}
      description={step === 0 ? 'Three quick questions and you are in. You can skip any of them.' : undefined}
      footer={<>
        <Button variant="ghost" className="mr-auto" onClick={() => finish()}>Skip</Button>
        {step > 0 && <Button variant="ghost" onClick={() => setStep(step - 1)}>Back</Button>}
        {!last && <Button variant="primary" onClick={() => setStep(step + 1)}>Next</Button>}
      </>}>
      <div className="flex flex-col gap-3">
        <div className="flex gap-1" aria-hidden>{steps.map((_, i) => <span key={i} className={cn('h-1 flex-1 rounded-full', i <= step ? 'bg-accent' : 'bg-line2')} />)}</div>
        {s.body}
        <p className="m-0 text-xs text-t3">{s.note}</p>
      </div>
    </Dialog>
  );
}

const WORDS: { word: string; means: string }[] = [
  { word: 'Profile', means: 'One set of mods, in order. It can have its own standard save (.sl2); Seamless Co-op saves (.co2) are shared between profiles. Launch runs the active one.' },
  { word: 'Package', means: 'A mod made of game files. me3 lays its files over the game\'s own.' },
  { word: 'Native', means: 'A mod that is a program (a .dll). It runs inside the game. These are the ones a game update can break.' },
  { word: 'Recipe', means: 'How Bayle installs a mod: which files go where and what gets merged. Most mods come with one or Bayle writes it.' },
  { word: 'Merge', means: 'When two mods change the same file, Bayle combines both sets of changes instead of keeping only one.' },
  { word: 'Clash', means: 'Two mods changed the exact same thing. One has to win. The later mod wins unless you pick.' },
  { word: 'Loads last', means: 'A big mod built on top of everything above it, so it has to be at the bottom of the list.' },
  { word: 'Rebuild', means: 'Redo the merge after something changed. Launch does it for you.' },
];

/** The eight words Bayle uses, in plain language. Help › Words Bayle uses. */
export function Glossary() {
  const open = useDialogs((s) => s.open?.id === 'glossary');
  const close = useDialogs((s) => s.close);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && close()} width={560} title="Words Bayle uses" description="Eight words. Everything else is plain English."
      footer={<Button onClick={close}>Close</Button>}>
      <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-5 gap-y-2.5 text-ui">
        {WORDS.map((w) => <div key={w.word} className="contents"><dt className="font-semibold">{w.word}</dt><dd className="m-0 text-t2">{w.means}</dd></div>)}
      </dl>
    </Dialog>
  );
}
