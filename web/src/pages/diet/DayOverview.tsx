import { useState } from "react";
import type { CSSProperties } from "react";
import { api, problemText } from "../../api/client";
import type { Day } from "../../api/client";
import { Ring, Segmented } from "../../components/Controls";
import { whole } from "../../lib/format";
import { Link } from "../../router";

type Macro = { key: "protein" | "carbs" | "fat" | "fibre"; label: string; hue: string };
const MACROS: Macro[] = [
  { key: "protein", label: "Protein", hue: "var(--protein)" },
  { key: "carbs", label: "Carbs", hue: "var(--carbs)" },
  { key: "fat", label: "Fat", hue: "var(--fat)" },
  { key: "fibre", label: "Fibre", hue: "var(--fibre)" },
];

/** One macro: eaten against its target, and what's left (or over) in words beside it. */
function MacroRow({ m, eaten, target }: { m: Macro; eaten: number; target: number | null | undefined }) {
  const left = target != null ? Math.round(target - eaten) : null;
  const share = target ? Math.min(1, eaten / target) : 0;
  return (
    <div className="macro" style={{ "--hue": m.hue } as CSSProperties}>
      <div className="macro-top">
        <span className="meter-label"><span className="dot" />{m.label}</span>
        <span className="meter-value num"><strong>{whole(eaten)}</strong>{target != null ? ` / ${whole(target)}` : ""} g</span>
        {left != null && (
          <span className={`macro-left num${left < 0 ? " over" : ""}`}>{left < 0 ? `${whole(-left)} g over` : `${whole(left)} g left`}</span>
        )}
      </div>
      {target != null && (
        <div className="meter-track" role="meter" aria-label={`${m.label}: ${whole(eaten)} of ${whole(target)} g`}
          aria-valuenow={Math.round(eaten)} aria-valuemin={0} aria-valuemax={target}>
          <div className="meter-fill" style={{ width: `${share * 100}%` }} />
        </div>
      )}
    </div>
  );
}

/** The day's target split of calories between protein, carbs and fat: a thin part-to-whole bar,
 *  each part labelled underneath (colour is never the only cue). */
function Split({ split }: { split: { protein: number; carbs: number; fat: number } }) {
  const parts = MACROS.slice(0, 3).map((m) => ({ ...m, pct: split[m.key as "protein" | "carbs" | "fat"] }));
  return (
    <div className="split" aria-label={`Daily split: ${parts.map((p) => `${p.pct}% ${p.label.toLowerCase()}`).join(", ")}`}>
      <div className="split-bar" aria-hidden="true">
        {parts.map((p) => <span key={p.key} style={{ flexGrow: p.pct, background: p.hue }} />)}
      </div>
      <div className="split-legend footnote secondary">
        <span>Daily split</span>
        {parts.map((p) => (
          <span key={p.key}><span className="dot" style={{ background: p.hue }} />{p.pct}% {p.label.toLowerCase()}</span>
        ))}
      </div>
    </div>
  );
}

/** The two answers the targets still need, asked right here instead of on another page. */
function QuickSetup({ d, onSaved }: { d: Day; onSaved: () => void }) {
  const missing = d.targets.missing;
  const [sex, setSex] = useState<"male" | "female" | "">("");
  const [year, setYear] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const onlyThese = missing.every((m) => m === "sex" || m === "birth year");

  async function save() {
    setBusy(true);
    setError(null);
    const g = d.targets.goal;
    const { error: err } = await api.PUT("/api/diet/goals", {
      params: { query: { day: d.day } },
      body: {
        goal: g.goal, rate: g.rate, activity: g.activity, eat_back: g.eat_back, protein_per_kg: g.protein_per_kg,
        kcal_override: g.kcal_override, protein_override: g.protein_override, fat_pct: g.fat_pct ?? 0.3,
        sex: sex || null, birth_year: year ? Number(year) : null,
      },
    });
    setBusy(false);
    if (err) setError(problemText(err));
    else onSaved();
  }

  if (!onlyThese) {
    return (
      <div style={{ display: "grid", gap: 10 }}>
        <p className="subhead secondary" style={{ margin: 0 }}>
          To work out your targets, the dashboard needs your {missing.join(", ")}.
        </p>
        <Link to="/diet/goals" className="button small tinted" style={{ justifySelf: "start" }}>Set Goal</Link>
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <p className="subhead" style={{ margin: 0 }}>
        {missing.length === 1 ? "One answer" : "Two answers"} and your targets appear.{d.targets.weight?.source ? ` Your weight already comes from ${d.targets.weight.source}.` : ""}
      </p>
      {missing.includes("sex") && (
        <Segmented label="Sex" value={sex} onChange={setSex}
          options={[{ value: "male", label: "Male" }, { value: "female", label: "Female" }]} />
      )}
      {missing.includes("birth year") && (
        <label className="inline-field">
          <span>Year of birth</span>
          <input className="field num" type="number" inputMode="numeric" placeholder="Required" value={year}
            onChange={(e) => setYear(e.target.value)} />
        </label>
      )}
      {error && <p className="footnote danger" style={{ margin: 0 }}>{error}</p>}
      <button className="button small" style={{ justifySelf: "start" }} onClick={save}
        disabled={busy || (missing.includes("sex") && !sex) || (missing.includes("birth year") && year.length !== 4)}>
        {busy ? "Saving…" : "Save"}
      </button>
    </div>
  );
}

export function DayOverview({ d, onChanged }: { d: Day; onChanged: () => void }) {
  const t = d.targets;
  const left = d.left.kcal ?? 0;
  const over = left < 0;
  const hue = over && Math.abs(left) > (t.kcal ?? 0) * 0.1 ? "var(--orange-ui)" : "var(--energy)";
  return (
    <div className="card" style={{ marginBottom: 16, display: "grid", gap: 18 }}>
      {t.ready ? (
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <Ring value={d.eaten.kcal} max={t.kcal ?? 0} hue={hue} size={128} stroke={16}
            label={`${whole(d.eaten.kcal)} of ${whole(t.kcal)} kcal eaten`} />
          <div style={{ display: "grid", gap: 2 }}>
            <span className="footnote secondary" style={{ fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.02em" }}>
              {over ? "Over" : "Left"}
            </span>
            <span className="value hero">{whole(Math.abs(left))}</span>
            <span className="subhead secondary num">kcal · {whole(d.eaten.kcal)} of {whole(t.kcal)}</span>
          </div>
        </div>
      ) : (
        <>
          <div>
            <span className="footnote secondary" style={{ fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.02em" }}>Eaten</span>
            <div className="value">{whole(d.eaten.kcal)}<span className="unit">kcal</span></div>
          </div>
          <QuickSetup d={d} onSaved={onChanged} />
        </>
      )}

      <div style={{ display: "grid", gap: 14 }}>
        {MACROS.map((m) => (
          <MacroRow key={m.key} m={m} eaten={d.eaten[m.key] ?? 0} target={t[m.key]} />
        ))}
      </div>

      {t.split && <Split split={t.split} />}

      {t.active_kcal ? (
        <p className="footnote secondary" style={{ margin: 0 }}>
          Includes {Math.round((t.goal.eat_back ?? 0) * 100)}% of the {whole(t.active_kcal)} kcal of activity {t.activity_source ?? "Apple Health"} recorded.
        </p>
      ) : null}
    </div>
  );
}
