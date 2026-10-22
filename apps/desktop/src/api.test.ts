import { afterEach, expect, test, vi } from "vitest";
import { createApi } from "./api";

afterEach(() => vi.unstubAllGlobals());

test("health sends the bearer token to the handshake base url", async () => {
  const body = { app_version: "1", contract_version: "1", ready: true };
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  expect(await createApi({ base_url: "http://127.0.0.1:5", token: "t" }).health()).toEqual(body);
  const req = fetchMock.mock.calls[0]![0] as Request;
  expect(req.url).toBe("http://127.0.0.1:5/v1/health");
  expect(req.headers.get("Authorization")).toBe("Bearer t");
});

test("health rejects on a non-2xx answer", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("no", { status: 401 })));
  await expect(createApi({ base_url: "http://x", token: "t" }).health()).rejects.toBeDefined();
});
