import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "./App";

vi.mock("@tauri-apps/api/app", () => ({ getVersion: () => Promise.resolve("0.0.0") }));
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  getBackend: () =>
    Promise.resolve({ base_url: "http://127.0.0.1:5", token: "t", app_version: "9", contract_version: "1" }),
}));

afterEach(() => vi.unstubAllGlobals());

test("shows engine health and versions", async () => {
  const health = '{"app_version":"4.6.0","contract_version":"1","ready":true}';
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(health)));
  render(<App />);
  expect(await screen.findByText("Engine: ready")).toBeTruthy();
  expect(screen.getByText("Engine version: 4.6.0")).toBeTruthy();
  expect(screen.getByText("Shell version: 0.0.0")).toBeTruthy();
});
