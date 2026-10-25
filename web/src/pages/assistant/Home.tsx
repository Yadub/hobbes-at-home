import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, problemText, useLoad } from "../../api/client";
import type { AssistantTaskSummary } from "../../api/client";
import { useToast } from "../../components/Controls";
import { ChecklistIcon, ChevronRight, Spinner } from "../../components/Icons";
import { List, Row, Section } from "../../components/List";
import { Page } from "../../components/Page";
import { Link } from "../../router";
import { aheadWhen, Choices, Composer, shortWhen } from "./common";
import { EyeIcon, PersonCircleIcon, RepeatIcon, TerminalIcon } from "./icons";
import { Ideas } from "./Ideas";
import { sessionsSummary } from "./Sessions";

const ROUTINE_EXAMPLE = "Every Thursday, find what's on near me this weekend that I'd like";

const EXAMPLES = [
  "Find me a quiet hotel in Lisbon for 12–15 November, with a pool",
  "Compare flights to Bangkok for the first week of December",
  "What do I need for a visa to Japan on my passport?",
];

/** A watched job's line: the change it found (new ones first), or what it's waiting for and when it looks. */
function watchSub(t: AssistantTaskSummary): ReactNode {
  const w = t.watch;
  if (!w) return null;
  if (t.status === "working") return "Sniffing around now";
  if (w.last_change && w.unseen) return <span className="as-watch-new">{w.last_change}</span>;
  if (w.last_change) return `${w.last_change} · ${shortWhen(w.last_change_at ?? "")}`;
  const waiting = w.condition ? `Waiting for ${w.condition}` : "No change";
  return w.last_check_at ? `${waiting} · looked ${shortWhen(w.last_check_at)}`
    : w.condition ? `${waiting} · first look ${aheadWhen(w.next_at)}` : `First look ${aheadWhen(w.next_at)}`;
}

/** A routine's line: new results first, otherwise when it runs. */
function routineSub(t: AssistantTaskSummary): ReactNode {
  const w = t.watch;
  if (!w) return null;
  if (t.status === "working") return "Running now";
  if (w.unseen) return <span className="as-watch-new">New results{w.last_change ? `: ${w.last_change}` : ""}</span>;
  return w.last_check_at ? `${w.when} · last ran ${shortWhen(w.last_check_at)}` : `${w.when} · first run ${aheadWhen(w.next_at)}`;
}

function Decision({ t, onAnswered }: { t: AssistantTaskSummary; onAnswered: () => void }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function send(text: string) {
    setBusy(true);
    const { error } = await api.POST("/api/assistant/tasks/{task_id}/messages", {
      params: { path: { task_id: t.id } }, body: { text },
    });
    setBusy(false);
    if (error) { toast({ text: problemText(error) }); return; }
    toast({ text: "Sent. It's carrying on." });
    onAnswered();
  }

  async function retry() {
    setBusy(true);
    const { error } = await api.POST("/api/assistant/tasks/{task_id}/retry", { params: { path: { task_id: t.id } } });
    setBusy(false);
    if (error) { toast({ text: problemText(error) }); return; }
    onAnswered();
  }

  return (
    <div className={`card as-decision${t.status === "failed" ? " failed" : ""}`}>
      <Link to={`/assistant/task/${t.id}`} className="as-decision-head">
        <span>{t.title}</span><ChevronRight />
      </Link>
      {t.status === "failed" ? (
        <>
          <p className="as-question">Couldn't finish</p>
          <p className="subhead secondary as-why">{t.error ?? "Something went wrong."}</p>
          <div className="as-choices">
            <button type="button" className="button small tinted" onClick={retry} disabled={busy}>Try Again</button>
          </div>
        </>
      ) : t.question ? (
        <>
          <Choices question={t.question} busy={busy} onChoose={send} />
          <Link to={`/assistant/task/${t.id}?answer=1`} className="as-own-words">Answer in your own words</Link>
        </>
      ) : null}
    </div>
  );
}

export function AssistantHome() {
  const list = useLoad(() => api.GET("/api/assistant/tasks"));
  const coding = useLoad(() => api.GET("/api/sessions"));
  const codingNow = sessionsSummary(coding.data);
  const [showAll, setShowAll] = useState(false);
  const [draft, setDraft] = useState("");
  const toast = useToast();
  const all = list.data?.tasks ?? [];
  const needs = all.filter((t) => t.status === "needs_you" || t.status === "failed");
  const scheduled = all.filter((t) => t.watch && t.status !== "needs_you" && t.status !== "failed")
    .sort((a, b) => Number(b.watch?.unseen) - Number(a.watch?.unseen)
      || (b.watch?.last_change_at ?? "").localeCompare(a.watch?.last_change_at ?? ""));
  const watched = scheduled.filter((t) => t.watch?.kind === "watch");
  const routines = scheduled.filter((t) => t.watch?.kind === "routine");
  const working = all.filter((t) => t.status === "working" && !t.watch);
  const done = all.filter((t) => (t.status === "done" || t.status === "cancelled") && !t.watch);
  const shown = showAll ? done : done.slice(0, 15);

  const busy = all.some((t) => t.status === "working");
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(list.reload, 3000);
    return () => window.clearInterval(timer);
  }, [busy, list.reload]);

  async function start(request: string): Promise<boolean> {
    const { data, error } = await api.POST("/api/assistant/tasks", { body: { request } });
    if (error) { toast({ text: problemText(error) }); return false; }
    setDraft("");
    toast({ text: "On it. It'll be here when it's done." });
    list.reload();
    return Boolean(data);
  }

  return (
    <Page title="Hobbes AI"
      trailing={<Link to="/assistant/profile" className="bar-button" aria-label="Profile"><PersonCircleIcon /></Link>}>
      <Composer big placeholder="What do you need?" button="Start" onSend={start} initial={draft}
        note="It comes back with options, or one question. It never books or pays." />

      {list.error && <div className="notice error">{list.error}</div>}

      {needs.length > 0 && (
        <Section header="Needs you">
          <div className="as-decisions">
            {needs.map((t) => <Decision key={t.id} t={t} onAnswered={list.reload} />)}
          </div>
        </Section>
      )}

      {coding.data && (
        <Section>
          <List>
            <Row icon={<TerminalIcon />} tile="var(--gray)" title="Coding Sessions" sub="Claude Code and Codex on the Mac"
              to="/assistant/sessions"
              value={codingNow.waiting ? <span style={{ color: "var(--caution)" }}>{codingNow.value}</span> : codingNow.value} />
          </List>
        </Section>
      )}

      <Ideas onStarted={list.reload} />

      {watched.length > 0 && (
        <Section header="Watching" footer="It looks again on schedule and tells you what changed: a fare that fell, a table that opened up.">
          <List>
            {watched.map((t) => (
              <Row key={t.id} icon={<EyeIcon />} tile="var(--assistant)" title={t.title} sub={watchSub(t)}
                to={`/assistant/task/${t.id}`} value={t.status === "working" ? undefined : t.watch?.every === "daily" ? "Daily" : "Weekly"}
                trailing={t.status === "working" ? <Spinner label="Looking again" />
                  : t.watch?.unseen ? <span className="as-dot" role="img" aria-label="New change" /> : undefined} />
            ))}
          </List>
        </Section>
      )}

      {list.data && (
        <Section header="Routines" footer={routines.length > 0
          ? "Done afresh on schedule, early in the morning unless you said a time, so the results are in your brief. To change one, say so in it."
          : "Ask for a job to be done on a schedule and it shows here. Runs are early in the morning, in time for your brief."}>
          <List>
            {routines.map((t) => (
              <Row key={t.id} icon={<RepeatIcon />} tile="var(--assistant)" title={t.title} sub={routineSub(t)}
                to={`/assistant/task/${t.id}`}
                trailing={t.status === "working" ? <Spinner label="Running" />
                  : t.watch?.unseen ? <span className="as-dot" role="img" aria-label="New results" /> : undefined} />
            ))}
            {routines.length === 0 && (
              <Row icon={<RepeatIcon />} tile="var(--gray)" chevron={false}
                title={<span style={{ whiteSpace: "normal" }}>“{ROUTINE_EXAMPLE}”</span>} sub="An example: tap to use it"
                onClick={() => { setDraft(ROUTINE_EXAMPLE); window.scrollTo(0, 0); }} />
            )}
          </List>
        </Section>
      )}

      {working.length > 0 && (
        <Section header="Working">
          <List>
            {working.map((t) => (
              <Row key={t.id} title={t.title} sub={t.latest ?? "Hobbes is fetching"} to={`/assistant/task/${t.id}`}
                trailing={<Spinner label="Working" />} />
            ))}
          </List>
        </Section>
      )}

      {(list.data?.suggestions ?? 0) > 0 && (
        <Section footer="Preferences it noticed in your tasks. Nothing changes until you add them.">
          <List>
            <Row icon={<PersonCircleIcon />} tile="var(--assistant)" title="Suggestions for your profile"
              value={String(list.data?.suggestions)} to="/assistant/profile" />
          </List>
        </Section>
      )}

      {done.length > 0 && (
        <Section header="Done">
          <List>
            {shown.map((t) => (
              <Row key={t.id} title={t.title} to={`/assistant/task/${t.id}`}
                sub={t.status === "cancelled" ? "Stopped" : t.pick ? `Recommended: ${t.pick}` : t.summary ?? undefined}
                value={shortWhen(t.finished_at ?? t.updated_at)} />
            ))}
            {!showAll && done.length > shown.length && (
              <Row title={`Show All ${done.length}`} tone="tinted" onClick={() => setShowAll(true)} chevron={false} />
            )}
          </List>
        </Section>
      )}

      {list.data && all.length === 0 && (
        <>
          <div className="empty">
            <ChecklistIcon />
            <p className="subhead" style={{ margin: 0 }}>Nothing to fetch yet. Give Hobbes a job above: it works in the background and comes back with the job done, or with one decision for you.</p>
          </div>
          <Section header="For example">
            <List>
              {EXAMPLES.map((e) => (
                <Row key={e} title={<span style={{ whiteSpace: "normal" }}>{e}</span>} onClick={() => { setDraft(e); window.scrollTo(0, 0); }} chevron={false} />
              ))}
            </List>
          </Section>
        </>
      )}
    </Page>
  );
}
