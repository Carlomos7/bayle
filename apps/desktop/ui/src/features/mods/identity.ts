import type { Mod, Profile } from '@/api';

/**
 * How a mod is named and what it is made of. A DLL is shown by the name
 * people call it (Seamless Co-op), with its file (ersc.dll) beside it, and
 * the UI always says where that name came from, because it can be wrong.
 */

/** The DLL's file name: ersc.dll. Natives only. */
export const dllFile = (m: Mod) => (m.kind === 'native' ? m.file ?? m.folder.split(/[\\/]/).pop() ?? m.folder : undefined);

/** True when the row's name says nothing the file name doesn't: show the file once, not twice. */
export const namedByFile = (m: Mod) => m.kind === 'native' && (m.nameSource === 'file' || m.name === dllFile(m));

/** The package mod a DLL came with. */
export const ownerOf = (m: Mod, p: Profile) => (m.partOfModId ? p.mods.find((x) => x.id === m.partOfModId) : undefined);

/** The DLLs that came with a package mod. */
export const dllsOf = (m: Mod, p: Profile) => p.mods.filter((x) => x.kind === 'native' && x.partOfModId === m.id);

/** The name a thumbnail is drawn from, so a mod's DLL wears the mod's colours. */
export const thumbName = (m: Mod, p: Profile) => ownerOf(m, p)?.name ?? m.name.replace(/\.(dll|exe)$/i, '');

/** Where a name came from, as one sentence. */
export function nameSourceText(m: Mod, p: Profile): string {
  const owner = ownerOf(m, p);
  switch (m.nameSource) {
    case 'install': return owner ? `Named after ${owner.name}, which it came with.` : 'Named after the download it came in.';
    case 'file-details': return "Named from the DLL's own file details.";
    case 'known': return 'Bayle recognizes this DLL.';
    case 'you': return 'You named it.';
    case 'file': return 'No name found, so its file name.';
    default: return '';
  }
}

/** A DLL named for a sentence: "Elden Mod Loader (EldenModLoader.dll)", or just the file when that is all there is. */
export const dllLabel = (m: Mod) => (m.kind !== 'native' || namedByFile(m) ? m.name : `${m.name} (${dllFile(m)})`);

/** Text a search should match: the name, and for a DLL its file and the mod it belongs to. */
export const searchText = (m: Mod, p: Profile) => [m.name, dllFile(m), ownerOf(m, p)?.name, m.packageId].filter(Boolean).join(' ').toLowerCase();
