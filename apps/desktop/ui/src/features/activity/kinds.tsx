import type { ReactNode } from 'react';
import { Download, Layers, Merge, Play, Save } from 'lucide-react';
import type { ActivityKind } from '@/api';

/** Label, icon and tint for each kind of entry. Shared by the toolbar, tiles and timeline. */
export const KIND: Record<ActivityKind, { label: string; icon: ReactNode; tint: string }> = {
  launch: { label: 'Launches', icon: <Play />, tint: 'bg-accent-soft text-accent' },
  install: { label: 'Installs', icon: <Download />, tint: 'bg-info-bg text-info' },
  rebuild: { label: 'Rebuilds', icon: <Merge />, tint: 'bg-vio-bg text-vio' },
  save: { label: 'Saves', icon: <Save />, tint: 'bg-ok-bg text-ok' },
  profile: { label: 'Profiles', icon: <Layers />, tint: 'bg-t1/7 text-t2' },
};

export const KIND_ORDER: ActivityKind[] = ['launch', 'install', 'rebuild', 'save', 'profile'];
