/**
 * Stands in for preview.ts in desktop builds (see vite.config.ts): there is no
 * mock to fall back to. createRuntime never calls this outside dev or a demo
 * build; if it ever did, it fails loudly instead of showing made-up data.
 */
import type { Runtime } from './index';

export function createPreviewRuntime(): Runtime {
  throw new Error('This build has no preview engine. Open Bayle from its desktop app.');
}
