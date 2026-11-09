import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError } from "./client";
afterEach(() => vi.unstubAllGlobals());
it("preserves conflict status and actionable message", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ message: "版本已变化" }), {
          status: 409,
        }),
      ),
  );
  await expect(api("/test")).rejects.toMatchObject({
    status: 409,
    message: "版本已变化",
  });
  await expect(api("/test")).rejects.toBeInstanceOf(ApiError);
});
it("does not force JSON headers on file uploads", async () => {
  const mock = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", mock);
  await api("/media", { method: "POST", body: new FormData() });
  expect(mock.mock.calls[0][1].headers).toEqual({});
});
