/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * "1" builds a browser demo that runs on the in-memory mock engine and says so on screen.
   * Leave it unset for the desktop app: inside Tauri the real gateway is always used.
   */
  readonly VITE_BAYLE_DEMO?: '1';
}
interface ImportMeta { readonly env: ImportMetaEnv }
