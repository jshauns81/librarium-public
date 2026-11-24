import { afterEach, expect, it, vi } from "vitest";
import { api, ApiError } from "../src/api";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("preserves caller cancellation while applying the read deadline", async () => {
  const controller = new AbortController();
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (_path, init: RequestInit) =>
        new Promise((_resolve, reject) => {
          init.signal?.addEventListener(
            "abort",
            () => reject(init.signal?.reason),
            { once: true },
          );
        }),
    ),
  );
  const request = api("works?q=old", { signal: controller.signal });
  const reason = new DOMException("Superseded", "AbortError");
  controller.abort(reason);
  await expect(request).rejects.toBe(reason);
});

it("keeps HTTP status and useful JSON errors distinct from transport failure", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "Invalid work identifier" }), {
        status: 400,
      }),
    ),
  );
  await expect(api("jobs?work_id=bad")).rejects.toMatchObject({
    status: 400,
    message: "Invalid work identifier",
  });
  vi.mocked(fetch).mockResolvedValue(
    new Response("upstream unavailable", { status: 503 }),
  );
  await expect(api("jobs")).rejects.toEqual(
    new ApiError("Request failed (503)", 503),
  );
  vi.mocked(fetch).mockResolvedValue(new Response("{}", { status: 409 }));
  await expect(api("jobs")).rejects.toMatchObject({
    status: 409,
    message: "Request failed (409)",
  });
});

it("retains the optional typed library-check conflict without inferring one from status or text", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          error: "Check changed",
          code: "library_check_changed",
        }),
        { status: 409 },
      ),
    ),
  );
  await expect(api("library")).rejects.toMatchObject({
    status: 409,
    code: "library_check_changed",
  });
  vi.mocked(fetch).mockResolvedValue(
    new Response(JSON.stringify({ error: "The library check changed" }), {
      status: 409,
    }),
  );
  await expect(api("library")).rejects.toMatchObject({
    status: 409,
    code: undefined,
  });
});
