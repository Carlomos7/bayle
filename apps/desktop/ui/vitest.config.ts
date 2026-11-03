import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config.ts';

// Unit tests for the integration layer: job ordering, engine lifecycle, the gateway hub, the security boundary.
export default defineConfig((env) => mergeConfig(viteConfig(env), {
  test: {
    include: ['src/**/*.test.{ts,tsx}'],
    environment: 'node',
    restoreMocks: true,
  },
}));
