import { describe, expect, it } from "vitest";
import {
  getSchedule,
  parseEpgState,
  parseRecordings,
  parseReserves,
  parseServices,
  parseTuners,
  recentRecordings,
} from "./edcb";

const now = Date.parse("2026-10-18T10:00:00+09:00");
function reserve(reserveID: number, startTime = "2026-10-18T10:00:00+09:00", recEnabled = true, recMode = 0) {
  return {
    reserveID,
    title: `番組${reserveID}`,
    startTime,
    durationSecond: 3600,
    stationName: "放送局",
    eid: 90 + reserveID,
    recSetting: { recEnabled, recMode, startMargin: -5, endMargin: 30 },
    overlapMode: 0,
  };
}

describe("EDCB response parsers", () => {
  it("accepts direct arrays and empty lists with ISO 8601 timezone dates", () => {
    expect(parseReserves([reserve(1)])).toHaveLength(1);
    expect(parseRecordings([{ id: 3, title: "Rec", startTime: "2026-10-18T09:00:00+09:00", durationSecond: 60, serviceName: "NHK" }])).toHaveLength(1);
    expect(parseTuners([{ tunerID: 1, tunerName: "Tuner", reserveList: [1] }])).toHaveLength(1);
    expect(parseReserves([])).toEqual([]);
    expect(parseRecordings([])).toEqual([]);
    expect(parseTuners([])).toEqual([]);
  });

  it.each([
    () => parseReserves({ total: 1, items: [reserve(1)] }),
    () => parseReserves([reserve(1, "2026-02-30T10:00:00+09:00")]),
    () => parseReserves([reserve(1, "2026-10-18T24:00:00+09:00")]),
    () => parseReserves([reserve(1, "2026-10-18T10:00:00")]),
    () => parseReserves([reserve(1, "2026-10-18T10:00:00+09:00", true, 6)]),
    () => parseReserves([reserve(1, "2026-10-18T10:00:00+09:00", false, 5)]),
    () => parseRecordings([{ id: 1, title: "x", startTime: "bad", durationSecond: 1, serviceName: "x" }]),
    () => parseTuners([{ tunerID: 1, tunerName: "x", reserveList: "1" }]),
  ])("fails the entire response for malformed records", (parse) => {
    expect(parse).toThrow();
  });

  it("marks blank EPG names and handles the exact EPG loading response", () => {
    expect(parseReserves([{ ...reserve(1), title: " ", stationName: "" }])[0]).toMatchObject({ title: "番組情報未取得", stationName: "放送局未取得" });
    expect(parseEpgState([])).toBe("empty");
    expect(parseEpgState({ err: "EPGデータを読み込み中、または存在しません" })).toBe("empty");
    expect(parseEpgState([{ onid: 1, tsid: 2, sid: 3, service_name: "NHK" }])).toBe("ready");
    expect(parseServices([{ onid: 1, tsid: 2, sid: 3, service_name: "NHK", private: true }])).toEqual([{ onid: 1, tsid: 2, sid: 3, service_name: "NHK" }]);
    expect(() => parseEpgState({ err: "別の障害" })).toThrow();
    expect(() => parseEpgState([{ onid: 1 }])).toThrow();
  });
});

describe("EDCB schedule summary", () => {
  it("counts only assigned enabled recording modes in their nominal window", () => {
    const reserves = parseReserves([
      reserve(1),
      reserve(2, "2026-10-18T11:00:00+09:00"),
      reserve(3, "2026-10-18T10:00:00+09:00", false, 0),
      reserve(4, "2026-10-18T10:00:00+09:00", true, 4),
      reserve(5, "2026-10-18T10:00:00+09:00", false, 1),
    ]);
    const tuners = parseTuners([
      { tunerID: 10, tunerName: "地デジ", reserveList: [1, 2, 3, 4, 5] },
      { tunerID: 0xffffffff, tunerName: "競合", reserveList: [1] },
    ]);
    const summary = getSchedule(reserves, tuners, now);
    expect(summary.total).toBe(5);
    expect(summary.recordingCount).toBe(1);
    expect(summary.upcoming.map((item) => item.reserveID)).toEqual([1, 2]);
    expect(summary.next?.reserveID).toBe(2);
    expect(summary.tuners).toHaveLength(1);
    expect(summary.tuners[0]).toMatchObject({ recording: true, current: { reserveID: 1 }, next: { reserveID: 2 } });
  });

  it("uses start-inclusive and end-exclusive recording boundaries and requires tuner assignment", () => {
    const reserves = parseReserves([reserve(1, "2026-10-18T10:00:00+09:00"), reserve(2, "2026-10-18T09:00:00+09:00")]);
    expect(getSchedule(reserves, parseTuners([{ tunerID: 1, tunerName: "A", reserveList: [1, 2] }]), now).recordingCount).toBe(1);
    expect(getSchedule(reserves.slice(0, 1), parseTuners([]), now).recordingCount).toBe(0);
  });

  it("returns five most recent recordings", () => {
    const recordings = parseRecordings(Array.from({ length: 7 }, (_, i) => ({
      id: i,
      title: `${i}`,
      startTime: `2026-10-${String(10 + i).padStart(2, "0")}T10:00:00+09:00`,
      durationSecond: 120,
      serviceName: "NHK",
    })));
    expect(recentRecordings(recordings).map(({ id }) => id)).toEqual([6, 5, 4, 3, 2]);
  });
});
