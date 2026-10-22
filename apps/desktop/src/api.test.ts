import { afterEach, expect, test, vi } from "vitest";
import { createApi } from "./api";

afterEach(() => vi.unstubAllGlobals());

test("get sends the bearer token to the handshake base url", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response('{"ok":true}'));
  vi.stubGlobal("fetch", fetchMock);
  const body = await createApi({ base_url: "http://127.0.0.1:5", token: "t" }).get("/v1/health");
  expect(body).toEqual({ ok: true });
  expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:5/v1/health", {
    headers: { Authorization: "Bearer t" },
  });
});

test("get rejects on a non-2xx answer", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("no", { status: 401 })));
  await expect(createApi({ base_url: "http://x", token: "t" }).get("/v1/health")).rejects.toThrow("HTTP 401");
});
