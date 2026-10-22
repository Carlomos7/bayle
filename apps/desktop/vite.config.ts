import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  clearScreen: false, // keep Rust errors visible under `tauri dev`
  server: {
    port: 1420, // the backend's dev CORS list names this origin (api/settings.py)
    strictPort: true,
    watch: { ignored: ["**/src-tauri/**"] },
  },
  // Tailwind v4 needs Chrome 111 / Safari 16.4 (WebView2, WebKitGTK on the Steam Deck); Tauri's template says safari13
  build: { target: process.env.TAURI_ENV_PLATFORM === "windows" ? "chrome111" : "safari16.4" },
  test: { environment: "jsdom", setupFiles: ["./src/test/setup.ts"] },
});
