export interface ServiceConfig {
  id: string;
  name: string;
  role: string;
  http?: number;
  https?: number;
  path?: string;
  local?: string;
  note?: string;
}

export interface DashboardConfig {
  title: string;
  host: string;
  httpsHost: string | null;
  services: ServiceConfig[];
  edcb: { api: boolean };
}

export const CONFIG_ERROR = "設定ファイル dashboard.json を読めません。make regen-config SERVICE=edcb で作り直してください。";

export type ConfigResult =
  | { ok: true; value: DashboardConfig }
  | { ok: false; error: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validHostname(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > 253 || /[\s/@?#\\]/.test(value)) return false;
  if (value.includes(":")) {
    try {
      const parsed = new URL(`http://[${value}]/`);
      return parsed.hostname.length > 2 && parsed.hostname.startsWith("[");
    } catch {
      return false;
    }
  }
  // Validate IPv4 strictly; numeric dotted strings must not fall through as DNS names.
  if (/^[\d.]+$/.test(value)) {
    const parts = value.split(".");
    return parts.length === 4 && parts.every((part) => /^(0|[1-9]\d{0,2})$/.test(part) && Number(part) <= 255);
  }
  return value.length <= 253 && value.split(".").every((label) =>
    label.length > 0 && label.length <= 63 && /^[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?$/.test(label),
  );
}

function validLocalUrl(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    const url = new URL(value);
    return (url.protocol === "http:" || url.protocol === "https:") &&
      !url.username && !url.password && !url.hash && validHostname(url.hostname.replace(/^\[|\]$/g, ""));
  } catch {
    return false;
  }
}

function validPort(value: unknown): value is number {
  return Number.isInteger(value) && (value as number) >= 1 && (value as number) <= 65535;
}

function parseService(value: unknown): ServiceConfig | undefined {
  if (!isRecord(value) || typeof value.id !== "string" || !value.id.trim() ||
      typeof value.name !== "string" || !value.name.trim() ||
      typeof value.role !== "string" || !value.role.trim()) return undefined;
  for (const key of ["http", "https"] as const) {
    if (value[key] !== undefined && !validPort(value[key])) return undefined;
  }
  if (value.http === undefined && value.https === undefined && value.local === undefined) return undefined;
  if (value.path !== undefined && (typeof value.path !== "string" || !value.path.startsWith("/") || value.path.startsWith("//") || value.path.includes("\\"))) return undefined;
  if (value.local !== undefined && !validLocalUrl(value.local)) return undefined;
  if (value.local !== undefined && (value.http !== undefined || value.https !== undefined)) return undefined;
  if (value.note !== undefined && typeof value.note !== "string") return undefined;
  return {
    id: value.id,
    name: value.name,
    role: value.role,
    ...(value.http === undefined ? {} : { http: value.http as number }),
    ...(value.https === undefined ? {} : { https: value.https as number }),
    ...(value.path === undefined ? {} : { path: value.path }),
    ...(value.local === undefined ? {} : { local: value.local }),
    ...(value.note === undefined ? {} : { note: value.note }),
  };
}

/** Validate the untrusted JSON value without throwing or inventing any services. */
export function parseConfig(input: unknown): ConfigResult {
  if (!isRecord(input) || typeof input.title !== "string" || !input.title.trim() ||
      !validHostname(input.host) ||
      !(input.httpsHost === null || validHostname(input.httpsHost)) ||
      !Array.isArray(input.services) || !isRecord(input.edcb) || typeof input.edcb.api !== "boolean") {
    return { ok: false, error: CONFIG_ERROR };
  }
  const services = input.services.map(parseService);
  if (services.some((service) => service === undefined)) return { ok: false, error: CONFIG_ERROR };
  const ids = services.map((service) => (service as ServiceConfig).id);
  if (new Set(ids).size !== ids.length) return { ok: false, error: CONFIG_ERROR };
  const parsedServices = services as ServiceConfig[];
  if (input.httpsHost === null && parsedServices.some((service) => service.https !== undefined && service.http === undefined)) {
    return { ok: false, error: CONFIG_ERROR };
  }
  return {
    ok: true,
    value: {
      title: input.title,
      host: input.host,
      httpsHost: input.httpsHost,
      services: parsedServices,
      edcb: { api: input.edcb.api },
    },
  };
}

export function parseConfigText(text: string): ConfigResult {
  try {
    return parseConfig(JSON.parse(text) as unknown);
  } catch {
    return { ok: false, error: CONFIG_ERROR };
  }
}
