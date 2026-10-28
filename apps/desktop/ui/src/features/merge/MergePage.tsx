import { useEffect, useRef, useState } from 'react';
import { useNavigate, useSearch } from '@tanstack/react-router';
import type { Clash, FileFamily } from '@/api';
import { useBuild, useCurrent } from '@/data/hooks';
import { useGo } from '@/app/nav';
import { EmptyState, Page, PageHeader } from '@/components/bayle/layout';
import { Advanced } from '@/components/bayle/advanced';
import { FirstVisit } from '@/components/bayle/first-visit';
import { Board, type BoardFilter } from './Board';
import { Overlaps } from './Overlaps';
import { PieceSearch } from './PieceSearch';
import { RuleDialog } from './RuleDialog';
import { SuggestWinnersDialog } from './SuggestWinnersDialog';
import { Survival } from './Survival';
import { needsCount } from './explain';
import { NeedsYou } from './NeedsYou';
import { NotMerged } from './NotMerged';
import { AllSorted, RebuildDock } from './RebuildDock';
import { RulesList } from './RulesList';
import { StatusLine } from './StatusLine';
import { PlanDialog, ReportSheet, StatusTools } from './Status';

/**
 * Merge, in the order a player asks: is it built, does anything need me,
 * where do my mods overlap and who wins, what can't be merged, and "find the
 * thing that looks wrong". The board, plan and report sit under Advanced.
 * Decisions are suggestions until rebuilt; the bar at the bottom says what
 * rebuilding would change.
 */
export function MergePage() {
  const { game, profile, loading } = useCurrent();
  const build = useBuild(profile?.id);
  const go = useGo();
  const navigate = useNavigate();
  const search = useSearch({ from: '/merge' });
  const filter: BoardFilter = { modId: search.mod, family: search.family as FileFamily | undefined };
  const setFilter = (f: BoardFilter) => void navigate({ to: '/merge', search: { mod: f.modId, family: f.family }, replace: true });
  const [plan, setPlan] = useState(false);
  const [report, setReport] = useState(false);
  const [suggest, setSuggest] = useState(false);
  const [openKind, setOpenKind] = useState<FileFamily | undefined>(search.family as FileFamily | undefined);
  const [openPiece, setOpenPiece] = useState<string>();
  const [ruleFor, setRuleFor] = useState<FileFamily>();
  // The open Needs you item, and where it sat, so settling one moves on to the next.
  const [need, setNeed] = useState<{ id?: string; at?: number }>({});
  const scrollTarget = useRef<string | undefined>(undefined);
  const setScrollTo = (id: string) => { scrollTarget.current = id; };

  // Bring an opened piece or kind into view once it has rendered.
  useEffect(() => {
    const id = scrollTarget.current;
    if (!id) return;
    scrollTarget.current = undefined;
    document.querySelector(`[data-piece="${id}"], [data-kind="${id}"]`)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [openPiece, openKind]);

  if (!game || !profile) {
    if (loading) return <Page><PageHeader eyebrow="Merge" title="Loading…" /></Page>;
    return <Page><PageHeader eyebrow="Merge" title="Merge" /><EmptyState title="No profile for this game yet">Create one from the profile menu in the top bar, then come back to see how its mods merge.</EmptyState></Page>;
  }
  const b = build.data;
  // The engine merges in load order only: nothing here offers a pick, a rule, a suggestion or a search that could not work.
  const choices = b?.choices !== false;
  const openClash = (c: Clash) => {
    // A whole-file kind coupled to a rule shows inside that rule's row.
    const host = b?.rules.find((r) => !r.dormant && r.coupled?.includes(c.family))?.family;
    const ownRow = b?.clashes.some((x) => x.family === c.family && !x.unsupported);
    setOpenKind(ownRow ? c.family : host ?? c.family); setOpenPiece(c.id); setScrollTo(c.id);
  };

  const showKind = (f: FileFamily) => { setOpenKind(f); setOpenPiece(undefined); setScrollTo(f); };

  return (
    <Page className={b && (b.state === 'stale' || b.pending.length) ? 'pb-6' : undefined}>
      <PageHeader eyebrow={<>Merge · {game.name}</>} title={profile.name} subtitle="Where your mods change the same things, and who wins." />
      {build.isError ? <EmptyState title="Merge can't be shown yet.">{(build.error as Error).message}</EmptyState>
        : !b ? <div className="py-10 text-center text-ui text-t3">Reading the build…</div>
        : b.state === 'none' ? (
          <EmptyState title="Nothing to merge. That's good.">
            None of your mods change the same file, so there is nothing that could fight. When two do, this page shows who wins and lets you change it.
          </EmptyState>
        ) : (
          <>
            <StatusLine build={b} />
            <NeedsYou profile={profile} build={b} openId={need.id} openAt={need.at} onOpen={(id, at) => setNeed({ id, at })} onChangeRule={setRuleFor} onShowKind={showKind} />
            <AllSorted build={b} />
            {needsCount(b) === 0 && (
              <FirstVisit tipKey="merge" title="You rarely need this page">
                Bayle combines your mods on its own and Launch redoes it when something changes. Come here when something looks wrong in game, or when the chip next to Launch sends you.
              </FirstVisit>
            )}
            {choices && <PieceSearch profile={profile} onOpenMod={go.openMod} onOpenClash={(id) => { const c = b.clashes.find((x) => x.id === id); if (c) openClash(c); }} />}
            <Overlaps profile={profile} build={b} openKind={openKind} openPiece={openPiece} onOpenKind={setOpenKind} onOpenPiece={setOpenPiece} onChangeRule={setRuleFor} />
            {choices && <Survival profile={profile} build={b} onOpenMod={go.openMod} onSuggest={() => setSuggest(true)} />}
            <NotMerged profile={profile} build={b} />
            {choices && <RulesList profile={profile} build={b} onOpenPiece={openClash} />}
            <Advanced id="advanced" label="the load-order board, what a rebuild would do, the full report" defaultOpen={!!(search.mod || search.family)}>
              <StatusTools onPlan={() => setPlan(true)} onReport={() => setReport(true)} />
              <Board profile={profile} build={b} filter={filter} onFilter={setFilter} onOpenMod={go.openMod} />
            </Advanced>
            <RebuildDock profile={profile} build={b} />
            {choices && ruleFor && <RuleDialog key={ruleFor} profile={profile} build={b} family={ruleFor} open onOpenChange={(o) => !o && setRuleFor(undefined)} />}
            <PlanDialog profile={profile} open={plan} onOpenChange={setPlan} />
            {choices && <SuggestWinnersDialog profile={profile} open={suggest} onOpenChange={setSuggest} />}
            <ReportSheet build={b} open={report} onOpenChange={setReport} />
          </>
        )}
    </Page>
  );
}
