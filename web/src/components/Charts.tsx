import { useEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, PointerEvent } from "react";

// Charts in the style of Apple Health: one series each, thin marks, hairline grid with labels on the
// right, and the reading above the chart that changes to whichever day you touch (or pick with the
// arrow keys). Every value is also in the "All data" list below each chart.

export type Bar = { key: string; label: string; value: number | null; target?: number | null };

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e?.contentRect.width ?? 0)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

const compact = (n: number) => (n >= 1000 ? `${Math.round(n / 100) / 10}K`.replace(".0K", "K") : `${Math.round(n)}`);

function useSelection(n: number) {
  const [sel, setSel] = useState<number | null>(null);
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowLeft") { setSel((s) => Math.max(0, (s ?? n) - 1)); e.preventDefault(); }
    if (e.key === "ArrowRight") { setSel((s) => Math.min(n - 1, (s ?? -1) + 1)); e.preventDefault(); }
    if (e.key === "Escape") setSel(null);
  };
  return { sel, setSel, onKey };
}

/** Columns, one per day, with a 2 px tick for that day's target. */
export function BarChart({ bars, hue, unit, title, summaryLabel, height = 180 }: {
  bars: Bar[]; hue: string; unit: string; title: string; summaryLabel: string; height?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const { sel, setSel, onKey } = useSelection(bars.length);
  const axisW = 36;
  const plotW = Math.max(0, width - axisW);
  const xBand = 18;
  const max = niceMax(Math.max(1, ...bars.map((b) => Math.max(b.value ?? 0, b.target ?? 0))));
  const slot = bars.length ? plotW / bars.length : 0;
  const barW = Math.max(2, Math.min(24, slot * 0.62));
  const top = 10; // room for the top axis label
  const y = (v: number) => top + (height - top) - (v / max) * (height - top);
  const values = bars.map((b) => b.value).filter((v): v is number => v !== null && v > 0);
  const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  const chosen = sel !== null ? bars[sel] : null;

  const pick = (e: PointerEvent<SVGRectElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const i = Math.floor(((e.clientX - r.left) / r.width) * bars.length);
    setSel(Math.max(0, Math.min(bars.length - 1, i)));
  };
  const labelEvery = Math.ceil(bars.length / 7);

  return (
    <figure className="chart" style={{ "--hue": hue } as CSSProperties} aria-label={title}>
      <div className="chart-readout">
        <span className="caption secondary">{chosen ? chosen.label.toUpperCase() : summaryLabel}</span>
        <span className="value">{chosen ? (chosen.value === null ? "–" : Math.round(chosen.value).toLocaleString())
          : avg === null ? "–" : Math.round(avg).toLocaleString()}<span className="unit">{unit}</span></span>
        {chosen?.target ? <span className="subhead secondary">Target {Math.round(chosen.target).toLocaleString()} {unit}</span> : <span className="subhead secondary">&nbsp;</span>}
      </div>
      <div ref={ref} tabIndex={0} onKeyDown={onKey} onBlur={() => setSel(null)} className="chart-plot"
        aria-label={`${title}. Use the arrow keys to read each day.`}>
        {width > 0 && (
          <svg width={width} height={height + xBand} role="img" aria-hidden="true">
            {[0, 0.5, 1].map((f) => (
              <g key={f}>
                <line x1={0} x2={plotW} y1={y(max * f) + 0.5} y2={y(max * f) + 0.5} className="grid" />
                <text x={plotW + 6} y={y(max * f) + 4} className="axis">{compact(max * f)}</text>
              </g>
            ))}
            {bars.map((b, i) => {
              const cx = slot * i + slot / 2;
              const v = b.value ?? 0;
              const barTop = y(v);
              const r = Math.min(4, barW / 2, (height - barTop) / 2);
              const dim = sel !== null && sel !== i;
              return (
                <g key={b.key} opacity={dim ? 0.35 : 1}>
                  {v > 0 && (
                    <path className="bar" d={`M${cx - barW / 2},${height} V${barTop + r} q0,-${r} ${r},-${r} H${cx + barW / 2 - r} q${r},0 ${r},${r} V${height} Z`} />
                  )}
                  {b.target ? <line className="target" x1={cx - barW / 2 - 2} x2={cx + barW / 2 + 2} y1={y(b.target)} y2={y(b.target)} /> : null}
                  {i % labelEvery === 0 && <text x={cx} y={height + 14} textAnchor="middle" className="axis">{b.label.split(" ")[0]?.slice(0, bars.length > 10 ? 2 : 3)}</text>}
                </g>
              );
            })}
            {sel !== null && <line x1={slot * sel + slot / 2} x2={slot * sel + slot / 2} y1={0} y2={height} className="crosshair" />}
            <rect x={0} y={0} width={plotW} height={height} fill="transparent" onPointerMove={pick} onPointerDown={pick}
              onPointerLeave={(e) => { if (e.pointerType === "mouse") setSel(null); }} />
          </svg>
        )}
      </div>
    </figure>
  );
}

export type Pt = { key: string; label: string; value: number };

/** A single line (e.g. weight), with the latest value marked. */
export function LineChart({ points, hue, unit, title, height = 150 }: {
  points: Pt[]; hue: string; unit: string; title: string; height?: number;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const { sel, setSel, onKey } = useSelection(points.length);
  const axisW = 40;
  const plotW = Math.max(0, width - axisW);
  const pad = 8;
  const vals = points.map((p) => p.value);
  const lo = Math.floor(Math.min(...vals) - 0.5);
  const hi = Math.ceil(Math.max(...vals) + 0.5);
  const x = (i: number) => (points.length === 1 ? plotW / 2 : pad + (i / (points.length - 1)) * (plotW - 2 * pad));
  const y = (v: number) => pad + (1 - (v - lo) / Math.max(0.001, hi - lo)) * (height - 2 * pad);
  const last = points[points.length - 1];
  const chosen = sel !== null ? points[sel] : last;
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p.value)}`).join(" ");
  const pick = (e: PointerEvent<SVGRectElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const rel = (e.clientX - r.left - pad) / Math.max(1, r.width - 2 * pad);
    setSel(Math.max(0, Math.min(points.length - 1, Math.round(rel * (points.length - 1)))));
  };
  if (!points.length) return null;

  return (
    <figure className="chart" style={{ "--hue": hue } as CSSProperties} aria-label={title}>
      <div className="chart-readout">
        <span className="caption secondary">{(sel !== null ? chosen?.label : "LATEST")?.toUpperCase()}</span>
        <span className="value">{chosen ? chosen.value.toLocaleString(undefined, { maximumFractionDigits: 1 }) : "–"}<span className="unit">{unit}</span></span>
      </div>
      <div ref={ref} tabIndex={0} onKeyDown={onKey} onBlur={() => setSel(null)} className="chart-plot"
        aria-label={`${title}. Use the arrow keys to read each day.`}>
        {width > 0 && (
          <svg width={width} height={height} aria-hidden="true">
            {[lo, (lo + hi) / 2, hi].map((v) => (
              <g key={v}>
                <line x1={0} x2={plotW} y1={y(v) + 0.5} y2={y(v) + 0.5} className="grid" />
                <text x={plotW + 6} y={y(v) + 4} className="axis">{Math.round(v * 10) / 10}</text>
              </g>
            ))}
            <path d={`${d} L${x(points.length - 1)},${height} L${x(0)},${height} Z`} className="area" />
            <path d={d} className="line" />
            {chosen && <circle cx={x(sel ?? points.length - 1)} cy={y(chosen.value)} r={5} className="dot" />}
            <rect x={0} y={0} width={plotW} height={height} fill="transparent" onPointerMove={pick} onPointerDown={pick}
              onPointerLeave={(e) => { if (e.pointerType === "mouse") setSel(null); }} />
          </svg>
        )}
      </div>
    </figure>
  );
}
