import { useEffect, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { api, useLoad } from "../../api/client";
import { ChevronLeft, ChevronRight } from "../../components/Icons";
import { Sheet } from "../../components/Sheet";
import { addDays, dayOf, parseDay, today } from "../../lib/dates";
import { whole } from "../../lib/format";

/** The first day of the week where the owner is (Sunday in India and the US, Monday in the UK). */
function weekStart(): number {
  try {
    const loc = new Intl.Locale(navigator.language) as Intl.Locale & {
      getWeekInfo?: () => { firstDay: number }; weekInfo?: { firstDay: number };
    };
    const info = loc.getWeekInfo?.() ?? loc.weekInfo;
    if (info?.firstDay) return info.firstDay % 7;
  } catch {
    // older browsers: fall through
  }
  return 1;
}

const monthOf = (day: string) => `${day.slice(0, 7)}-01`;

function shiftMonth(first: string, n: number): string {
  const d = parseDay(first);
  return dayOf(new Date(d.getFullYear(), d.getMonth() + n, 1));
}

function MiniRing({ share, over }: { share: number; over: boolean }) {
  const size = 18;
  const stroke = 3;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true" style={{ transform: "rotate(-90deg)" }}
      className="cal-ring">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className="ring-track" />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} strokeLinecap="round" className="ring-fill"
        strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(1, share))} style={over ? { stroke: "var(--orange-ui)" } : undefined} />
    </svg>
  );
}

/** A month at a time: each logged day carries a small ring of calories eaten against that day's target.
 *  Tap a day to go to it. */
export function CalendarSheet({ open, day, onClose, onPick }: {
  open: boolean; day: string; onClose: () => void; onPick: (day: string) => void;
}) {
  const [month, setMonth] = useState(monthOf(day));
  const now = today();
  useEffect(() => { if (open) setMonth(monthOf(day)); }, [open, day]);

  const last = addDays(shiftMonth(month, 1), -1);
  const end = last < now ? last : now;
  const hist = useLoad(
    () => (open && month <= now ? api.GET("/api/diet/history", { params: { query: { start: month, end } } }) : Promise.resolve({ data: undefined })),
    [open, month, end],
  );
  const byDay = useMemo(() => new Map((hist.data?.days ?? []).map((d) => [d.day, d])), [hist.data]);

  const first = weekStart();
  const lead = (parseDay(month).getDay() - first + 7) % 7;
  const days = Array.from({ length: Number(last.slice(8)) }, (_, i) => addDays(month, i));
  const weekdays = Array.from({ length: 7 }, (_, i) =>
    new Date(2024, 0, 7 + ((first + i) % 7)).toLocaleDateString(undefined, { weekday: "narrow" }));
  const logged = (hist.data?.days ?? []).filter((d) => d.kcal > 0);
  const avg = logged.length ? logged.reduce((a, d) => a + d.kcal, 0) / logged.length : null;
  const title = parseDay(month).toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const elapsed = month > now ? 0 : Number(end.slice(8));

  return (
    <Sheet open={open} title="Calendar" onClose={onClose} action={{ label: "Today", onClick: () => onPick(now) }}>
      <div className="cal" style={{ "--hue": "var(--energy)" } as CSSProperties}>
        <div className="cal-head">
          <h2 className="title3" aria-live="polite">{title}</h2>
          <div style={{ display: "flex" }}>
            <button type="button" className="bar-button" onClick={() => setMonth(shiftMonth(month, -1))} aria-label="Previous month">
              <ChevronLeft />
            </button>
            <button type="button" className="bar-button" onClick={() => setMonth(shiftMonth(month, 1))} aria-label="Next month"
              disabled={shiftMonth(month, 1) > now}>
              <ChevronRight className="chev" />
            </button>
          </div>
        </div>

        <div className="cal-grid" role="grid" aria-label={title}>
          {weekdays.map((w, i) => <div key={i} className="cal-weekday" aria-hidden="true">{w}</div>)}
          {Array.from({ length: lead }, (_, i) => <div key={`pad-${i}`} />)}
          {days.map((d) => {
            const h = byDay.get(d);
            const future = d > now;
            const target = h?.target_kcal ?? null;
            const label = parseDay(d).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })
              + (h && h.kcal > 0 ? `, ${whole(h.kcal)} kcal${target ? ` of ${whole(target)}` : ""}` : ", nothing logged");
            return (
              <button key={d} type="button" className="cal-day" disabled={future} onClick={() => onPick(d)}
                aria-current={d === day ? "date" : undefined} aria-label={label}>
                <span className={`cal-num${d === day ? " selected" : ""}${d === now ? " today" : ""}`}>{Number(d.slice(8))}</span>
                {h && h.kcal > 0 ? (target ? <MiniRing share={h.kcal / target} over={h.kcal > target * 1.1} /> : <span className="cal-dot" />)
                  : <span className="cal-blank" />}
              </button>
            );
          })}
        </div>

        <p className="footnote secondary" style={{ margin: "14px 4px 0" }}>
          {month > now ? "" : `Logged ${logged.length} of ${elapsed} ${elapsed === 1 ? "day" : "days"}`}
          {avg !== null ? ` · average ${whole(avg)} kcal a day` : ""}. Rings show calories eaten against that day's target.
        </p>
      </div>
    </Sheet>
  );
}
