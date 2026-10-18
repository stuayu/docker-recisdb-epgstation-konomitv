export type ServiceStatus = "up" | "down" | "unknown";
export type StatusFetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

/** Probe a service with a bounded request. Mixed-content HTTP probes from HTTPS pages are skipped. */
export async function checkService(
  url: string,
  pageProtocol: string,
  fetcher: StatusFetcher = fetch,
  timeoutMs = 4000,
): Promise<ServiceStatus> {
  let target: URL;
  try {
    target = new URL(url);
  } catch {
    return "unknown";
  }
  if (target.protocol !== "http:" && target.protocol !== "https:") return "unknown";
  const normalizedPageProtocol = pageProtocol.toLowerCase();
  if ((normalizedPageProtocol === "https:" || normalizedPageProtocol === "https") && target.protocol === "http:") {
    return "unknown";
  }

  const controller = new AbortController();
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const timeoutResult = new Promise<ServiceStatus>((resolve) => {
    timeout = setTimeout(() => {
      controller.abort();
      resolve("down");
    }, Math.max(0, timeoutMs));
  });
  const request = Promise.resolve()
    .then(() => fetcher(target, {
      method: "GET",
      mode: "no-cors",
      cache: "no-store",
      signal: controller.signal,
    }))
    // In no-cors mode browsers hide status and headers. A resolved fetch still
    // proves that the browser reached the target, regardless of response type.
    .then((): ServiceStatus => "up")
    .catch((): ServiceStatus => "down");

  try {
    return await Promise.race([request, timeoutResult]);
  } finally {
    if (timeout !== undefined) clearTimeout(timeout);
  }
}
