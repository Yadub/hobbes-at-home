import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { MinusIcon, PlusIcon } from "./Icons";

export function Segmented<T extends string | number>({ value, options, onChange, label }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string;
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={String(o.value)} type="button" aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Stepper({ onMinus, onPlus, label }: { onMinus: () => void; onPlus: () => void; label: string }) {
  return (
    <span className="stepper" role="group" aria-label={label}>
      <button type="button" onClick={onMinus} aria-label={`Less ${label}`}><MinusIcon /></button>
      <button type="button" onClick={onPlus} aria-label={`More ${label}`}><PlusIcon /></button>
    </span>
  );
}

/** A progress ring (a meter bent into a circle): the track is a light step of the same hue. */
export function Ring({ value, max, hue, size = 120, stroke = 14, label }: {
  value: number; max: number; hue: string; size?: number; stroke?: number; label: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const share = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
  return (
    <div className="ring-wrap" style={{ "--hue": hue, width: size, height: size } as CSSProperties} role="img" aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle className="ring-track" cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} />
        <circle className="ring-fill" cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke}
          strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - share)} opacity={share === 0 ? 0 : 1} />
      </svg>
    </div>
  );
}

export function Meter({ label, hue, value, max, unit = "g" }: {
  label: string; hue: string; value: number; max?: number | null; unit?: string;
}) {
  const share = max ? Math.min(1, value / max) : 0;
  return (
    <div className="meter" style={{ "--hue": hue } as CSSProperties}>
      <div className="meter-top">
        <span className="meter-label"><span className="dot" />{label}</span>
        <span className="meter-value num">
          <strong>{Math.round(value)}</strong>{max ? ` / ${max}` : ""} {unit}
        </span>
      </div>
      {max ? (
        <div className="meter-track" role="meter" aria-label={label} aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={max}>
          <div className="meter-fill" style={{ width: `${share * 100}%` }} />
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- toast with Undo

type ToastMsg = { text: string; undo?: () => void | Promise<void> };
const ToastCtx = createContext<(t: ToastMsg) => void>(() => {});

export function ToastHost({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastMsg | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const show = useCallback((t: ToastMsg) => {
    window.clearTimeout(timer.current);
    setToast(t);
    timer.current = window.setTimeout(() => setToast(null), t.undo ? 6000 : 3000);
  }, []);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return (
    <ToastCtx.Provider value={show}>
      {children}
      {toast && (
        <div className="toast" role="status">
          <span>{toast.text}</span>
          {toast.undo && (
            <button type="button" onClick={async () => { const u = toast.undo; setToast(null); await u?.(); }}>Undo</button>
          )}
        </div>
      )}
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
