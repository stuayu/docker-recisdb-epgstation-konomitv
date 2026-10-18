import { afterEach, describe, expect, it, vi } from "vitest";
import { checkService } from "./status";

afterEach(() => vi.useRealTimers());

describe("service health checks", () => {
  it("uses a no-cors, no-store request and counts any resolved response as up", async () => {
    const fetcher = vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      expect(init).toMatchObject({ method: "GET", mode: "no-cors", cache: "no-store" });
      expect(init?.signal).toBeInstanceOf(AbortSignal);
      return new Response(null, { status: 204 });
    });
    await expect(checkService("http://tv.local:8080/", "http:", fetcher)).resolves.toBe("up");
    expect(fetcher).toHaveBeenCalledOnce();
    await expect(checkService("http://tv.local/", "http:", async () => new Response(null, { status: 503 }))).resolves.toBe("up");
  });

  it("skips HTTPS-to-HTTP probes and invalid URLs", async () => {
    const fetcher = vi.fn();
    await expect(checkService("http://tv.local/", "https:", fetcher)).resolves.toBe("unknown");
    await expect(checkService("javascript:alert(1)", "http:", fetcher)).resolves.toBe("unknown");
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("returns down on timeout even when fetch ignores abort", async () => {
    vi.useFakeTimers();
    const neverResolves = vi.fn(() => new Promise<Response>(() => undefined));
    const pending = checkService("http://tv.local/", "http:", neverResolves, 4000);
    await vi.advanceTimersByTimeAsync(4000);
    await expect(pending).resolves.toBe("down");
  });

  it("counts an opaque resolved no-cors response as up", async () => {
    await expect(checkService("https://tv.local/", "https:", async () => ({ type: "opaque", status: 0 } as Response))).resolves.toBe("up");
  });
});
