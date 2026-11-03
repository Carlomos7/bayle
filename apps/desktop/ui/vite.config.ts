import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { tanstackRouter } from '@tanstack/router-plugin/vite';
import { fileURLToPath, URL } from 'node:url';

// base: './' so the built app works from file:// or inside a desktop webview.
export default defineConfig(({ mode, command }) => {
  // Desktop builds swap the browser preview (mock engine + made-up data) for an empty stub,
  // so it can't ship in the app. Dev, tests and `--mode demo` keep the real preview.
  const preview = command === 'serve' || mode === 'test' || loadEnv(mode, process.cwd(), 'VITE_').VITE_BAYLE_DEMO === '1';
  const src = fileURLToPath(new URL('./src', import.meta.url));
  return {
    base: './',
    plugins: [
      // Must come before react(): generates src/routeTree.gen.ts and code-splits each route.
      tanstackRouter({ target: 'react', autoCodeSplitting: true }),
      react(),
      tailwindcss(),
    ],
    resolve: {
      alias: [
        { find: /^@\/api\/preview$/, replacement: `${src}/api/${preview ? 'preview' : 'preview.disabled'}.ts` },
        { find: '@', replacement: src },
      ],
    },
    server: { port: 5173 },
    build: {
      // Libraries change less often than app code, so they get their own cached chunks.
      rolldownOptions: {
        output: {
          codeSplitting: {
            groups: [
              { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/, priority: 3 },
              { name: 'ui', test: /node_modules[\\/](radix-ui|@radix-ui|cmdk|sonner|lucide-react|@floating-ui)/, priority: 2 },
              { name: 'vendor', test: /node_modules/, priority: 1 },
            ],
          },
        },
      },
    },
  };
});
