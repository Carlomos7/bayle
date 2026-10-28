import type { BuildChange, FileFamily, Outcome } from '@/api';

/** File families in the words a player uses, not the formats. */
export const FAMILY: Record<FileFamily, { label: string; hint: string }> = {
  params: { label: 'Balance', hint: 'regulation.bin: damage, weights, prices, stats. Merged field by field.' },
  text: { label: 'Text', hint: 'Menu and item text. Merged line by line.' },
  animations: { label: 'Animations', hint: 'Movesets. Merged one animation at a time.' },
  behaviour: { label: 'Behaviour', hint: 'Behaviour graphs. Not merged: the later mod\'s file is used whole, which says nothing about compatibility.' },
  scripts: { label: 'Scripts', hint: 'Player and talk scripts. A recipe\'s hook is appended and checked to compile, not tested in game; talk menus merge state by state.' },
  textures: { label: 'Textures', hint: 'Not merged inside a file: the later mod\'s copy is used whole.' },
  other: { label: 'Other', hint: 'Models, sounds, maps. The later mod\'s copy is used whole.' },
};

export const OUTCOME: Record<Outcome, { label: string; chip: string; hint: string; weight: number }> = {
  merged: { label: 'Merged', chip: 'bg-ok-bg text-ok', hint: 'Kept together with the other mods\' changes.', weight: 0 },
  won: { label: 'Won', chip: 'bg-t1/7 text-t2', hint: 'This mod\'s copy is used; the other mod\'s change is not.', weight: 1 },
  picked: { label: 'Your pick', chip: 'bg-accent-soft text-accent', hint: 'You chose this mod for the clash.', weight: 2 },
  lost: { label: 'Lost', chip: 'bg-warn-bg text-warn', hint: 'Another mod loads later and wins this piece.', weight: 3 },
  dropped: { label: 'Dropped', chip: 'bg-bad-bg text-bad', hint: 'Bayle could not carry this change into the build.', weight: 4 },
  unsupported: { label: 'Whole file', chip: 'bg-vio-bg text-vio', hint: 'This kind of file cannot be merged, so one mod\'s copy is used whole. Says nothing about whether they are compatible.', weight: 2.5 },
  unknown: { label: 'Not checked', chip: 'bg-t1/5 text-t3', hint: 'Bayle has no evidence either way for this piece.', weight: 1.5 },
};

export const CHANGE_ICON: Record<BuildChange['kind'], string> = {
  'mod-updated': 'update', 'game-updated': 'game', reordered: 'order', toggled: 'toggle', 'setup-changed': 'setup', 'pick-changed': 'pick', added: 'add', removed: 'remove',
};

export const fmt = (n: number) => n.toLocaleString();
