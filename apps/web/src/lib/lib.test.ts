import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, query } from "./api";
import { fmtAge, fmtTime, liftFraction, statusMeta, toIso } from "./format";
import { pushBounded, reconnectDelay, series, type Frame } from "./telemetry";

describe("format", () => {
  it("formats ages without inventing values", () => {
    expect(fmtAge(null)).toBe("never");
    expect(fmtAge(0.02)).toBe("20 ms");
    expect(fmtAge(4.2)).toBe("4.20 s");
    expect(fmtAge(300)).toBe("5 min");
  });
  it("prints UTC times the way the copilot cites them", () => {
    expect(fmtTime("2026-11-17T20:41:11.384Z")).toBe("2026-11-17 20:41:11.384Z");
    expect(fmtTime(null)).toBe("—");
  });
  it("maps every status to an icon and a word, unknown strings to UNKNOWN", () => {
    for (const s of ["READY", "BLOCKED", "UNKNOWN", "ERROR"]) {
      expect(statusMeta(s).label).toBe(s);
      expect(statusMeta(s).icon).toBeTruthy();
    }
    expect(statusMeta("WHATEVER").label).toBe("UNKNOWN");
  });
  it("converts lift_joint to a fraction of the 0.35 m travel and refuses non-finite", () => {
    expect(liftFraction(0.175)).toBeCloseTo(0.5);
    expect(liftFraction(1)).toBe(1);
    expect(liftFraction(null)).toBeNull();
    expect(liftFraction(Number.NaN)).toBeNull();
  });
  it("converts filter times to ISO", () => {
    expect(toIso("")).toBeUndefined();
    // datetime-local is the viewer's local time; the API gets the same instant in UTC.
    expect(toIso("2026-11-17T10:00")).toBe(new Date(2026, 10, 17, 10, 0).toISOString());
  });
});

describe("telemetry buffer", () => {
  it("is bounded", () => {
    let b: number[] = [];
    for (let i = 0; i < 1000; i++) b = pushBounded(b, i, 300);
    expect(b.length).toBe(300);
    expect(b[0]).toBe(700);
    expect(b[299]).toBe(999);
  });
  it("backs off exponentially to a ceiling", () => {
    expect(reconnectDelay(0)).toBe(500);
    expect(reconnectDelay(3)).toBe(4000);
    expect(reconnectDelay(20)).toBe(10000);
  });
  it("extracts a joint series and keeps gaps as null", () => {
    const f = (pos: (number | null)[], name = ["lift_joint"]): Frame =>
      ({ t: "2026-11-17T00:00:00Z", replay: true, name, position: pos, velocity: [] });
    const s = series([f([0.1]), f([null]), f([0.2], ["other"])], "lift_joint");
    expect(s.map((p) => p.v)).toEqual([0.1, null, null]);
  });
});

describe("api client", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("builds query strings without empty values", () => {
    expect(query({ a: "x", b: "", c: undefined, d: 0 })).toBe("?a=x&d=0");
    expect(query({})).toBe("");
  });
  it("surfaces structured API errors", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "unknown_fixture", message: "no fixture" } }), { status: 404 })));
    await expect(api("/fixtures/select")).rejects.toMatchObject({ code: "unknown_fixture", status: 404 });
  });
  it("reports an unreachable API instead of returning data", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    const p = api("/status");
    await expect(p).rejects.toBeInstanceOf(ApiError);
    await expect(p).rejects.toMatchObject({ code: "api_unreachable" });
  });
});
