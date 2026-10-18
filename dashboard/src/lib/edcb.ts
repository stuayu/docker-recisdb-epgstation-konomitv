export interface EDCBRecSetting {
  recEnabled: boolean;
  recMode: number;
  startMargin?: number;
  endMargin?: number;
}

export interface EDCBReserve {
  reserveID: number;
  title: string;
  startTime: string;
  durationSecond: number;
  stationName: string;
  eid: number;
  recSetting: EDCBRecSetting;
  overlapMode: number;
}

export interface EDCBRecording {
  id: number;
  title: string;
  startTime: string;
  durationSecond: number;
  serviceName: string;
}

export interface EDCBTuner {
  tunerID: number;
  tunerName: string;
  reserveList: number[];
}

export interface EDCBService {
  onid: number;
  tsid: number;
  sid: number;
  service_name: string;
}

export type EpgState = "ready" | "empty";

export interface ScheduleEntry extends EDCBReserve {
  endTime: string;
  endTimestamp: number;
  startTimestamp: number;
  recording: boolean;
  tunerName?: string;
}

export interface TunerSchedule {
  id: number;
  name: string;
  recording: boolean;
  current?: ScheduleEntry;
  next?: ScheduleEntry;
}

export interface ScheduleSummary {
  total: number;
  recordingCount: number;
  next?: ScheduleEntry;
  upcoming: ScheduleEntry[];
  tuners: TunerSchedule[];
}

const NO_EPG_TITLE = "番組情報未取得";
const NO_STATION_NAME = "放送局未取得";

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string") throw new Error(`EDCB response: invalid ${field}`);
  return value;
}

function requiredInteger(value: unknown, field: string, min = 0, max = Number.MAX_SAFE_INTEGER): number {
  if (!Number.isSafeInteger(value) || (value as number) < min || (value as number) > max) {
    throw new Error(`EDCB response: invalid ${field}`);
  }
  return value as number;
}

function requiredDate(value: unknown, field: string): string {
  const pattern = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,3})?(Z|([+-])(\d{2}):(\d{2}))$/;
  const match = typeof value === "string" ? pattern.exec(value) : null;
  if (!match) {
    throw new Error(`EDCB response: invalid ${field}`);
  }
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, , , offsetHourText, offsetMinuteText] = match;
  const [year, month, day, hour, minute, second] = [yearText, monthText, dayText, hourText, minuteText, secondText].map(Number);
  const offsetHour = offsetHourText ? Number(offsetHourText) : 0;
  const offsetMinute = offsetMinuteText ? Number(offsetMinuteText) : 0;
  const calendarCheck = new Date(0);
  calendarCheck.setUTCFullYear(year, month - 1, day);
  calendarCheck.setUTCHours(0, 0, 0, 0);
  if (!Number.isFinite(Date.parse(value as string)) || month < 1 || month > 12 || day < 1 || day > 31 ||
      hour > 23 || minute > 59 || second > 59 || offsetHour > 14 || offsetMinute > 59 ||
      (offsetHour === 14 && offsetMinute !== 0) || calendarCheck.getUTCFullYear() !== year ||
      calendarCheck.getUTCMonth() !== month - 1 || calendarCheck.getUTCDate() !== day) {
    throw new Error(`EDCB response: invalid ${field}`);
  }
  return value as string;
}

function list(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`EDCB response: invalid ${field}`);
  return value;
}

function normalizeTitle(title: string): string {
  return title.trim() ? title : NO_EPG_TITLE;
}

function normalizeStation(name: string): string {
  return name.trim() ? name : NO_STATION_NAME;
}

function parseReserve(value: unknown): EDCBReserve {
  if (!record(value) || !record(value.recSetting)) throw new Error("EDCB response: invalid reserve");
  const setting = value.recSetting;
  if (typeof setting.recEnabled !== "boolean") throw new Error("EDCB response: invalid recSetting.recEnabled");
  // ConvertJson rewrites the internal disabled mode 5 to recEnabled=false and
  // a display recMode in 0..4 (normally 1), so 5 is not valid in this payload.
  const recMode = requiredInteger(setting.recMode, "recSetting.recMode", 0, 4);
  const recSetting: EDCBRecSetting = {
    recEnabled: setting.recEnabled,
    recMode,
    ...(setting.startMargin === undefined ? {} : { startMargin: requiredMargin(setting.startMargin, "recSetting.startMargin") }),
    ...(setting.endMargin === undefined ? {} : { endMargin: requiredMargin(setting.endMargin, "recSetting.endMargin") }),
  };
  return {
    reserveID: requiredInteger(value.reserveID, "reserveID"),
    title: normalizeTitle(requiredString(value.title, "title")),
    startTime: requiredDate(value.startTime, "startTime"),
    durationSecond: requiredInteger(value.durationSecond, "durationSecond", 1),
    stationName: normalizeStation(requiredString(value.stationName, "stationName")),
    eid: requiredInteger(value.eid, "eid"),
    recSetting,
    overlapMode: requiredInteger(value.overlapMode, "overlapMode"),
  };
}

function requiredMargin(value: unknown, field: string): number {
  if (!Number.isSafeInteger(value)) throw new Error(`EDCB response: invalid ${field}`);
  return value as number;
}

export function parseReserves(value: unknown): EDCBReserve[] {
  return list(value, "reserve list").map(parseReserve);
}

function parseRecording(value: unknown): EDCBRecording {
  if (!record(value)) throw new Error("EDCB response: invalid recording");
  return {
    id: requiredInteger(value.id, "recording.id"),
    title: normalizeTitle(requiredString(value.title, "title")),
    startTime: requiredDate(value.startTime, "startTime"),
    durationSecond: requiredInteger(value.durationSecond, "durationSecond", 1),
    serviceName: normalizeStation(requiredString(value.serviceName, "serviceName")),
  };
}

export function parseRecordings(value: unknown): EDCBRecording[] {
  return list(value, "recording list").map(parseRecording);
}

function parseTuner(value: unknown): EDCBTuner {
  if (!record(value)) throw new Error("EDCB response: invalid tuner");
  return {
    tunerID: requiredInteger(value.tunerID, "tunerID", 0, 0xffffffff),
    tunerName: requiredString(value.tunerName, "tunerName"),
    reserveList: list(value.reserveList, "tuner.reserveList").map((id) => requiredInteger(id, "reserveList item")),
  };
}

export function parseTuners(value: unknown): EDCBTuner[] {
  return list(value, "tuner list").map(parseTuner);
}

const EPG_EMPTY_ERROR = "EPGデータを読み込み中、または存在しません";

export function parseServices(value: unknown): EDCBService[] {
  return list(value, "service list").map((item) => {
    if (!record(item)) throw new Error("EDCB response: invalid service");
    return {
      onid: requiredInteger(item.onid, "service.onid"),
      tsid: requiredInteger(item.tsid, "service.tsid"),
      sid: requiredInteger(item.sid, "service.sid"),
      service_name: requiredString(item.service_name, "service.service_name"),
    };
  });
}

export function parseEpgState(value: unknown): EpgState {
  if (record(value) && value.err === EPG_EMPTY_ERROR) return "empty";
  const services = parseServices(value);
  return services.length === 0 ? "empty" : "ready";
}

function canRecord(reserve: EDCBReserve): boolean {
  return reserve.recSetting.recEnabled && reserve.recSetting.recMode >= 0 && reserve.recSetting.recMode <= 3;
}

function entryFor(reserve: EDCBReserve, tunerName?: string): ScheduleEntry {
  const startTimestamp = Date.parse(reserve.startTime);
  const endTimestamp = startTimestamp + reserve.durationSecond * 1000;
  return {
    ...reserve,
    endTime: new Date(endTimestamp).toISOString(),
    startTimestamp,
    endTimestamp,
    recording: false,
    ...(tunerName === undefined ? {} : { tunerName }),
  };
}

/** Build a time-aware schedule. "recording" is an assignment/time estimate, not process confirmation. */
export function getSchedule(reserves: EDCBReserve[], tuners: EDCBTuner[], now: Date | number): ScheduleSummary {
  const nowMs = now instanceof Date ? now.getTime() : now;
  if (!Number.isFinite(nowMs)) throw new Error("Invalid schedule time");

  const normalTuners = tuners.filter((tuner) => tuner.tunerID !== 0xffffffff);
  const tunerForReserve = new Map<number, EDCBTuner>();
  for (const tuner of normalTuners) {
    for (const reserveID of tuner.reserveList) {
      if (!tunerForReserve.has(reserveID)) tunerForReserve.set(reserveID, tuner);
    }
  }

  const entries = reserves.map((reserve) => {
    const tuner = tunerForReserve.get(reserve.reserveID);
    const entry = entryFor(reserve, tuner?.tunerName);
    entry.recording = canRecord(reserve) && tuner !== undefined && entry.startTimestamp <= nowMs && nowMs < entry.endTimestamp;
    return entry;
  }).sort((a, b) => a.startTimestamp - b.startTimestamp || a.reserveID - b.reserveID);

  const upcoming = entries.filter((entry) => canRecord(entry) && entry.endTimestamp > nowMs).slice(0, 5);
  const next = entries.find((entry) => canRecord(entry) && entry.startTimestamp > nowMs);
  const tunerSchedules = normalTuners.map((tuner): TunerSchedule => {
    const assigned = entries.filter((entry) => tuner.reserveList.includes(entry.reserveID) && canRecord(entry));
    const current = assigned.find((entry) => entry.startTimestamp <= nowMs && nowMs < entry.endTimestamp);
    const nextTunerEntry = assigned.find((entry) => entry.startTimestamp > nowMs);
    return {
      id: tuner.tunerID,
      name: tuner.tunerName,
      recording: current !== undefined,
      ...(current ? { current } : {}),
      ...(nextTunerEntry ? { next: nextTunerEntry } : {}),
    };
  });
  return {
    total: reserves.length,
    recordingCount: entries.filter((entry) => entry.recording).length,
    ...(next ? { next } : {}),
    upcoming,
    tuners: tunerSchedules,
  };
}

export function recentRecordings(recordings: EDCBRecording[]): EDCBRecording[] {
  return [...recordings]
    .sort((a, b) => Date.parse(b.startTime) - Date.parse(a.startTime) || b.id - a.id)
    .slice(0, 5);
}
