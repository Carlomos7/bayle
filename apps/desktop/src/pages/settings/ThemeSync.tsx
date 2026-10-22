import { useEffect } from "react";
import { useTheme, type LogoSetting, type ThemeSetting } from "@/theme/ThemeProvider";
import { useSettingsState } from "./useSettings";

/** Applies the saved theme and logo (settings.set owns them) to the ThemeProvider, on start and after any change. */
export function ThemeSync() {
  const { data } = useSettingsState();
  const { theme, logo, setTheme, setLogo } = useTheme();
  const savedTheme = data?.theme as ThemeSetting | undefined;
  const savedLogo = data?.logo as LogoSetting | undefined;
  useEffect(() => {
    if (savedTheme && savedTheme !== theme) setTheme(savedTheme);
    if (savedLogo && savedLogo !== logo) setLogo(savedLogo);
    // only a newly saved value matters: the provider's own value changes first when the user picks one
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [savedTheme, savedLogo]);
  return null;
}
