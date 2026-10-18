import { describe, expect, it } from "vitest";
import type { DashboardConfig, ServiceConfig } from "./config";
import { resolveService } from "./urls";

const config: DashboardConfig = { title: "DTV", host: "192.168.1.10", httpsHost: "tv.example.jp", services: [], edcb: { api: true } };
const service: ServiceConfig = { id: "epg", name: "EPGStation", role: "web", http: 8888, https: 8443, path: "/" };

describe("resolveService", () => {
  it("uses current-origin HTTPS as primary and config host for HTTP secondary", () => {
    expect(resolveService(service, config, { protocol: "https:", hostname: "dash.example.jp" })).toEqual({
      primary: { url: "https://dash.example.jp:8443/", protocol: "HTTPS", port: 8443 },
      secondary: { url: "http://192.168.1.10:8888/", protocol: "HTTP", port: 8888 },
    });
  });

  it("uses current-origin HTTP as primary and configured HTTPS host as secondary", () => {
    expect(resolveService(service, config, { protocol: "http:", hostname: "dash.local" })).toEqual({
      primary: { url: "http://dash.local:8888/", protocol: "HTTP", port: 8888 },
      secondary: { url: "https://tv.example.jp:8443/", protocol: "HTTPS", port: 8443 },
    });
  });

  it("falls back to the configured alternate protocol when the origin protocol is unavailable", () => {
    expect(resolveService({ ...service, http: undefined }, config, { protocol: "http:", hostname: "dash.local" })).toEqual({
      primary: { url: "https://tv.example.jp:8443/", protocol: "HTTPS", port: 8443 },
    });
    expect(resolveService({ ...service, https: undefined }, config, { protocol: "https:", hostname: "dash.example.jp" })).toEqual({
      primary: { url: "http://192.168.1.10:8888/", protocol: "HTTP", port: 8888 },
    });
  });

  it("brackets IPv6 hosts", () => {
    expect(resolveService({ id: "x", name: "X", role: "web", http: 80 },
      { ...config, host: "2001:db8::2" }, { protocol: "http", hostname: "2001:db8::3" })).toEqual({
      primary: { url: "http://[2001:db8::3]:80", protocol: "HTTP", port: 80 },
    });
  });

  it("returns local links only", () => {
    expect(resolveService({ id: "x", name: "X", role: "web", local: "http://127.0.0.1:80/" }, config,
      { protocol: "http", hostname: "dash.local" })).toEqual({
      local: "http://127.0.0.1:80/",
    });
  });

  it("does not invent an HTTPS host when none is configured", () => {
    expect(resolveService({ ...service, https: undefined }, { ...config, httpsHost: null },
      { protocol: "http:", hostname: "dash.local" })).toEqual({
      primary: { url: "http://dash.local:8888/", protocol: "HTTP", port: 8888 },
    });
  });
});

describe('HTTP/HTTPS page × service protocol matrix', () => {
  it.each([
    ['http:', { http: 8888 }, 'http://dash.local:8888/', undefined],
    ['http:', { https: 8443 }, 'https://tv.example.jp:8443/', undefined],
    ['http:', { http: 8888, https: 8443 }, 'http://dash.local:8888/', 'https://tv.example.jp:8443/'],
    ['https:', { http: 8888 }, 'http://192.168.1.10:8888/', undefined],
    ['https:', { https: 8443 }, 'https://dash.local:8443/', undefined],
    ['https:', { http: 8888, https: 8443 }, 'https://dash.local:8443/', 'http://192.168.1.10:8888/'],
  ] as const)('%s with %j', (protocol, ports, primary, secondary) => {
    const result = resolveService({ id: 'test', name: 'Test', role: 'Test', path: '/', ...ports }, config, { protocol, hostname: 'dash.local' });
    expect(result.primary?.url).toBe(primary);
    expect(result.secondary?.url).toBe(secondary);
  });
  it.each(['http:', 'https:'])('keeps local address copy-only on %s pages', protocol => {
    expect(resolveService({ id: 'local', name: 'Local', role: 'Local', local: 'http://127.0.0.1:6980/' }, config, { protocol, hostname: 'dash.local' })).toEqual({ local: 'http://127.0.0.1:6980/' });
  });
});
