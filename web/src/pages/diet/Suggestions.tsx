import { useState } from "react";
import { problemText } from "../../api/client";
import { useToast } from "../../components/Controls";
import { List, Row, Section } from "../../components/List";
import { withOffset } from "../../lib/dates";
import { whole } from "../../lib/format";

export type Suggestion = { name: string; portion: string; kcal: number; protein: number; carbs: number; fat: number; why: string };

/** Meal ideas that fit what's left. "Log" saves one as a meal (Codex then reads it like any note). */
export function Suggestions({ list, onLogged }: { list: Suggestion[]; onLogged: () => void }) {
  const [logged, setLogged] = useState<Set<string>>(new Set());
  const toast = useToast();

  async function log(s: Suggestion) {
    const form = new FormData();
    form.set("eaten_at", withOffset(new Date()));
    form.set("note", `${s.name}, ${s.portion}`);
    const r = await fetch("/api/diet/meals", { method: "POST", body: form, headers: { "X-Hobbes": "1" } });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) { toast({ text: problemText(body, "Couldn't log it.") }); return; }
    setLogged((x) => new Set(x).add(s.name));
    toast({ text: `${s.name} logged; reading it now` });
    onLogged();
  }

  return (
    <Section header="Suggested meals" footer="From what's left today and what you usually eat. Logging one reads it like any note, so you can adjust it after.">
      <List>
        {list.map((s) => (
          <Row key={s.name}
            title={s.name}
            sub={<>
              <span className="num">{s.portion} · {whole(s.kcal)} kcal · {whole(s.protein)} g protein · {whole(s.carbs)} g carbs · {whole(s.fat)} g fat</span>
              <br /><span className="tertiary-text">{s.why}</span>
            </>}
            trailing={
              <button type="button" className="button small tinted" disabled={logged.has(s.name)} onClick={() => log(s)}>
                {logged.has(s.name) ? "Logged" : "Log"}
              </button>
            } />
        ))}
      </List>
    </Section>
  );
}
