// Dates as the phone sees them: local days (YYYY-MM-DD) and times with their UTC offset.

const pad = (n: number) => String(n).padStart(2, "0");

export function dayOf(d: Date): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export const today = () => dayOf(new Date());

export function addDays(day: string, n: number): string {
  const [y, m, d] = day.split("-").map(Number);
  return dayOf(new Date(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + n));
}

export function parseDay(day: string): Date {
  const [y, m, d] = day.split("-").map(Number);
  return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
}

/** A local time as ISO 8601 with its offset, e.g. 2026-10-17T13:05:00+05:30. */
export function withOffset(d: Date): string {
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? "+" : "-";
  const a = Math.abs(off);
  return `${dayOf(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}${sign}${pad(Math.floor(a / 60))}:${pad(a % 60)}`;
}

/** For <input type="datetime-local">. */
export function toLocalInput(d: Date): string {
  return `${dayOf(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function dayLabel(day: string, { long = false } = {}): string {
  const t = today();
  if (day === t) return "Today";
  if (day === addDays(t, -1)) return "Yesterday";
  return parseDay(day).toLocaleDateString(undefined, long
    ? { weekday: "long", day: "numeric", month: "long" }
    : { weekday: "short", day: "numeric", month: "short" });
}

export function timeLabel(iso: string): string {
  // The time as it was on the clock where it was logged (the ISO string carries that clock's time).
  const m = /T(\d{2}):(\d{2})/.exec(iso);
  if (!m) return "";
  const d = new Date(2000, 0, 1, Number(m[1]), Number(m[2]));
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function longDate(d = new Date()): string {
  return d.toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
}
