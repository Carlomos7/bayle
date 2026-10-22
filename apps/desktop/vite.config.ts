import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  clearScreen: false, // keep Rust errors visible under `tauri dev`
  server: {
    port: 1420, // the backend's dev CORS list names this origin (api/settings.py)
    strictPort: true,
    watch: { ignored: ["**/src-tauri/**"] },
  },
  test: { environment: "jsdom" },
});
