import type { Modifier } from '@dnd-kit/core';

/** Rows only move up and down. (Local copy so we don't need @dnd-kit/modifiers.) */
export const restrictToVerticalAxis: Modifier = ({ transform }) => ({ ...transform, x: 0 });
