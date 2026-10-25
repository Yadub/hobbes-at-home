import { useEffect, useState } from "react";
import { api, problemText, useLoad } from "../../api/client";
import type { AssistantFact, AssistantSuggestion } from "../../api/client";
import { useToast } from "../../components/Controls";
import { ChevronRight, PlusIcon } from "../../components/Icons";
import { List, Row, Section } from "../../components/List";
import { Page } from "../../components/Page";
import { Sheet } from "../../components/Sheet";
import "./assistant.css";
import { LockSmallIcon } from "./icons";

type Topic = AssistantFact["topic"];
const TOPICS: { value: Topic; label: string }[] = [
  { value: "travel", label: "Travel" }, { value: "stays", label: "Hotels" }, { value: "budget", label: "Budgets" },
  { value: "payments", label: "Cards and rewards" }, { value: "bookings", label: "Where to book" },
  { value: "food", label: "Food" }, { value: "people", label: "People" }, { value: "ids", label: "Loyalty and IDs" },
  { value: "other", label: "Other" },
];

type Editing =
  | { mode: "new"; topic: Topic; label: string; secret: boolean; example: string }
  | { mode: "edit"; fact: AssistantFact };

function FactSheet({ editing, onClose, onSaved }: {
  editing: Editing | null; onClose: () => void; onSaved: (text: string, change: number | null | undefined) => void;
}) {
  const [topic, setTopic] = useState<Topic>("other");
  const [label, setLabel] = useState("");
  const [value, setValue] = useState("");
  const [secret, setSecret] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isNew = editing?.mode === "new";
  const fact = editing?.mode === "edit" ? editing.fact : null;

  useEffect(() => {
    if (!editing) return;
    setError(null);
    if (editing.mode === "new") {
      setTopic(editing.topic); setLabel(editing.label); setValue(""); setSecret(editing.secret);
    } else {
      setTopic(editing.fact.topic); setLabel(editing.fact.label); setValue(editing.fact.value); setSecret(editing.fact.secret);
    }
  }, [editing]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      if (isNew) {
        const { data, error: err } = await api.POST("/api/assistant/profile", { body: { topic, label, value, secret } });
        if (err) throw new Error(problemText(err));
        onSaved("Added", data.change_id);
      } else if (fact) {
        const body: { topic?: Topic; label?: string; value?: string } = { topic, label };
        if (!fact.secret || value.trim()) body.value = value;
        const { data, error: err } = await api.PATCH("/api/assistant/profile/{fact_id}", { params: { path: { fact_id: fact.id } }, body });
        if (err) throw new Error(problemText(err));
        onSaved("Saved", data.change_id);
      }
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!fact) return;
    setBusy(true);
    const { data, error: err } = await api.DELETE("/api/assistant/profile/{fact_id}", { params: { path: { fact_id: fact.id } } });
    setBusy(false);
    if (err) { setError(problemText(err)); return; }
    onSaved("Removed", data.change_id);
    onClose();
  }

  const canSave = label.trim().length > 0 && (value.trim().length > 0 || Boolean(fact?.secret));
  const example = editing?.mode === "new" ? editing.example : "";

  return (
    <Sheet open={editing !== null} title={isNew ? "Add to Profile" : "Edit"} onClose={onClose}
      action={{ label: isNew ? "Add" : "Save", onClick: save, disabled: !canSave, busy }}>
      {error && <div className="notice error" role="alert">{error}</div>}
      <Section>
        <List>
          <div className="row">
            <span className="row-main"><span className="row-title">Name</span></span>
            <input className="field" aria-label="Name" value={label} maxLength={60} placeholder="Home airport"
              onChange={(e) => setLabel(e.target.value)} />
          </div>
          <label className="row">
            <span className="row-main"><span className="row-title">Topic</span></span>
            <select className="field as-select" aria-label="Topic" value={topic} onChange={(e) => setTopic(e.target.value as Topic)}>
              {TOPICS.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
            </select>
            <ChevronRight />
          </label>
        </List>
      </Section>
      <Section footer={secret ? "Kept in the Mac's Keychain, not in the dashboard's catalog, and never sent to the AI. The assistant is only told you have it."
        : "In your own words; the assistant reads it before every job."}>
        <List>
          <div className="row">
            {secret ? (
              <input className="field left" type="password" autoComplete="off" aria-label="Value" value={value}
                placeholder={fact ? "Enter a new value to replace it" : "Value"} onChange={(e) => setValue(e.target.value)} />
            ) : (
              <textarea className="field" aria-label="Value" value={value} rows={3} maxLength={500}
                placeholder={example || "Value"} onChange={(e) => setValue(e.target.value)} />
            )}
          </div>
        </List>
      </Section>
      {isNew && (
        <Section>
          <List>
            <label className="row">
              <span className="row-main"><span className="row-title">Keep in the Keychain</span>
                <span className="row-sub">For passport and membership numbers</span></span>
              <input type="checkbox" role="switch" className="switch" checked={secret} onChange={(e) => setSecret(e.target.checked)} />
            </label>
          </List>
        </Section>
      )}
      {fact && (
        <Section footer="Removed facts can be brought back with Undo.">
          <List><Row title="Remove" tone="destructive" onClick={remove} disabled={busy} chevron={false} /></List>
        </Section>
      )}
    </Sheet>
  );
}

export function ProfilePage() {
  const p = useLoad(() => api.GET("/api/assistant/profile"));
  const [editing, setEditing] = useState<Editing | null>(null);
  const toast = useToast();
  const data = p.data;

  const undoable = (text: string, change: number | null | undefined) => toast({
    text,
    undo: change ? async () => { await api.POST("/api/undo/{change_id}", { params: { path: { change_id: change } } }); p.reload(); } : undefined,
  });

  async function decide(s: AssistantSuggestion, accept: boolean) {
    const path = { params: { path: { suggestion_id: s.id } } };
    const { data: done, error } = accept
      ? await api.POST("/api/assistant/suggestions/{suggestion_id}/accept", path)
      : await api.POST("/api/assistant/suggestions/{suggestion_id}/dismiss", path);
    if (error) { toast({ text: problemText(error) }); return; }
    undoable(accept ? "Added to your profile" : "Dismissed", done.change_id);
    p.reload();
  }

  return (
    <Page title="Profile" backTo="/assistant" backLabel="Hobbes AI">
      <p className="footnote secondary as-intro">
        The assistant reads this before every job, and states what it assumed when something isn't here.
      </p>
      {p.error && <div className="notice error">{p.error}</div>}

      {data && data.suggestions.length > 0 && (
        <Section header="Suggested by the assistant" footer="Nothing changes until you add them.">
          <List>
            {data.suggestions.map((s) => (
              <div key={s.id} className="row as-small-row">
                <span className="row-main">
                  <span className="row-title" style={{ whiteSpace: "normal" }}>{s.label}: {s.value}</span>
                  <span className="row-sub" style={{ whiteSpace: "normal" }}>{s.replaces ? `Instead of “${s.replaces}”. ` : ""}{s.why}</span>
                </span>
                <span className="as-inline-group">
                  <button type="button" className="as-inline quiet" onClick={() => decide(s, false)}>Dismiss</button>
                  <button type="button" className="as-inline" onClick={() => decide(s, true)}>Add</button>
                </span>
              </div>
            ))}
          </List>
        </Section>
      )}

      {data && TOPICS.map((t) => {
        const facts = data.facts.filter((f) => f.topic === t.value);
        const prompts = data.prompts.filter((x) => x.topic === t.value);
        if (!facts.length && !prompts.length) return null;
        return (
          <Section key={t.value} header={t.label}>
            <List>
              {facts.map((f) => (
                <button key={f.id} type="button" className="row as-fact" onClick={() => setEditing({ mode: "edit", fact: f })}>
                  <span className="row-main">
                    <span className="as-fact-label">{f.label}</span>
                    {f.secret
                      ? <span className="as-fact-value secret"><LockSmallIcon />In the Keychain</span>
                      : <span className="as-fact-value">{f.value}</span>}
                  </span>
                  <ChevronRight />
                </button>
              ))}
              {prompts.map((x) => (
                <Row key={x.label} title={`Add ${x.label.toLowerCase()}`} tone="tinted" chevron={false}
                  onClick={() => setEditing({ mode: "new", topic: x.topic, label: x.label, secret: x.secret, example: x.example })} />
              ))}
            </List>
          </Section>
        );
      })}

      {data && (
        <Section footer="Secret items, such as your passport number, are kept in the Mac's Keychain and never sent to the AI.">
          <List>
            <Row title="Add Something Else" tone="tinted" icon={<PlusIcon />} tile="var(--tint)" chevron={false}
              onClick={() => setEditing({ mode: "new", topic: "other", label: "", secret: false, example: "" })} />
          </List>
        </Section>
      )}

      <FactSheet editing={editing} onClose={() => setEditing(null)} onSaved={(text, change) => { undoable(text, change); p.reload(); }} />
    </Page>
  );
}
