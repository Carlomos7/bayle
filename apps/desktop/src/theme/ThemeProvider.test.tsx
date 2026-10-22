import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";
import { AppearanceControls } from "./AppearanceControls";
import { ThemeProvider, useTheme } from "./ThemeProvider";

function Probe() {
  const { logoSrc } = useTheme();
  return <img alt="logo" src={logoSrc} />;
}

function setup() {
  render(
    <ThemeProvider>
      <AppearanceControls />
      <Probe />
    </ThemeProvider>,
  );
  return userEvent.setup();
}

describe("theme", () => {
  test("defaults to the system theme (dark here) and writes it on the root element", () => {
    setup();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  test("switching the theme changes data-theme and is remembered", async () => {
    const user = setup();
    await user.selectOptions(screen.getByLabelText("Theme"), "light");
    expect(document.documentElement.dataset.theme).toBe("light");
    await user.selectOptions(screen.getByLabelText("Theme"), "tarnished");
    expect(document.documentElement.dataset.theme).toBe("tarnished");
    expect(JSON.parse(localStorage.getItem("bayle.appearance")!)).toMatchObject({ theme: "tarnished" });
  });

  test("the logo follows the theme (crimson dark, ice light) unless the setting picks one", async () => {
    const user = setup();
    const src = () => screen.getByAltText("logo").getAttribute("src")!;
    expect(src()).toContain("logo-crimson");
    await user.selectOptions(screen.getByLabelText("Theme"), "light");
    expect(src()).toContain("logo-ice");
    await user.selectOptions(screen.getByLabelText("Logo"), "gold");
    expect(src()).toContain("logo-gold");
  });
});
