import { useEffect, useState } from "react";
import { api, problemText, useLoad } from "../../api/client";
import type { GoalsIn } from "../../api/client";
import { Segmented, Stepper, useToast } from "../../components/Controls";
import { List, Row, Section } from "../../components/List";
import { Page } from "../../components/Page";
import { dayLabel, today, withOffset } from "../../lib/dates";
import { oneDp, whole } from "../../lib/format";

const RATES = [0.1, 0.25, 0.5, 0.75];
const ACTIVITY: { value: GoalsIn["activity"]; label: string }[] = [
  { value: "sedentary", label: "Little" }, { value: "light", label: "Light" },
  { value: "moderate", label: "Moderate" }, { value: "very", label: "High" },
];

export function Goals() {
  const day = today();
  const view = useLoad(() => api.GET("/api/diet/goals", { params: { query: { day } } }), [day]);
  const drinks = useLoad(() => api.GET("/api/diet/drinks", { params: { query: { day } } }), [day]);
  const [form, setForm] = useState<GoalsIn | null>(null);
  const [byHandKcal, setByHandKcal] = useState(false);
  const [byHandProtein, setByHandProtein] = useState(false);
  const [weight, setWeight] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const toast = useToast();

  useEffect(() => {
    const v = view.data;
    if (!v || form) return;
    setForm({
      goal: v.goal.goal, rate: v.goal.rate || 0.25, activity: v.goal.activity, eat_back: v.goal.eat_back,
      protein_per_kg: v.goal.protein_per_kg, kcal_override: v.goal.kcal_override, protein_override: v.goal.protein_override,
      fat_pct: v.goal.fat_pct ?? 0.3,
      sex: v.profile.sex, birth_year: v.profile.birth_year, height_cm: v.profile.height_cm,
    });
    setByHandKcal(v.goal.kcal_override !== null);
    setByHandProtein(v.goal.protein_override !== null);
  }, [view.data, form]);

  if (!form || !view.data) {
    return <Page title="Goal" backTo="/diet" backLabel="Diet">{view.error && <div className="notice error">{view.error}</div>}</Page>;
  }
  const v = view.data;
  const t = v.targets;
  const set = (patch: Partial<GoalsIn>) => setForm({ ...form, ...patch });

  async function save() {
    if (!form) return;
    setBusy(true);
    setError(null);
    try {
      if (weight) {
        const { error: err } = await api.POST("/api/diet/weight", { body: { kg: Number(weight), at: withOffset(new Date()) } });
        if (err) throw new Error(problemText(err));
        setWeight("");
      }
      const body: GoalsIn = {
        ...form,
        rate: form.goal === "maintain" ? 0 : form.rate,
        kcal_override: byHandKcal ? form.kcal_override : null,
        protein_override: byHandProtein ? form.protein_override : null,
      };
      const { data, error: err } = await api.PUT("/api/diet/goals", { params: { query: { day } }, body });
      if (err) throw new Error(problemText(err));
      const missing = data.targets.missing;
      if (missing.length) setError(`Saved. Still needed for your targets: ${missing.join(", ")}.`);
      else toast({ text: `Goal saved: ${data.targets.kcal?.toLocaleString()} kcal and ${data.targets.protein} g protein a day` });
      view.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page title="Goal" backTo="/diet" backLabel="Diet"
      trailing={<button className="bar-button strong" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</button>}>
      {error && <div className="notice error" role="alert">{error}</div>}

      <div className="card" style={{ marginBottom: 28, display: "grid", gap: 8 }}>
        {t.ready ? (
          <>
            <div style={{ display: "flex", gap: 28 }}>
              <div><div className="caption secondary">Calories a day</div><div className="value">{whole(t.kcal)}<span className="unit">kcal</span></div></div>
              <div><div className="caption secondary">Protein</div><div className="value">{whole(t.protein)}<span className="unit">g</span></div></div>
            </div>
            <p className="footnote secondary" style={{ margin: 0 }}>Today: {t.kcal_how}. Protein: {t.protein_how}.</p>
            {t.notes.map((n) => <p key={n} className="footnote" style={{ margin: 0, color: "var(--carbs-text)" }}>{n}</p>)}
          </>
        ) : (
          <p className="subhead secondary" style={{ margin: 0 }}>Add your {t.missing.join(", ")} below and save to see your daily targets.</p>
        )}
      </div>

      <Section header="Goal">
        <List>
          <div className="row" style={{ display: "block" }}>
            <Segmented label="Goal" value={form.goal} onChange={(g) => set({ goal: g })}
              options={[{ value: "lose", label: "Lose" }, { value: "maintain", label: "Maintain" }, { value: "gain", label: "Gain" }]} />
          </div>
          {form.goal !== "maintain" && (
            <div className="row" style={{ display: "grid", gap: 8 }}>
              <span className="row-title">Rate</span>
              <Segmented label="Rate" value={form.rate} onChange={(r) => set({ rate: r })}
                options={RATES.map((r) => ({ value: r, label: `${r} kg` }))} />
            </div>
          )}
        </List>
        <p className="section-footer">
          {form.goal === "maintain" ? "Eat about what you burn." : `About ${whole(form.rate * 7700 / 7)} kcal a day ${form.goal === "lose" ? "under" : "over"} what you burn, per week: ${form.rate} kg.`}
          {" "}0.25 kg a week is a gentle pace.
        </p>
      </Section>

      <Section header="You" footer="Used for your resting energy (the Mifflin-St Jeor formula). Weight and height come from WHOOP or Apple Health when they have them.">
        <List>
          <div className="row" style={{ display: "block" }}>
            <Segmented label="Sex" value={form.sex ?? ""} onChange={(s) => set({ sex: s as GoalsIn["sex"] })}
              options={[{ value: "male", label: "Male" }, { value: "female", label: "Female" }]} />
          </div>
          <div className="row">
            <span className="row-main"><span className="row-title">Year of birth{!form.birth_year && <span className="needed">Needed</span>}</span></span>
            <input className="field num" type="number" inputMode="numeric" placeholder="Required" aria-label="Year of birth"
              value={form.birth_year ?? ""} onChange={(e) => set({ birth_year: e.target.value ? Number(e.target.value) : null })} />
          </div>
          <div className="row">
            <span className="row-main"><span className="row-title">Height</span>{v.profile.height_from_health && <span className="row-sub">From Apple Health</span>}</span>
            <input className="field num" type="number" inputMode="decimal" placeholder="cm" aria-label="Height in centimetres"
              value={form.height_cm ?? ""} onChange={(e) => set({ height_cm: e.target.value ? Number(e.target.value) : null })} style={{ maxWidth: 90 }} />
            <span className="row-value">cm</span>
          </div>
          <div className="row">
            <span className="row-main">
              <span className="row-title">Weight</span>
              <span className="row-sub">{t.weight ? `${oneDp(t.weight.kg)} kg, ${dayLabel(t.weight.day)}${t.weight.source ? ` · ${t.weight.source}` : ""}` : "None yet"}</span>
            </span>
            <input className="field num" type="number" inputMode="decimal" placeholder="Add" aria-label="Today's weight in kg"
              value={weight} onChange={(e) => setWeight(e.target.value)} style={{ maxWidth: 80 }} />
            <span className="row-value">kg</span>
          </div>
        </List>
      </Section>

      <Section header="Activity" footer="When WHOOP or Apple Health records activity, your target starts from resting energy × 1.2 and adds back this share of what you've burned so far today (trackers tend to overcount), so it rises after a workout. Without activity data it uses your usual level.">
        <List>
          <div className="row" style={{ display: "grid", gap: 8 }}>
            <span className="row-title">Usual activity</span>
            <Segmented label="Usual activity" value={form.activity} onChange={(a) => set({ activity: a })} options={ACTIVITY} />
          </div>
          <div className="row" style={{ display: "grid", gap: 8 }}>
            <span className="row-title">Add back activity</span>
            <Segmented label="Add back activity" value={form.eat_back} onChange={(x) => set({ eat_back: x })}
              options={[{ value: 0, label: "None" }, { value: 0.5, label: "Half" }, { value: 0.75, label: "¾" }, { value: 1, label: "All" }]} />
          </div>
        </List>
      </Section>

      <Section header="Protein">
        <List>
          <div className="row">
            <span className="row-main"><span className="row-title">Per kg of body weight</span></span>
            <span className="row-value num">{oneDp(form.protein_per_kg)} g</span>
            <Stepper label="protein" onMinus={() => set({ protein_per_kg: Math.max(0.8, Math.round((form.protein_per_kg - 0.1) * 10) / 10) })}
              onPlus={() => set({ protein_per_kg: Math.min(2.5, Math.round((form.protein_per_kg + 0.1) * 10) / 10) })} />
          </div>
        </List>
      </Section>

      <Section header="Macros" footer={t.split
        ? `Your daily split: ${t.split.protein}% protein, ${t.split.carbs}% carbs, ${t.split.fat}% fat: ${whole(t.protein)} g protein, ${whole(t.carbs)} g carbs, ${whole(t.fat)} g fat and ${whole(t.fibre)} g fibre. Carbs fill what protein and fat leave; fibre is 14 g per 1,000 kcal. Saved changes show here.`
        : "Carbs fill what protein and fat leave; fibre is 14 g per 1,000 kcal."}>
        <List>
          <div className="row" style={{ display: "grid", gap: 8 }}>
            <span className="row-title">Fat share of calories</span>
            <Segmented label="Fat share of calories" value={form.fat_pct ?? 0.3} onChange={(x) => set({ fat_pct: x })}
              options={[{ value: 0.2, label: "20%" }, { value: 0.25, label: "25%" }, { value: 0.3, label: "30%" }, { value: 0.35, label: "35%" }]} />
          </div>
        </List>
      </Section>

      <Section header="Caffeine and Alcohol" footer={drinks.data?.enabled ?? true
        ? "Shown on your meals and items, with weekly and monthly averages against guidance. Caffeine in mg; alcohol in UK units (8 g of pure alcohol)."
        : "Off: caffeine and alcohol aren't shown. The AI still notes them, so turning this on shows them for everything you've logged."}>
        <List>
          <div className="row">
            <span className="row-main"><span className="row-title">Track Caffeine and Alcohol</span></span>
            <input className="switch" type="checkbox" role="switch" aria-label="Track caffeine and alcohol" checked={drinks.data?.enabled ?? true}
              onChange={async (e) => {
                const on = e.target.checked;
                const { error: err } = await api.PUT("/api/diet/drinks", { params: { query: { day } }, body: { enabled: on } });
                if (err) { toast({ text: problemText(err) }); return; }
                toast({ text: on ? "Caffeine and alcohol are shown" : "Caffeine and alcohol are hidden" });
                drinks.reload();
              }} />
          </div>
          {(drinks.data?.enabled ?? true) && <Row title="Weekly and Monthly Averages" to="/diet/drinks" />}
        </List>
      </Section>

      <Section header="Set by hand" footer="Overrides the worked-out numbers. Activity is still added on top.">
        <List>
          <div className="row">
            <span className="row-main"><span className="row-title">Calories</span></span>
            {byHandKcal && <input className="field num" type="number" inputMode="numeric" aria-label="Calories a day" style={{ maxWidth: 90 }}
              value={form.kcal_override ?? ""} onChange={(e) => set({ kcal_override: e.target.value ? Number(e.target.value) : null })} />}
            <input className="switch" type="checkbox" role="switch" aria-label="Set calories by hand" checked={byHandKcal}
              onChange={(e) => { setByHandKcal(e.target.checked); if (e.target.checked && !form.kcal_override) set({ kcal_override: t.kcal ?? 2000 }); }} />
          </div>
          <div className="row">
            <span className="row-main"><span className="row-title">Protein</span></span>
            {byHandProtein && <input className="field num" type="number" inputMode="numeric" aria-label="Protein grams a day" style={{ maxWidth: 90 }}
              value={form.protein_override ?? ""} onChange={(e) => set({ protein_override: e.target.value ? Number(e.target.value) : null })} />}
            <input className="switch" type="checkbox" role="switch" aria-label="Set protein by hand" checked={byHandProtein}
              onChange={(e) => { setByHandProtein(e.target.checked); if (e.target.checked && !form.protein_override) set({ protein_override: t.protein ?? 120 }); }} />
          </div>
        </List>
      </Section>
    </Page>
  );
}
