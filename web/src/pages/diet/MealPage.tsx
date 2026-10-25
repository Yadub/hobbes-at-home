import { useEffect, useState } from "react";
import { api, problemText, useLoad } from "../../api/client";
import type { Item } from "../../api/client";
import { Segmented, useToast } from "../../components/Controls";
import { PlusIcon, Spinner } from "../../components/Icons";
import { List, Row, Section } from "../../components/List";
import { Page } from "../../components/Page";
import { dayLabel, today, withOffset } from "../../lib/dates";
import { oneDp, whole } from "../../lib/format";
import { go } from "../../router";
import { drinksText } from "./drinksText";
import { ItemSheet } from "./ItemSheet";
import { WhySheet } from "./Why";

type Slot = "breakfast" | "lunch" | "snack" | "dinner";
const SLOTS: { value: Slot; label: string }[] = [
  { value: "breakfast", label: "Breakfast" }, { value: "lunch", label: "Lunch" },
  { value: "snack", label: "Snack" }, { value: "dinner", label: "Dinner" },
];

/** The clock time in an ISO string, for the datetime-local input. */
const localPart = (iso: string) => iso.slice(0, 16);

export function MealPage({ id }: { id: number }) {
  const m = useLoad(() => api.GET("/api/diet/meals/{meal_id}", { params: { path: { meal_id: id } } }), [id]);
  const drinks = useLoad(() => api.GET("/api/diet/drinks", { params: { query: { day: today() } } }), []);
  const showDrinks = drinks.data?.enabled ?? false;
  const [editing, setEditing] = useState<{ open: boolean; item: Item | null }>({ open: false, item: null });
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [why, setWhy] = useState(false);
  const toast = useToast();
  const meal = m.data;
  const savedNote = meal?.note;
  useEffect(() => { setNote(savedNote ?? ""); }, [savedNote]);
  const dayUrl = meal ? (meal.day === today() ? "/diet" : `/diet?day=${meal.day}`) : "/diet";

  useEffect(() => {
    if (meal?.status !== "analysing") return;
    const t = window.setInterval(m.reload, 2500);
    return () => window.clearInterval(t);
  }, [meal?.status, m.reload]);

  async function patch(body: { slot?: Slot; eaten_at?: string }) {
    const { data, error } = await api.PATCH("/api/diet/meals/{meal_id}", { params: { path: { meal_id: id } }, body });
    if (error) { toast({ text: problemText(error) }); return; }
    toast({ text: "Meal updated", undo: async () => { await api.POST("/api/undo/{change_id}", { params: { path: { change_id: data.change_id } } }); m.reload(); } });
    m.reload();
  }

  /** Save the changed note, then read the meal again with it. */
  async function noteAndRead() {
    setBusy("note");
    try {
      const saved = await api.PATCH("/api/diet/meals/{meal_id}", { params: { path: { meal_id: id } }, body: { note: note.trim() } });
      if (saved.error) throw new Error(problemText(saved.error));
      const read = await api.POST("/api/diet/meals/{meal_id}/analyse", { params: { path: { meal_id: id } } });
      if (read.error) throw new Error(problemText(read.error));
      toast({ text: "Reading it again with your note" });
      m.reload();
    } catch (e) {
      toast({ text: e instanceof Error ? e.message : "That didn't work." });
    } finally {
      setBusy(null);
    }
  }

  async function action(kind: "again" | "read" | "remove") {
    setBusy(kind);
    try {
      if (kind === "again") {
        const { data, error } = await api.POST("/api/diet/meals/{meal_id}/again", { params: { path: { meal_id: id } }, body: { eaten_at: withOffset(new Date()) } });
        if (error) throw new Error(problemText(error));
        toast({ text: "Logged again for now" });
        go(`/diet/meal/${data.meal_id}`, { replace: true });
      } else if (kind === "read") {
        const { error } = await api.POST("/api/diet/meals/{meal_id}/analyse", { params: { path: { meal_id: id } } });
        if (error) throw new Error(problemText(error));
        m.reload();
      } else {
        const { data, error } = await api.DELETE("/api/diet/meals/{meal_id}", { params: { path: { meal_id: id } } });
        if (error) throw new Error(problemText(error));
        toast({ text: "Meal removed", undo: async () => { await api.POST("/api/undo/{change_id}", { params: { path: { change_id: data.change_id } } }); go(`/diet/meal/${id}`); } });
        go(dayUrl, { replace: true });
      }
    } catch (e) {
      toast({ text: e instanceof Error ? e.message : "That didn't work." });
    } finally {
      setBusy(null);
    }
  }

  if (m.error) return <Page title="Meal" backTo="/diet" backLabel="Diet"><div className="notice error">{m.error}</div></Page>;
  if (!meal) return <Page title="Meal" backTo="/diet" backLabel="Diet"><div /></Page>;

  const estimates = meal.items.filter((i) => i.basis === "estimate").length;
  const noteChanged = note.trim() !== meal.note.trim();

  return (
    <Page title={meal.title || "Meal"} eyebrow={dayLabel(meal.day, { long: true })} backTo={dayUrl} backLabel="Diet">
      {meal.photos > 0 && (
        <div style={{ display: "flex", gap: 10, overflowX: "auto", scrollSnapType: "x mandatory", marginBottom: 16 }}>
          {Array.from({ length: meal.photos }, (_, n) => (
            <img key={n} src={`/api/diet/meals/${meal.id}/photos/${n}`} alt={`Photo ${n + 1} of the meal`}
              style={{ width: meal.photos === 1 ? "100%" : "85%", aspectRatio: "4 / 3", objectFit: "cover", borderRadius: 12, flex: "none", scrollSnapAlign: "start", background: "var(--fill-3)" }} />
          ))}
        </div>
      )}

      {meal.status === "analysing" ? (
        <div className="card" style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 28 }}>
          <Spinner label="Reading" /><span className="subhead">Reading the meal… this takes about half a minute.</span>
        </div>
      ) : meal.status === "failed" ? (
        <div className="notice error" style={{ marginBottom: 28 }}>{meal.error ?? "This couldn't be read."}</div>
      ) : (
        <div className="card" style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr 1fr 1fr", gap: 8, marginBottom: 28 }}>
          <div><div className="caption secondary">Energy</div><div className="value small">{whole(meal.totals.kcal)}<span className="unit">kcal</span></div></div>
          <div><div className="caption secondary">Protein</div><div className="value small">{oneDp(meal.totals.protein)}<span className="unit">g</span></div></div>
          <div><div className="caption secondary">Carbs</div><div className="value small">{oneDp(meal.totals.carbs)}<span className="unit">g</span></div></div>
          <div><div className="caption secondary">Fat</div><div className="value small">{oneDp(meal.totals.fat)}<span className="unit">g</span></div></div>
          {showDrinks && drinksText(meal.totals.caffeine, meal.totals.alcohol) && (
            <span className="footnote secondary" style={{ gridColumn: "1 / -1" }}>
              {(() => { const t = drinksText(meal.totals.caffeine, meal.totals.alcohol).slice(3); return t.charAt(0).toUpperCase() + t.slice(1); })()}
            </span>
          )}
        </div>
      )}

      <Section header="Items" footer={estimates
        ? `${estimates === 1 ? "One item uses" : `${estimates} items use`} the AI's own estimate. Tap an item to check its amount or numbers.`
        : "Tap an item to change its amount or numbers."}>
        <List>
          {meal.items.map((i) => (
            <Row key={i.id} title={i.name}
              sub={`${i.portion ? `${i.portion} · ` : ""}${whole(i.grams)} g${i.basis === "estimate" ? " · AI estimate" : i.basis === "owner" ? " · your numbers" : i.basis === "label" ? " · label" : ""}${showDrinks ? drinksText(i.caffeine, i.alcohol) : ""}`}
              value={`${whole(i.kcal)} kcal`} onClick={() => setEditing({ open: true, item: i })} chevron />
          ))}
          <Row title="Add Item" tone="tinted" icon={<PlusIcon />} tile="var(--tint)" onClick={() => setEditing({ open: true, item: null })} chevron={false} />
        </List>
      </Section>

      {meal.status === "ready" && meal.items.length > 0 && (
        <Section>
          <List>
            <Row title="Why These Numbers?" tone="tinted" onClick={() => setWhy(true)} chevron={false}
              sub="The AI explains the amounts and where each item's values come from." />
          </List>
        </Section>
      )}

      <Section header="Your Note" footer={noteChanged
        ? "Read Again replaces the items with a new reading of the photo and this note; edits you made to items are replaced."
        : "Change it to correct the whole meal, for example “3 slices, not 2”, then read it again. To fix one item, tap it."}>
        <List>
          <div className="row">
            <textarea className="field" aria-label="Your note" value={note} rows={2} onChange={(e) => setNote(e.target.value)}
              placeholder="What did you eat? For example: 2 slices of toast, scrambled eggs" />
          </div>
          {noteChanged && (
            <Row title={busy === "note" ? "Reading Again…" : "Save and Read Again"} tone="tinted" chevron={false}
              disabled={!!busy || meal.status === "analysing" || (!note.trim() && !meal.photos)} onClick={noteAndRead} />
          )}
        </List>
      </Section>

      <Section header="When">
        <List>
          <div className="row">
            <span className="row-main"><span className="row-title">Time</span></span>
            <input className="field" type="datetime-local" aria-label="Time" defaultValue={localPart(meal.eaten_at)}
              onBlur={(e) => { if (e.target.value && e.target.value !== localPart(meal.eaten_at)) patch({ eaten_at: withOffset(new Date(e.target.value)) }); }} />
          </div>
          <div className="row" style={{ display: "block" }}>
            <Segmented label="Meal" value={meal.slot as Slot} options={SLOTS} onChange={(v) => patch({ slot: v })} />
          </div>
        </List>
      </Section>

      <Section>
        <List>
          <Row title="Log Again Now" tone="tinted" onClick={() => action("again")} disabled={!!busy} chevron={false} />
          <Row title="Read Again" tone="tinted" onClick={() => action("read")} disabled={!!busy || meal.status === "analysing"} chevron={false}
            sub={meal.note || meal.photos ? "Asks the AI again; your edits to items are replaced." : undefined} />
        </List>
      </Section>
      <Section footer="Removed meals can be brought back with Undo.">
        <List><Row title="Remove Meal" tone="destructive" onClick={() => action("remove")} disabled={!!busy} chevron={false} /></List>
      </Section>

      <ItemSheet open={editing.open} item={editing.item} mealId={meal.id} showDrinks={showDrinks} onClose={() => setEditing({ open: false, item: null })} onDone={m.reload} />
      <WhySheet open={why} mealId={meal.id} items={meal.items} onClose={() => setWhy(false)} />
    </Page>
  );
}
