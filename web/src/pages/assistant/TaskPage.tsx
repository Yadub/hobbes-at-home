import { useEffect, useRef, useState } from "react";
import { api, problemText, useLoad } from "../../api/client";
import type { AssistantResult, AssistantSuggestion, AssistantTask } from "../../api/client";
import { useToast } from "../../components/Controls";
import { Spinner } from "../../components/Icons";
import { List, Row, Section } from "../../components/List";
import { Page } from "../../components/Page";
import { Sheet } from "../../components/Sheet";
import { go, useQuery } from "../../router";
import { aheadWhen, Choices, Composer, logWhen, shortWhen, STATUS_NAMES } from "./common";
import { ArrowUpRightIcon, CheckCircleIcon, EyeIcon, RepeatIcon } from "./icons";
import { Md } from "./Md";
import { Share } from "./Share";

type Step = AssistantTask["steps"][number];

function stepText(s: Step): { text: string; cls: string } {
  switch (s.kind) {
    case "asked": return { text: `You asked: ${s.text}`, cls: "owner" };
    case "answer": return { text: `You answered: ${s.text}`, cls: "owner" };
    case "refine": return { text: `You asked for: ${s.text}`, cls: "owner" };
    case "question": return { text: `Asked you: ${s.text}`, cls: "" };
    case "failed": return { text: s.text, cls: "bad" };
    case "changed": return { text: `Changed: ${s.text}`, cls: "owner" };
    case "started": case "retry": case "stopped": case "unchanged": case "watch": return { text: s.text, cls: "quiet" };
    default: return { text: s.text, cls: "" };
  }
}

/** One reply in the thread: the text, then any options as a compact list. `full` (the latest reply only) adds
 *  why the pick, what it assumed (tap one to change it) and the next steps. */
function Reply({ r, full, busy, onChange }: { r: AssistantResult; full: boolean; busy: boolean; onChange: (a: string) => void }) {
  const pick = r.recommended !== null && r.recommended !== undefined ? r.options[r.recommended] : undefined;
  return (
    <div className="as-msg ai">
      {r.summary && <Md text={r.summary} />}
      {r.options.length > 0 && (
        <div className="as-opts">
          {r.options.map((o, i) => {
            const inner = (
              <>
                <span className="as-opt-main">
                  <span className="as-opt-title">{o.title}{r.recommended === i && <span className="as-pick">Pick</span>}</span>
                  {(o.when || o.why) && <span className="as-opt-sub">{[o.when, o.why].filter(Boolean).join(" · ")}</span>}
                </span>
                {o.price && <span className="as-opt-price">{o.price}</span>}
                {o.link && <ArrowUpRightIcon />}
              </>
            );
            return o.link
              ? <a key={`${i}-${o.title}`} className="as-opt" href={o.link} target="_blank" rel="noopener noreferrer">{inner}</a>
              : <div key={`${i}-${o.title}`} className="as-opt">{inner}</div>;
          })}
        </div>
      )}
      {full && pick && r.recommendation && <p className="as-msg-note"><strong>Pick:</strong> {r.recommendation}</p>}
      {full && r.options.length > 0 && <p className="as-msg-foot">Prices change; check on the site before booking.</p>}
      {full && r.assumptions.length > 0 && (
        <div className="as-assumed">
          <span className="as-msg-foot">Assumed (tap to change)</span>
          {r.assumptions.map((a) => (
            <button key={a} type="button" className="as-chip" disabled={busy} onClick={() => onChange(a)}>{a}</button>
          ))}
        </div>
      )}
      {full && r.actions.length > 0 && (
        <div className="as-next">
          {r.actions.map((a, i) => (a.link
            ? <a key={i} href={a.link} target="_blank" rel="noopener noreferrer">{a.label}<ArrowUpRightIcon /></a>
            : <span key={i}>{a.label}</span>))}
        </div>
      )}
    </div>
  );
}

function Suggestions({ items, onDone }: { items: AssistantSuggestion[]; onDone: () => void }) {
  const toast = useToast();
  async function decide(s: AssistantSuggestion, accept: boolean) {
    const path = { params: { path: { suggestion_id: s.id } } };
    const { data, error } = accept
      ? await api.POST("/api/assistant/suggestions/{suggestion_id}/accept", path)
      : await api.POST("/api/assistant/suggestions/{suggestion_id}/dismiss", path);
    if (error) { toast({ text: problemText(error) }); return; }
    const change = data.change_id;
    toast({
      text: accept ? "Added to your profile" : "Dismissed",
      undo: change ? async () => { await api.POST("/api/undo/{change_id}", { params: { path: { change_id: change } } }); onDone(); } : undefined,
    });
    onDone();
  }
  return (
    <List>
      {items.map((s) => (
        <div key={s.id} className="row as-small-row">
          <span className="row-main">
            <span className="row-title" style={{ whiteSpace: "normal" }}>{s.label}: {s.value}</span>
            <span className="row-sub" style={{ whiteSpace: "normal" }}>
              {s.replaces ? `Instead of “${s.replaces}”. ` : ""}{s.why}
            </span>
          </span>
          <span className="as-inline-group">
            <button type="button" className="as-inline quiet" onClick={() => decide(s, false)}>Dismiss</button>
            <button type="button" className="as-inline" onClick={() => decide(s, true)}>Add</button>
          </span>
        </div>
      ))}
    </List>
  );
}

export function TaskPage({ id }: { id: number }) {
  const t = useLoad(() => api.GET("/api/assistant/tasks/{task_id}", { params: { path: { task_id: id } } }), [id]);
  const [busy, setBusy] = useState(false);
  const [changing, setChanging] = useState<string | null>(null);
  const [instead, setInstead] = useState("");
  const [watchSheet, setWatchSheet] = useState(false);
  const answerBox = useRef<HTMLTextAreaElement>(null);
  const query = useQuery();
  const toast = useToast();
  const task = t.data;
  const working = task?.status === "working";

  useEffect(() => {
    if (!working) return;
    const timer = window.setInterval(t.reload, 2500);
    return () => window.clearInterval(timer);
  }, [working, t.reload]);

  // Opening the job is seeing its latest change.
  const unseen = Boolean(task?.watch?.unseen);
  useEffect(() => {
    if (unseen) void api.POST("/api/assistant/tasks/{task_id}/seen", { params: { path: { task_id: id } } });
  }, [unseen, id]);

  const wantsAnswer = query.get("answer") === "1";
  useEffect(() => {
    if (wantsAnswer && task) answerBox.current?.focus();
  }, [wantsAnswer, Boolean(task)]);

  async function send(text: string): Promise<boolean> {
    const { error } = await api.POST("/api/assistant/tasks/{task_id}/messages", {
      params: { path: { task_id: id } }, body: { text },
    });
    if (error) { toast({ text: problemText(error) }); return false; }
    toast({ text: working ? "Added. It'll take it into account next." : "Sent. It's looking again." });
    t.reload();
    return true;
  }

  async function act(kind: "stop" | "retry" | "remove") {
    setBusy(true);
    try {
      const path = { params: { path: { task_id: id } } };
      if (kind === "remove") {
        const { data, error } = await api.DELETE("/api/assistant/tasks/{task_id}", path);
        if (error) throw new Error(problemText(error));
        const change = data.change_id;
        toast({ text: "Task removed", undo: change ? async () => { await api.POST("/api/undo/{change_id}", { params: { path: { change_id: change } } }); go(`/assistant/task/${id}`); } : undefined });
        go("/assistant", { replace: true });
        return;
      }
      const { error } = kind === "stop"
        ? await api.POST("/api/assistant/tasks/{task_id}/stop", path)
        : await api.POST("/api/assistant/tasks/{task_id}/retry", path);
      if (error) throw new Error(problemText(error));
      t.reload();
    } catch (e) {
      toast({ text: e instanceof Error ? e.message : "That didn't work." });
    } finally {
      setBusy(false);
    }
  }

  async function watch(every: "daily" | "weekly" | null) {
    setBusy(true);
    const path = { params: { path: { task_id: id } } };
    const { error } = every
      ? await api.PUT("/api/assistant/tasks/{task_id}/watch", { ...path, body: { every } })
      : await api.DELETE("/api/assistant/tasks/{task_id}/watch", path);
    setBusy(false);
    setWatchSheet(false);
    if (error) { toast({ text: problemText(error) }); return; }
    toast({ text: every ? `Watching it ${every}. It'll tell you what changes.` : task?.watch?.kind === "routine" ? "Stopped the routine" : "Stopped watching" });
    t.reload();
  }

  async function lookNow() {
    setBusy(true);
    const { error } = await api.POST("/api/assistant/tasks/{task_id}/watch/check", { params: { path: { task_id: id } } });
    setBusy(false);
    if (error) { toast({ text: problemText(error) }); return; }
    t.reload();
  }

  async function sendChange() {
    if (!changing || !instead.trim()) return;
    setBusy(true);
    const ok = await send(`Change the assumption “${changing}”: ${instead.trim()}`);
    setBusy(false);
    if (ok) { setChanging(null); setInstead(""); }
  }

  if (t.error) return <Page title="Task" backTo="/assistant" backLabel="Hobbes AI"><div className="notice error">{t.error}</div></Page>;
  if (!task) return <Page title="Task" backTo="/assistant" backLabel="Hobbes AI"><div /></Page>;

  const r = task.result;
  const routine = task.watch?.kind === "routine";
  const lastResult = [...task.steps].reverse().find((s) => s.kind === "result")?.id;
  const lastQuestion = [...task.steps].reverse().find((s) => s.kind === "question")?.id;
  const eyebrow = task.status === "done" ? `Done · ${shortWhen(task.finished_at ?? task.updated_at)}` : STATUS_NAMES[task.status];

  return (
    <Page title={task.title} eyebrow={eyebrow} backTo="/assistant" backLabel="Hobbes AI"
      trailing={working ? <button className="bar-button" onClick={() => act("stop")} disabled={busy}>Stop</button> : undefined}>
      <div className="as-thread">
        {task.steps.map((s) => {
          switch (s.kind) {
            case "asked": case "refine": case "answer":
              return <div key={s.id} className="as-msg me">{s.text}</div>;
            case "result":
              return s.result ? (
                <Reply key={s.id} r={s.id === lastResult && r ? r : s.result} full={s.id === lastResult} busy={busy}
                  onChange={(a) => { setChanging(a); setInstead(""); }} />
              ) : null;
            case "question":
              return (
                <div key={s.id} className="as-msg ai">
                  <p>{s.text}</p>
                  {s.id === lastQuestion && task.status === "needs_you" && task.question && (
                    <Choices question={task.question} busy={busy} onChoose={async (c) => { setBusy(true); await send(c); setBusy(false); }} />
                  )}
                </div>
              );
            case "changed":
              return <div key={s.id} className="as-msg ai"><p><strong>Changed:</strong> {s.text}</p></div>;
            case "failed":
              return <div key={s.id} className="as-msg ai bad"><p>{s.text}</p></div>;
            case "stopped":
              return <p key={s.id} className="as-thread-note">{s.text}</p>;
            default:
              return null;  // its work: under Show Its Work
          }
        })}
        {working && (
          <div className="as-msg ai as-msg-working"><Spinner label="Working" /><span>{task.latest ?? "Hobbes is fetching"}…</span></div>
        )}
      </div>

      {task.status === "failed" && (
        <div className="as-thread-actions">
          <button type="button" className="button small tinted" onClick={() => act("retry")} disabled={busy}>Try Again</button>
        </div>
      )}
      {task.status === "cancelled" && (
        <div className="as-thread-actions">
          <button type="button" className="button small tinted" onClick={() => act("retry")} disabled={busy}>Carry On</button>
        </div>
      )}

      <Section footer={working ? "It's working; what you add is used in its next round." : undefined}>
        <Composer inputRef={answerBox} button="Send" onSend={send}
          placeholder={task.status === "needs_you" ? "Answer in your own words" : working ? "Add something…" : "Reply…"} />
      </Section>

      {r && (r.options.length > 0 || r.summary) && task.status !== "working" && <Share task={task} />}

      {task.watch && routine ? (
        <Section header="Routine"
          footer={`Next run ${aheadWhen(task.watch.next_at)}. To change it, say so below (“make it Fridays”, “stop the routine”). Each run uses a little of the Codex allowance.`}>
          <List>
            <Row icon={<RepeatIcon />} tile="var(--assistant)" title="Runs" value={task.watch.when ?? ""} chevron={false} />
            <Row title="Run Now" tone="tinted" onClick={lookNow} chevron={false}
              disabled={busy || working || task.status === "needs_you"} />
            <Row title="Stop Routine" tone="destructive" onClick={() => watch(null)} disabled={busy} chevron={false} />
          </List>
        </Section>
      ) : task.watch ? (
        <Section header="Watching"
          footer={`Looks again ${aheadWhen(task.watch.next_at)}${task.watch.last_check_at ? `; last looked ${logWhen(task.watch.last_check_at)}` : ""}. Each look uses a little of the Codex allowance.`}>
          <List>
            <Row icon={<EyeIcon />} tile="var(--assistant)" title="How Often" value={task.watch.every === "daily" ? "Every Day" : "Every Week"}
              onClick={() => setWatchSheet(true)} chevron />
            {task.watch.condition && (
              <Row title={<span style={{ whiteSpace: "normal" }}>Only when there's {task.watch.condition}</span>}
                sub="To change it, say so below" chevron={false} />
            )}
            <Row title="Look Again Now" tone="tinted" onClick={lookNow} chevron={false}
              disabled={busy || working || task.status === "needs_you"} />
            <Row title="Stop Watching" tone="destructive" onClick={() => watch(null)} disabled={busy} chevron={false} />
          </List>
        </Section>
      ) : task.status === "done" && r ? (
        <Section footer="It looks again on a schedule and tells you when something changes: a fare that fell, a table that opened up. Or say it below: “tell me if it drops under 1,000”, “do this every Friday”.">
          <List>
            <Row icon={<EyeIcon />} tile="var(--assistant)" title="Watch for Changes" onClick={() => setWatchSheet(true)} chevron />
          </List>
        </Section>
      ) : null}

      {task.suggestions.length > 0 && (
        <Section header="For your profile" footer="Preferences it noticed. Add them and it uses them from the next job on.">
          <Suggestions items={task.suggestions} onDone={t.reload} />
        </Section>
      )}

      <details className="as-work">
        <summary>Show Its Work</summary>
        <div className="as-log">
          <List>
            {task.steps.map((s) => {
              const { text, cls } = stepText(s);
              return (
                <div key={s.id} className={`row ${cls}`}>
                  <span className="row-main"><span className="as-log-text">{text}</span></span>
                  <span className="row-value">{logWhen(s.at)}</span>
                </div>
              );
            })}
          </List>
        </div>
      </details>

      <Section footer="Removed tasks can be brought back with Undo.">
        <List><Row title="Remove Task" tone="destructive" onClick={() => act("remove")} disabled={busy} chevron={false} /></List>
      </Section>

      <Sheet open={watchSheet} title="Watch for Changes" onClose={() => setWatchSheet(false)}>
        <p className="subhead secondary as-sheet-note">It searches again and compares with this result. Changes show in Hobbes AI and in your morning brief.</p>
        <Section>
          <List>
            <Row title="Every Day" sub="Fares and prices that move daily" onClick={() => watch("daily")} disabled={busy}
              chevron={false} trailing={task.watch?.every === "daily" ? <CheckCircleIcon /> : undefined} />
            <Row title="Every Week" sub="Things that change slowly: availability, offers, rules" onClick={() => watch("weekly")} disabled={busy}
              chevron={false} trailing={task.watch?.every === "weekly" ? <CheckCircleIcon /> : undefined} />
          </List>
        </Section>
      </Sheet>

      <Sheet open={changing !== null} title="Change Assumption" onClose={() => setChanging(null)}
        action={{ label: "Send", onClick: sendChange, disabled: !instead.trim(), busy }}>
        <p className="subhead secondary as-sheet-note">It assumed: {changing}</p>
        <Section>
          <List>
            <div className="row">
              <textarea className="field" aria-label="What should it be instead?" placeholder="What should it be instead?"
                value={instead} onChange={(e) => setInstead(e.target.value)} rows={3} />
            </div>
          </List>
        </Section>
      </Sheet>
    </Page>
  );
}
