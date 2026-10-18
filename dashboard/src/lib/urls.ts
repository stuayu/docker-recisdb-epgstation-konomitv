import type { DashboardConfig, ServiceConfig } from "./config";

export interface ServiceEndpoint {
  url: string;
  protocol: "HTTP" | "HTTPS";
  port: number;
}

export interface ResolvedService {
  primary?: ServiceEndpoint;
  secondary?: ServiceEndpoint;
  local?: string;
}

export interface PageLocation {
  protocol: string;
  hostname: string;
}

function formatHost(host: string): string {
  const bareHost = host.replace(/^\[|\]$/g, "");
  return bareHost.includes(":") ? `[${bareHost}]` : bareHost;
}

function endpoint(service: ServiceConfig, scheme: "http" | "https", host: string): ServiceEndpoint | undefined {
  const port = scheme === "http" ? service.http : service.https;
  if (port === undefined) return undefined;
  const path = service.path ?? "";
  const protocol = scheme === "http" ? "HTTP" : "HTTPS";
  return { url: `${scheme}://${formatHost(host)}:${port}${path}`, protocol, port };
}

/** Resolve service endpoints for the current browser origin. This function performs no network access. */
export function resolveService(
  service: ServiceConfig,
  config: DashboardConfig,
  location: PageLocation,
): ResolvedService {
  if (service.local) return { local: service.local };
  const isHttps = location.protocol.toLowerCase() === "https:" || location.protocol.toLowerCase() === "https";
  const currentScheme = isHttps ? "https" : "http";
  const otherScheme = isHttps ? "http" : "https";
  const currentHost = location.hostname || config.host;
  const alternateHost = isHttps ? config.host : config.httpsHost;

  const onOrigin = endpoint(service, currentScheme, currentHost);
  const fallback = alternateHost ? endpoint(service, otherScheme, alternateHost) : undefined;
  const primary = onOrigin ?? fallback;
  const otherHost = isHttps ? config.host : config.httpsHost;
  const other = otherHost ? endpoint(service, otherScheme, otherHost) : undefined;
  const secondary = other && other.url !== primary?.url ? other : undefined;

  return {
    ...(primary ? { primary } : {}),
    ...(secondary ? { secondary } : {}),
    ...(service.local ? { local: service.local } : {}),
  };
}
