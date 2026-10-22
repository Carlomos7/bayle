import { createContext, use, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import crimson from "@/assets/logo-crimson.png";
import gold from "@/assets/logo-gold.png";
import ice from "@/assets/logo-ice.png";

/** "system" follows the OS; tarnished is the olive dark variant. Same names as the Qt app's settings. */
export type ThemeSetting = "system" | "dark" | "light" | "tarnished";
export type Theme = Exclude<ThemeSetting, "system">;
/** "auto" = crimson on dark, ice on light. */
export type LogoSetting = "auto" | "crimson" | "ice" | "gold";

const LOGOS = { crimson, ice, gold };
const KEY = "bayle.appearance";

interface Stored {
  theme: ThemeSetting;
  logo: LogoSetting;
}

function load(): Stored {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Stored>;
    return { theme: raw.theme ?? "system", logo: raw.logo ?? "auto" };
  } catch {
    return { theme: "system", logo: "auto" };
  }
}

const dark = () => window.matchMedia("(prefers-color-scheme: dark)");

interface Ctx extends Stored {
  /** The theme in effect (system resolved). */
  resolved: Theme;
  logoSrc: string;
  setTheme(t: ThemeSetting): void;
  setLogo(l: LogoSetting): void;
}

const ThemeContext = createContext<Ctx | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [stored, setStored] = useState(load);
  const [systemDark, setSystemDark] = useState(() => dark().matches);

  useEffect(() => {
    const mq = dark();
    const on = () => setSystemDark(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  const resolved: Theme = stored.theme === "system" ? (systemDark ? "dark" : "light") : stored.theme;
  useEffect(() => {
    document.documentElement.dataset.theme = resolved;
  }, [resolved]);

  const save = useCallback((next: Stored) => {
    setStored(next);
    try {
      localStorage.setItem(KEY, JSON.stringify(next));
    } catch {
      // storage blocked: the choice lasts until restart
    }
  }, []);

  const value = useMemo<Ctx>(() => {
    const kind = stored.logo === "auto" ? (resolved === "light" ? "ice" : "crimson") : stored.logo;
    return {
      ...stored,
      resolved,
      logoSrc: LOGOS[kind],
      setTheme: (theme) => save({ ...stored, theme }),
      setLogo: (logo) => save({ ...stored, logo }),
    };
  }, [stored, resolved, save]);

  return <ThemeContext value={value}>{children}</ThemeContext>;
}

export function useTheme(): Ctx {
  const ctx = use(ThemeContext);
  if (!ctx) throw new Error("useTheme outside ThemeProvider");
  return ctx;
}
