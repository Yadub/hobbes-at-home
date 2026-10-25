import { useEffect, useState } from "react";
import { api, problemText, waitForJob } from "../../api/client";
import type { Food, Item } from "../../api/client";
import { Stepper, useToast } from "../../components/Controls";
import { Spinner } from "../../components/Icons";
import { List, Row, Section } from "../../components/List";
import { Sheet } from "../../components/Sheet";
import { oneDp, sourceName, whole } from "../../lib/format";
import { drinksText } from "./drinksText";
import { explainMeal, ItemWhy } from "./Why";

type Per100 = { kcal: number; protein: number; carbs: number; fat: number; caffeine?: number | null; alcohol?: number | null };
type Own = { protein: string; carbs: string; fat: string; kcal: string };
const MACROS: { key: keyof Own; label: string; unit: string }[] = [
  { key: "protein", label: "Protein", unit: "g" }, { key: "carbs", label: "Carbs", unit: "g" },
  { key: "fat", label: "Fat", unit: "g" }, { key: "kcal", label: "Energy", unit: "kcal" },
];
const num = (v: string) => (v.trim() === "" ? NaN : Number(v));
const hostOf = (link: string) => { try { return new URL(link).hostname.replace(/^www\./, ""); } catch { return link; } };
/** Energy from the macros: 4 kcal a gram of protein or carbs, 9 of fat. */
const energyOf = (o: Own) => Math.round(4 * (num(o.protein) || 0) + 4 * (num(o.carbs) || 0) + 9 * (num(o.fat) || 0));

function Nutrition({ per100, grams, drinks }: { per100: Per100; grams: number; drinks: boolean }) {
  const f = grams / 100;
  const cells: [string, string, string][] = [
    ["Energy", `${whole(per100.kcal * f)}`, "kcal"], ["Protein", oneDp(per100.protein * f), "g"],
    ["Carbs", oneDp(per100.carbs * f), "g"], ["Fat", oneDp(per100.fat * f), "g"],
  ];
  const extra = drinks ? drinksText((per100.caffeine ?? 0) * f, (per100.alcohol ?? 0) * f).replace(/^ · /, "") : "";
  return (
    <div className="card" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 22 }}>
      {cells.map(([k, v, u]) => (
        <div key={k} style={{ display: "grid", gap: 2 }}>
          <span className="caption secondary">{k}</span>
          <span className="value small" style={{ fontSize: 20 }}>{v}<span className="unit">{u}</span></span>
        </div>
      ))}
      {extra && <span className="footnote secondary" style={{ gridColumn: "1 / -1" }}>{extra.charAt(0).toUpperCase() + extra.slice(1)}</span>}
    </div>
  );
}

/** Change an item's amount or numbers, have the AI redo it with a correction, or ask why it has these numbers.
 *  With `item` null, say what else was eaten and the AI reads it into items. */
export function ItemSheet({ open, item, mealId, showDrinks = false, onClose, onDone }: {
  open: boolean; item: Item | null; mealId: number; showDrinks?: boolean; onClose: () => void; onDone: () => void;
}) {
  const adding = item === null;
  const [grams, setGrams] = useState(100);
  const [portion, setPortion] = useState("");
  const [food, setFood] = useState<Food | null>(null);
  const [per100, setPer100] = useState<Per100>({ kcal: 0, protein: 0, carbs: 0, fat: 0 });
  const [text, setText] = useState("");  // what else was eaten, when adding
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [correction, setCorrection] = useState("");
  const [redoing, setRedoing] = useState(false);
  const [why, setWhy] = useState<{ why: string; doubt: string } | null>(null);
  const [own, setOwn] = useState<Own | null>(null);  // the owner's own numbers, while they're typing them
  const [kcalTyped, setKcalTyped] = useState(false);
  const [explaining, setExplaining] = useState(false);
  const toast = useToast();

  useEffect(() => {
    if (!open) return;
    setError(null);
    setFood(null);
    setCorrection("");
    setWhy(null);
    setOwn(null);
    setKcalTyped(false);
    if (item) {
      setGrams(item.grams);
      setPortion(item.portion);
      setPer100(item.per100);
      if (item.food_id) {
        api.GET("/api/diet/foods/{food_id}", { params: { path: { food_id: item.food_id } } }).then(({ data }) => data && setFood(data));
      }
    } else {
      setText("");
    }
  }, [open, item]);

  const undoAll = (ids: number[]) => async () => {
    for (const id of [...ids].reverse()) await api.POST("/api/undo/{change_id}", { params: { path: { change_id: id } } });
    onDone();
  };

  async function save() {
    setBusy(true);
    setError(null);
    try {
      if (adding) {
        const { data, error: err } = await api.POST("/api/diet/meals/{meal_id}/items", {
          params: { path: { meal_id: mealId } }, body: { text: text.trim() },
        });
        if (err) throw new Error(problemText(err));
        const job = await waitForJob(data.job_id);
        if (job.status === "failed") throw new Error(job.error && job.error.includes("didn't find") ? job.error : "The AI couldn't read that this time. Try again, or say it differently.");
        const r = job.result as { change_ids?: number[]; names?: string[] } | null;
        const ids = r?.change_ids ?? [];
        toast({ text: `Added: ${(r?.names ?? []).join(", ") || "item"}`, undo: ids.length ? undoAll(ids) : undefined });
      } else {
        let nutrients: { protein: number; carbs: number; fat: number; kcal: number } | undefined;
        if (own) {
          const v = { protein: num(own.protein), carbs: num(own.carbs), fat: num(own.fat), kcal: num(own.kcal) };
          if (Object.values(v).some((x) => !Number.isFinite(x) || x < 0)) throw new Error("Fill in protein, carbs, fat and energy with numbers.");
          nutrients = v;
        }
        const { data, error: err } = await api.PATCH("/api/diet/items/{item_id}", {
          params: { path: { item_id: item.id } }, body: { grams, portion, nutrients },
        });
        if (err) throw new Error(problemText(err));
        toast({ text: "Item updated", undo: async () => { await api.POST("/api/undo/{change_id}", { params: { path: { change_id: data.change_id } } }); onDone(); } });
      }
      onDone();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setBusy(false);
    }
  }

  async function redo() {
    if (!item) return;
    setRedoing(true);
    setError(null);
    try {
      const { data, error: err } = await api.POST("/api/diet/items/{item_id}/redo", {
        params: { path: { item_id: item.id } }, body: { correction: correction.trim() },
      });
      if (err) throw new Error(problemText(err));
      const job = await waitForJob(data.job_id);
      if (job.status === "failed") throw new Error("The AI couldn't redo it this time. Try again, or change it by hand above.");
      const r = job.result as { change_id?: number; name?: string } | null;
      const changeId = r?.change_id;
      toast({ text: `Redone: ${r?.name ?? item.name}`, undo: changeId ? async () => { await api.POST("/api/undo/{change_id}", { params: { path: { change_id: changeId } } }); onDone(); } : undefined });
      onDone();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't redo it.");
    } finally {
      setRedoing(false);
    }
  }

  async function explainItem() {
    if (!item) return;
    setExplaining(true);
    setError(null);
    try {
      const e = await explainMeal(mealId);
      setWhy(e.items.find((x) => x.item_id === item.id) ?? { why: "The AI didn't say anything about this item. Try Why These Numbers on the meal.", doubt: "" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't explain it.");
    } finally {
      setExplaining(false);
    }
  }

  async function useEstimate() {
    if (!item) return;
    const { data, error: err } = await api.POST("/api/diet/items/{item_id}/estimate", { params: { path: { item_id: item.id } } });
    if (err) { setError(problemText(err)); return; }
    toast({ text: "Using the AI's estimate", undo: async () => { await api.POST("/api/undo/{change_id}", { params: { path: { change_id: data.change_id } } }); onDone(); } });
    onDone();
    onClose();
  }

  async function remove() {
    if (!item) return;
    const { data, error: err } = await api.DELETE("/api/diet/items/{item_id}", { params: { path: { item_id: item.id } } });
    if (err) { setError(problemText(err)); return; }
    toast({ text: `${item.name} removed`, undo: async () => { await api.POST("/api/undo/{change_id}", { params: { path: { change_id: data.change_id } } }); onDone(); } });
    onDone();
    onClose();
  }

  const step = grams >= 100 ? 10 : 5;
  const title = adding ? "Add Item" : item?.name ?? "";
  const servings = food?.servings ?? [];
  const aiGrams = item?.ai_grams;

  return (
    <Sheet open={open} title={title} onClose={onClose}
      action={{ label: adding ? "Add" : "Save", onClick: save, busy, disabled: adding && !text.trim() }}>
      {error && <div className="notice error" role="alert">{error}</div>}

      {adding ? (
        <Section header="What Else Did You Have?" footer={busy ? "Reading it… about half a minute." : "The AI reads it into items, as it does a meal's note. A branded product's label is looked up online."}>
          <List>
            <div className="row">
              <textarea className="field" aria-label="What else did you have?" value={text} rows={3} autoFocus
                onChange={(e) => setText(e.target.value)} placeholder="For example: a bowl of yoghurt, or a Kind bar, dark chocolate" />
            </div>
          </List>
        </Section>
      ) : (
        <>
          {own ? (
            <Section header="Your Numbers" footer="For the amount below. Energy follows the macros (4 kcal a gram of protein and carbs, 9 of fat) unless you type it. If you change the amount later, these scale with it.">
              <List>
                {MACROS.map((m) => (
                  <div key={m.key} className="row">
                    <span className="row-main"><span className="row-title">{m.label}</span></span>
                    <input className="field num" type="number" inputMode="decimal" min={0} step="0.1" aria-label={`${m.label} (${m.unit})`}
                      value={own[m.key]} style={{ maxWidth: 90 }}
                      onChange={(e) => {
                        const next = { ...own, [m.key]: e.target.value };
                        if (m.key === "kcal") setKcalTyped(true);
                        else if (!kcalTyped) next.kcal = String(energyOf(next));
                        setOwn(next);
                      }} />
                    <span className="row-value" style={{ minWidth: 34 }}>{m.unit}</span>
                  </div>
                ))}
                <Row title="Use the Food's Numbers" tone="tinted" chevron={false} onClick={() => { setOwn(null); setKcalTyped(false); }} />
              </List>
            </Section>
          ) : (
            <>
              <Nutrition per100={per100} grams={grams} drinks={showDrinks} />
              {!adding && (
                <div style={{ margin: "-12px 0 22px", textAlign: "right" }}>
                  <button type="button" className="button small tinted" onClick={() => {
                    const f = grams / 100;
                    const r1 = (x: number) => String(Math.round(x * f * 10) / 10);
                    setOwn({ protein: r1(per100.protein), carbs: r1(per100.carbs), fat: r1(per100.fat), kcal: String(Math.round(per100.kcal * f)) });
                    setKcalTyped(false);
                  }}>Edit Nutrients</button>
                </div>
              )}
            </>
          )}

          <Section header="Amount">
            <List>
              <div className="row">
                <span className="row-main"><span className="row-title">Grams</span></span>
                <input className="field num" type="number" inputMode="decimal" min={1} max={5000} aria-label="Grams"
                  value={Number.isFinite(grams) ? grams : ""} onChange={(e) => { setGrams(Number(e.target.value)); setPortion(""); }}
                  style={{ maxWidth: 90 }} />
                <Stepper label="grams" onMinus={() => { setGrams((g) => Math.max(step, Math.round((g - step) / step) * step)); setPortion(""); }}
                  onPlus={() => { setGrams((g) => Math.round((g + step) / step) * step); setPortion(""); }} />
              </div>
              {(servings.length > 0 || aiGrams) && (
                <div className="row" style={{ display: "block" }}>
                  <div className="chips">
                    {aiGrams ? [0.5, 1, 1.5, 2].map((x) => (
                      <button key={x} type="button" className="chip"
                        aria-pressed={grams === Math.round(aiGrams * x) && !servings.some((s) => s.name === portion)}
                        onClick={() => { setGrams(Math.round(aiGrams * x)); setPortion(""); }}>
                        {x === 1 ? "As read" : `${x}×`}
                      </button>
                    )) : null}
                    {servings.map((s) => (
                      <button key={s.name} type="button" className="chip" aria-pressed={portion === s.name}
                        onClick={() => { setGrams(s.grams); setPortion(s.name); }}>
                        {s.name} · {whole(s.grams)} g
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </List>
          </Section>

          <Section header="Food" footer={item?.basis === "owner" && !own
            ? "Its nutrients are your own numbers. Not Right? has the AI read it again."
            : item?.basis === "label"
            ? "From the product's nutrition label, looked up online. If it's the wrong product, say so under Not Right?, or use the AI's estimate."
            : food
            ? `${whole(food.kcal)} kcal per 100 g, from the ${sourceName(food.id)}, which the dashboard no longer uses.`
            : "The AI's own estimate. Edit Nutrients to put in the numbers yourself, or say what's different under Not Right?."}>
            <List>
              <Row title={food?.name ?? item?.name ?? ""} sub={item?.basis === "label" ? "Nutrition label" : item?.basis === "owner" ? "Your numbers" : sourceName(food?.id ?? null)} />
              {item?.basis === "label" && item.label_url && (
                <a className="row tinted" href={item.label_url} target="_blank" rel="noopener noreferrer">
                  <span className="row-main"><span className="row-title">Open Label</span>
                    <span className="row-sub">{hostOf(item.label_url)}</span></span>
                </a>
              )}
              {(item?.basis === "table" || item?.basis === "label") && item.ai_grams !== null && (
                <Row title="Use the AI's Estimate" tone="tinted" onClick={useEstimate} chevron={false} />
              )}
            </List>
          </Section>

          {!adding && (
            <Section header="Why These Numbers" footer={why ? "The AI's account of how these numbers were worked out." : undefined}>
              <List>
                {why ? (
                  <div className="row"><span className="row-main"><ItemWhy why={why.why} doubt={why.doubt} /></span></div>
                ) : (
                  <Row title={explaining ? "Working It Out…" : "Explain"} tone="tinted" chevron={false} disabled={explaining}
                    onClick={explainItem} trailing={explaining ? <Spinner label="Working it out" /> : undefined} />
                )}
              </List>
            </Section>
          )}

          {!adding && (
            <Section header="Not Right?" footer="The AI reads this item again with what you say (and the photo). Undo puts it back as it was.">
              <List>
                <div className="row">
                  <textarea className="field" aria-label="What's different?" value={correction} rows={2}
                    onChange={(e) => setCorrection(e.target.value)} placeholder="What's different? For example: it was lentil soup, about 2 bowls" />
                </div>
                <Row title={redoing ? "Redoing… about half a minute" : "Redo Item"} tone="tinted" chevron={false}
                  disabled={redoing || !correction.trim()} onClick={redo} trailing={redoing ? <Spinner label="Redoing" /> : undefined} />
              </List>
            </Section>
          )}

          {!adding && (
            <Section>
              <List><Row title="Remove Item" tone="destructive" onClick={remove} chevron={false} /></List>
            </Section>
          )}
        </>
      )}
    </Sheet>
  );
}
