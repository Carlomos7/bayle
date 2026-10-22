import { createMemoryHistory } from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import { AppWithBackend } from "./App";
import { buildRouter } from "./router";
import { backend, BASE, server } from "./test/server";

const shell = {
  game_name: "Elden Ring",
  game_ready: true,
  game_running: false,
  profiles: ["Vanilla", "Overhaul"],
  profile_index: 1,
  status: { text: "Ready to play", tone: "muted", busy: false },
  pill: { text: "Play", state: "ready", can_launch: true, mode_text: "" },
  unseen: 2,
};

function boot() {
  server.use(
    http.get(`${BASE}/v1/pages/shell`, () => HttpResponse.json(shell)),
    http.get(`${BASE}/v1/events`, () => new HttpResponse(new ReadableStream(), { headers: { "Content-Type": "text/event-stream" } })),
  );
  const router = buildRouter(createMemoryHistory({ initialEntries: ["/"] }));
  render(<AppWithBackend backend={backend} router={router} />);
}

test("the shell shows game, profile, status, the rail and lands on Mods", async () => {
  boot();
  expect(await screen.findByText("Elden Ring")).toBeInTheDocument();
  expect(screen.getByLabelText("Profile")).toHaveTextContent("Overhaul");
  expect(screen.getByRole("status")).toHaveTextContent("Ready to play");
  expect(await screen.findByRole("heading", { name: "Mods" })).toBeInTheDocument();
  const rail = screen.getByRole("navigation", { name: "Pages" });
  expect(rail.querySelectorAll("a")).toHaveLength(6);
  expect(screen.getByRole("link", { name: /Mods/ })).toHaveAttribute("aria-current", "page");
  expect(screen.getByLabelText("2 failed since you last looked")).toBeInTheDocument();
});

test("Ctrl+1..6 jump to the pages in rail order", async () => {
  boot();
  const user = userEvent.setup();
  await screen.findByRole("heading", { name: "Mods" });
  await user.keyboard("{Control>}3{/Control}");
  expect(await screen.findByRole("heading", { name: "Saves" })).toBeInTheDocument();
  await user.keyboard("{Control>}6{/Control}");
  expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
  expect(screen.getByLabelText("Theme")).toBeInTheDocument();
  await user.keyboard("{Control>}4{/Control}");
  expect(await screen.findByRole("heading", { name: "Profile transfer" })).toBeInTheDocument();
});
