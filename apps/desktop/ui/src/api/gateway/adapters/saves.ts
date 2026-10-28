/**
 * The Saves page over the gateway: BayleApi's saves members, answered by the engine's `saves_*` operations
 * (apps/engine/src/bayle/api/routers/saves.py and modules/saves/saves_page.py, which this file's types are read from).
 *
 * Ids: the engine names things by path, so the UI's ids are paths.
 * - SaveId is the live save's file path.
 * - A backup's CopyId is the backup file's path.
 * - A Library copy's CopyId is `lib:<entry_id>:<save folder>` (the engine addresses a copy by folder and entry id;
 *   an entry id is 12 hex characters, so the first two colons split it).
 *
 * Writes follow the engine's pattern: `saves_check_*` gives the facts and a stamp of the files read, the write is
 * called with `expect=stamp` (refused `stale` when a file changed in between). Long writes return a job id; the
 * ActionResult is built from the job's result and undo record, and carries the Activity entry the job made.
 * Quick writes (rename, remove, keep) return no entry: the engine records none.
 */
import { awaitJob } from '@/data/engine';
import type { BayleApi } from '../../BayleApi';
import type { ActivityEntry, SaveCopy, SaveFile, Slot } from '../../types';
import type { Gateway } from '../hub';
import { GatewayError } from '../transport';

/* ------------------------------------------------------------------ engine shapes (dicts the OpenAPI leaves untyped) */

// Operation ids, local so this batch does not edit the shared OPERATIONS table.
const OP = {
  saves: 'saves',
  sheet: 'saves_sheet',
  copyEntry: 'saves_copy_entry',
  saveCopy: 'saves_save_copy',
  renameCopy: 'saves_rename_copy',
  keepBackup: 'saves_keep_backup',
  checkRemoveCopy: 'saves_check_remove_copy',
  removeCopy: 'saves_remove_copy',
  checkDeleteBackup: 'saves_check_delete_backup',
  deleteBackup: 'saves_delete_backup',
  importFiles: 'saves_import_files',
  backUp: 'saves_back_up',
  checkCopyCharacter: 'saves_check_copy_character',
  copyCharacter: 'saves_copy_character',
  checkReplaceFromLibrary: 'saves_check_replace_from_library',
  replaceFromLibrary: 'saves_replace_from_library',
  checkRestoreBackup: 'saves_check_restore_backup',
  restoreBackup: 'saves_restore_backup',
  checkRepair: 'saves_check_repair',
  repair: 'saves_repair',
} as const;

/** (mtime_ns, size) of each file a check read; null: it was not there. Sent back untouched as `expect`. */
type Stamp = ([number, number] | null)[];

/** modules/saves/models.py Character (extra keys allowed). */
interface EngineCharacter { slot: number; name: string; level: number; body?: string; where?: string; runes?: number; ok?: boolean }
interface EngineUnreadable { slot: number; name: string; level: number; error: string }
/** modules/saves/models.py SaveInfo, the parts used here. */
interface EngineSaveInfo {
  path: string;
  name: string;
  kind: string;
  modified: string;
  block: string;
  error: string | null;
  needs_repair: boolean;
  characters: EngineCharacter[];
  unreadable?: EngineUnreadable[];
  checksum_fixes: { slots: number[]; ud10: boolean };
  loading_plan: { slot: number; issues: string[] }[];
}
/** modules/saves/library.py: one entry of a Library manifest (`characters` is library.characters_in). */
interface EngineLibraryEntry {
  id: string;
  name: string;
  from?: string;
  added?: string;
  note?: string;
  size?: number;
  missing?: boolean;
  characters?: { slot: number; name: string; level: number; seconds: number }[];
}
/** modules/saves/service.py list_backups, one row. */
interface EngineBackup { path: string; save_name: string; when: string; action: string; size: number; keep: boolean; mtime: number }
interface SavesFacts { infos: EngineSaveInfo[]; libraries: Record<string, { entries: EngineLibraryEntry[] }>; backups: EngineBackup[] }
/** The job results documented on the routes (saves.py). */
interface WriteResult { file?: string; character?: string; slot?: number; save?: string | null; backup?: string | null; undo?: unknown }

/* ------------------------------------------------------------------ small helpers */

const SLOTS = 10; // Elden Ring; shortcut: Game.slotsPerSave is not reachable from the engine yet, upgrade with the games route.

// shortcut: no engine counterpart yet, upgrade when the engine can do it (same error the adapter gives unwired methods).
const notWired = (what: string) => new GatewayError({ code: 'not_wired', message: `This part of Bayle isn't connected to the engine yet (${what}).` });

const LIB = 'lib:';
const libraryId = (folder: string, entryId: string) => `${LIB}${entryId}:${folder}`;
function parseCopyId(id: string): { library: { entryId: string; folder: string } } | { backup: string } {
  if (!id.startsWith(LIB)) return { backup: id };
  const rest = id.slice(LIB.length);
  const i = rest.indexOf(':');
  return { library: { entryId: rest.slice(0, i), folder: rest.slice(i + 1) } };
}

function bytes(n: number | undefined): string | undefined {
  if (n == null) return undefined;
  return n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/** The engine writes local times as ISO ("2026-10-27T14:02:00") or "2026-10-27 14:02:00". */
function when(s: string | undefined): string {
  if (!s) return '';
  const d = new Date(s.replace(' ', 'T'));
  return Number.isNaN(d.getTime()) ? s : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false });
}

const hours = (seconds: number) => { const h = seconds / 3600; return h < 10 ? `${h.toFixed(1)} h` : `${Math.round(h)} h`; };

function slotsOf(chars: EngineCharacter[], unreadable: EngineUnreadable[] = []): Slot[] {
  return Array.from({ length: SLOTS }, (_, i): Slot => {
    const n = i + 1;
    const c = chars.find((x) => x.slot === n);
    if (c) {
      return {
        n,
        character: { name: c.name, level: c.level, location: c.where, body: c.body, runesHeld: c.runes },
        ...(c.ok === false ? { problem: 'The game may refuse this character. Repair the save to fix it.' } : {}),
      };
    }
    const bad = unreadable.find((x) => x.slot === n);
    return bad ? { n, problem: bad.error } : { n };
  });
}

const toSaveFile = (gameId: string, i: EngineSaveInfo): SaveFile => ({
  id: i.path,
  gameId,
  label: i.name,
  fileName: i.name,
  // shortcut: SaveInfo has no size or "used by profile"; shown empty until the engine reports them.
  size: '',
  health: i.needs_repair ? 'repair' : 'ok',
  source: i.kind,
  sourceDetail: i.error ?? `${i.kind} save, last changed ${when(i.modified)}`,
  usedBy: [],
  slots: slotsOf(i.characters, i.unreadable),
});

/** A Library copy lists its characters in the manifest; library.characters_in numbers slots 1-based. */
const toLibraryCopy = (gameId: string, folder: string, e: EngineLibraryEntry): SaveCopy => ({
  id: libraryId(folder, e.id),
  gameId,
  kind: 'library',
  name: e.name,
  fromFile: e.from,
  note: e.note || 'whole file',
  when: when(e.added),
  size: bytes(e.size),
  missing: !!e.missing,
  slots: (e.characters ?? []).map((c): Slot => ({ n: c.slot, character: { name: c.name, level: c.level, playtime: hours(c.seconds) } })),
});

/* ------------------------------------------------------------------ the adapter */

export function savesApi(gateway: Gateway): Partial<BayleApi> {
  const call = <T>(operation: string, params?: Record<string, unknown>) => gateway.call<T>(operation, params);

  /** Start a job and wait for it. The epoch pins the start to the engine process the job id belongs to. */
  async function runJob(operation: string, params: Record<string, unknown>): Promise<{ result: unknown; entry: ActivityEntry }> {
    const epoch = gateway.current()?.epoch;
    if (epoch === undefined) throw new GatewayError({ code: 'engine_unavailable', message: "Bayle's engine isn't ready." });
    const { job_id } = await gateway.call<{ job_id: string }>(operation, params, { epoch });
    const job = await awaitJob({ epoch, id: job_id });
    const now = new Date();
    const entry: ActivityEntry = {
      id: job.id, gameId: '', kind: 'save', ok: true, title: job.title, detail: '', day: 'Today',
      time: now.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false }),
      duration: '', hasLog: true, undoable: !!job.undo,
    };
    return { result: job.result, entry };
  }

  /** The check, then the write with the stamp the check gave (the engine refuses it as stale if a file moved). */
  async function checked<C extends { stamp: Stamp }>(check: string, write: string, params: Record<string, unknown>) {
    const facts = await call<C>(check, params);
    return { facts, ...(await runJob(write, { ...params, expect: facts.stamp })) };
  }

  /** The engine's Library copy file: a character may be copied out of it. */
  const copyFile = async (folder: string, entryId: string) => (await call<{ path: string }>(OP.copyEntry, { folder, entry_id: entryId })).path;

  const readFacts = () => call<SavesFacts>(OP.saves);

  return {
    async listSaves(gameId) {
      return (await readFacts()).infos.map((i) => toSaveFile(gameId, i));
    },

    async listCopies(gameId) {
      const { libraries, backups } = await readFacts();
      const library = Object.entries(libraries).flatMap(([folder, doc]) => doc.entries.map((e) => toLibraryCopy(gameId, folder, e)));
      // A backup's characters are not in the page's facts: ask the save's sheet, a few at a time (each parses a file).
      // shortcut: one sheet per backup, so a long Backups list is slow to open; upgrade with a lazy per-copy read.
      const sheets: (EngineSaveInfo | undefined)[] = [];
      for (let i = 0; i < backups.length; i += 4) {
        sheets.push(...await Promise.all(backups.slice(i, i + 4).map((b) => call<{ data: EngineSaveInfo }>(OP.sheet, { path: b.path, slot: 1 }).then((r) => r.data, () => undefined))));
      }
      const backup = backups.map((b, i): SaveCopy => ({
        id: b.path,
        gameId,
        kind: 'backup',
        name: when(b.when) || b.save_name,
        fromFile: b.save_name,
        note: b.action,
        when: when(b.when),
        size: bytes(b.size),
        pinned: b.keep,
        slots: sheets[i] ? slotsOf(sheets[i].characters, sheets[i].unreadable).filter((s) => s.character) : [],
      }));
      return [...library, ...backup];
    },

    async repairSave(saveId) {
      // The repairs ticked by default in the old Check & repair page: loading fixes and checksums. The rest stays opt-in.
      const { data: info } = await call<{ data: EngineSaveInfo }>(OP.sheet, { path: saveId, slot: 1 });
      const keys: (string | number)[][] = [
        ...info.loading_plan.flatMap((p) => p.issues.map((k) => ['loading', p.slot, k])),
        ...info.checksum_fixes.slots.map((s) => ['checksum', s]),
        ...(info.checksum_fixes.ud10 ? [['checksum', 'ud10']] : []),
      ];
      if (!keys.length) throw new GatewayError({ code: 'nothing_to_repair', message: `${info.name} has nothing Bayle can repair.` });
      const { entry } = await checked<{ stamp: Stamp }>(OP.checkRepair, OP.repair, { path: saveId, keys });
      return { entry, message: `Repaired ${info.name}`, detail: 'The save was backed up first.' };
    },

    async keepCopy(saveId, name) {
      const { result, entry } = await runJob(OP.saveCopy, { path: saveId, name });
      return { entry, message: `Kept a copy as ${(result as { name: string }).name}` };
    },

    async copyCharacter(from, to) {
      let source: string;
      if ('saveId' in from) source = from.saveId;
      else {
        const id = parseCopyId(from.copyId);
        // shortcut: the engine copies a character only out of a live save or a Library copy, not out of a backup; upgrade with a route that takes a backup.
        if ('backup' in id) throw notWired('copy a character out of a backup');
        source = await copyFile(id.library.folder, id.library.entryId);
      }
      const { result, entry } = await checked<{ stamp: Stamp }>(OP.checkCopyCharacter, OP.copyCharacter, { source, src_slot: from.n, target: to.saveId, dst_slot: to.n });
      const r = result as WriteResult;
      return { entry, message: `${r.character} is in slot ${r.slot} of ${r.file}`, detail: 'The save was backed up first.' };
    },

    // shortcut: the engine has no delete-a-slot operation, upgrade when it gains one.
    async deleteCharacter() { throw notWired('deleteCharacter'); },

    async restoreCopy(copyId, saveId) {
      const id = parseCopyId(copyId);
      // shortcut: the Library's "changed outside Bayle" warning (ReplaceCheck.changed_outside) is not asked; the page's confirm covers the write.
      const { result, entry } = 'backup' in id
        ? await checked<{ stamp: Stamp }>(OP.checkRestoreBackup, OP.restoreBackup, { backup: id.backup, target: saveId })
        : await checked<{ stamp: Stamp }>(OP.checkReplaceFromLibrary, OP.replaceFromLibrary, { folder: id.library.folder, entry_id: id.library.entryId, target: saveId });
      return { entry, message: `Restored ${(result as WriteResult).file}`, detail: 'The save was backed up first.' };
    },

    async renameCopy(copyId, name) {
      const id = parseCopyId(copyId);
      // shortcut: backups are named by their file; only Library copies can be renamed. Upgrade if the engine renames backups.
      if ('backup' in id) throw notWired('rename a backup');
      const { text } = await call<{ text: string }>(OP.renameCopy, { folder: id.library.folder, entry_id: id.library.entryId, name });
      return { message: `Renamed to ${text}` };
    },

    async removeCopy(copyId) {
      const id = parseCopyId(copyId);
      if ('backup' in id) {
        const facts = await call<{ stamp: [number, number]; save_name: string }>(OP.checkDeleteBackup, { backup: id.backup });
        await call(OP.deleteBackup, { backup: id.backup, expect: facts.stamp });
        return { message: `Removed the backup of ${facts.save_name}` };
      }
      const ref = { folder: id.library.folder, entry_id: id.library.entryId };
      const { text } = await call<{ text: string }>(OP.checkRemoveCopy, ref);
      await call(OP.removeCopy, { ...ref, expect: text });
      return { message: `Removed ${text}` };
    },

    async pinBackup(copyId, pinned) {
      const id = parseCopyId(copyId);
      if (!('backup' in id)) throw new GatewayError({ code: 'invalid_params', message: 'Only a backup can be kept forever.' });
      await call(OP.keepBackup, { backup: id.backup, keep: pinned });
      return { message: pinned ? 'Kept forever' : 'It will rotate out with the others' };
    },

    async importSave(_gameId, path) {
      const { result, entry } = await runJob(OP.importFiles, { files: [path] });
      const r = result as { imported: { name: string }[]; failed: { file: string; code: string }[] };
      return { entry, message: `Imported ${r.imported.map((i) => i.name).join(', ')}`, ...(r.failed.length ? { detail: `${r.failed.length} file${r.failed.length === 1 ? '' : 's'} could not be imported.` } : {}) };
    },

    async backupNow() {
      const { result, entry } = await runJob(OP.backUp, { everything: true });
      const n = (result as { backups: string[] }).backups.length;
      return { entry, message: `Backed up ${n} save${n === 1 ? '' : 's'}` };
    },
  };
}
