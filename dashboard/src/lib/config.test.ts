import { describe, expect, it } from "vitest";
import { CONFIG_ERROR, parseConfig, parseConfigText } from "./config";

const valid = {
  title: "DTV",
  host: "192.168.1.20",
  httpsHost: "tv.example.jp",
  services: [{ id: "edcb", name: "EDCB", role: "recorder", http: 5510, path: "/api/" }],
  edcb: { api: true },
};

describe("dashboard config validation", () => {
  it("accepts safe IPv4, DNS and IPv6 hosts and retains only supplied services", () => {
    expect(parseConfig(valid)).toEqual({ ok: true, value: valid });
    expect(parseConfig({ ...valid, host: "2001:db8::1", httpsHost: null })).toMatchObject({ ok: true });
    expect(parseConfig({ ...valid, host: "tv.example.jp", services: [] })).toMatchObject({ ok: true, value: { services: [] } });
  });

  it.each([
    { ...valid, host: "https://example.jp" },
    { ...valid, host: "999.1.1.1" },
    { ...valid, host: "bad host" },
    { ...valid, services: [{ ...valid.services[0], http: 0 }] },
    { ...valid, services: [{ ...valid.services[0], https: 65536 }] },
    { ...valid, services: [{ ...valid.services[0], path: "//evil.example/" }] },
    { ...valid, services: [{ ...valid.services[0], path: "/x\\y" }] },
    { ...valid, services: [{ id: "unreachable", name: "Unknown", role: "misc" }] },
    { ...valid, services: [{ ...valid.services[0], local: "javascript:alert(1)" }] },
    { ...valid, services: [valid.services[0], valid.services[0]] },
    { ...valid, httpsHost: null, services: [{ id: "only-secure", name: "s", role: "r", https: 443 }] },
    { ...valid, edcb: { api: "true" } },
  ])("rejects invalid configuration", (input) => {
    expect(parseConfig(input)).toEqual({ ok: false, error: CONFIG_ERROR });
  });

  it("maps malformed JSON and arbitrary untrusted inputs to one stable message", () => {
    expect(parseConfigText("{" )).toEqual({ ok: false, error: CONFIG_ERROR });
    expect(parseConfig(null)).toEqual({ ok: false, error: CONFIG_ERROR });
  });
});
