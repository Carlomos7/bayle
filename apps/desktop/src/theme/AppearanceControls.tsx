import { useId } from "react";
import { useTheme, type LogoSetting, type ThemeSetting } from "./ThemeProvider";

const THEMES: [ThemeSetting, string][] = [
  ["system", "Follows system"],
  ["dark", "Dark"],
  ["light", "Light"],
  ["tarnished", "Tarnished"],
];
const LOGOS: [LogoSetting, string][] = [
  ["auto", "Follows theme"],
  ["crimson", "Crimson"],
  ["ice", "Ice"],
  ["gold", "Tarnished (gold)"],
];

const select =
  "h-[var(--control-h)] rounded-control border border-border-edge bg-surface-input px-2 text-body text-text-primary";

export function AppearanceControls() {
  const { theme, logo, setTheme, setLogo } = useTheme();
  const themeId = useId();
  const logoId = useId();
  return (
    <div className="flex flex-wrap gap-6">
      <div className="flex flex-col gap-1">
        <label htmlFor={themeId} className="text-caption text-text-secondary">
          Theme
        </label>
        <select id={themeId} className={select} value={theme} onChange={(e) => setTheme(e.target.value as ThemeSetting)}>
          {THEMES.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor={logoId} className="text-caption text-text-secondary">
          Logo
        </label>
        <select id={logoId} className={select} value={logo} onChange={(e) => setLogo(e.target.value as LogoSetting)}>
          {LOGOS.map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
