import { useEffect, useState } from "react";
import { api, problemText, waitForJob } from "../../api/client";
import type { Explanation, Item } from "../../api/client";
import { Spinner } from "../../components/Icons";
import { List, Section } from "../../components/List";
import { Sheet } from "../../components/Sheet";

/** Why these numbers (diet/explain.py): the kept explanation, or one worked out now (about half a minute). */
export async function explainMeal(mealId: number): Promise<Explanation> {
  const { data, error } = await api.POST("/api/diet/meals/{meal_id}/explain", { params: { path: { meal_id: mealId } } });
  if (error) throw new Error(problemText(error));
  if (data.explanation) return data.explanation;
  const job = await waitForJob(data.job_id ?? 0);
  if (job.status === "failed") throw new Error("The AI couldn't explain it this time. Try again in a minute.");
  const got = await api.GET("/api/diet/meals/{meal_id}/explanation", { params: { path: { meal_id: mealId } } });
  if (got.error || !got.data) throw new Error("The meal changed while it was being explained. Try again.");
  return got.data;
}

/** One item's part of an explanation: how its numbers came about, and what might be off. */
export function ItemWhy({ why, doubt }: { why: string; doubt: string }) {
  return (
    <>
      <span className="row-sub" style={{ whiteSpace: "normal", color: "var(--label)" }}>{why}</span>
      {doubt && <span className="row-sub" style={{ whiteSpace: "normal", marginTop: 4 }}>{doubt}</span>}
    </>
  );
}

/** The whole meal's explanation, in a sheet. */
export function WhySheet({ open, mealId, items, onClose }: { open: boolean; mealId: number; items: Item[]; onClose: () => void }) {
  const [e, setE] = useState<Explanation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setE(null);
    setError(null);
    explainMeal(mealId).then((x) => live && setE(x)).catch((x) => live && setError(x instanceof Error ? x.message : "That didn't work."));
    return () => { live = false; };
  }, [open, mealId]);

  const name = new Map(items.map((i) => [i.id, i.name]));
  return (
    <Sheet open={open} title="Why These Numbers" onClose={onClose} cancelLabel="Done">
      {error && <div className="notice error" role="alert">{error}</div>}
      {!e && !error && (
        <div className="card" style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Spinner label="Working it out" /><span className="subhead">Working it out… this takes about half a minute.</span>
        </div>
      )}
      {e && (
        <>
          <p className="body" style={{ margin: "0 4px 18px" }}>{e.summary}</p>
          <Section footer="The AI's account of numbers that were already worked out: from the photo and your note, the food tables, and any changes you made.">
            <List>
              {e.items.map((x) => (
                <div key={x.item_id} className="row">
                  <span className="row-main">
                    <span className="row-title">{name.get(x.item_id) ?? "Item"}</span>
                    <ItemWhy why={x.why} doubt={x.doubt} />
                  </span>
                </div>
              ))}
            </List>
          </Section>
        </>
      )}
    </Sheet>
  );
}
