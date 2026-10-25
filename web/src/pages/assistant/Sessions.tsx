import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { api, useLoad } from "../../api/client";
import type { CodingSession, CodingSessions } from "../../api/client";
import { ChevronRight, Spinner } from "../../components/Icons";
import { List, Row, Section } from "../../components/List";
import { Page } from "../../components/Page";
import { Sheet } from "../../components/Sheet";
import { Link } from "../../router";
import { shortWhen } from "./common";
import { TerminalIcon } from "./icons";

const TOOL = { claude: "Claude Code", codex: "Codex" } as const;
const TILE = { claude: "var(--orange-ui)", codex: "var(--tint)" } as const;
const WHERE: Record<string, string> = {
  interactive: "In a terminal", background: "In the background", cli: "In a terminal", vscode: "In the Codex app",
  appServer: "In the Codex app",
};

const tilde = (cwd: string) => cwd.replace(/^\/Users\/[^/]+/, "~");
const folder = (cwd: string) => (tilde(cwd) === "~" ? "home folder" : cwd.split("/").filter(Boolean).pop() ?? cwd);

/** "now", "4 min", "2 h 10 min", "3 days": how long since `iso`. */
function since(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "now";
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  if (h < 24) return mins % 60 ? `${h} h ${mins % 60} min` : `${h} h`;
  const d = Math.floor(h / 24);
  return d === 1 ? "1 day" : `${d} days`;
}

function stateText(s: CodingSession): string {
  switch (s.state) {
    case "waiting": return s.waiting_for ? `Waiting for ${s.waiting_for}` : "Waiting for you";
    case "working": return "Working";
    case "idle": return "Idle";
    case "error": return "Stopped with an error";
    default: return "Ended";
  }
}

/** The summary on the Hobbes AI page: how many are waiting, working or open. */
export function sessionsSummary(d: CodingSessions | undefined): { value: string; waiting: boolean } {
  const live = d?.sessions.filter((s) => s.state !== "ended") ?? [];
  const waiting = live.filter((s) => s.state === "waiting").length;
  const working = live.filter((s) => s.state === "working").length;
  if (waiting) return { value: `${waiting} waiting`, waiting: true };
  if (working) return { value: `${working} working`, waiting: false };
  return { value: live.length ? `${live.length} open` : "None running", waiting: false };
}

/** Claude Code and Codex sessions on the Mac (sessions.py): what each is doing. Read only. */
export function SessionsPage() {
  const s = useLoad(() => api.GET("/api/sessions"));
  const [open, setOpen] = useState<CodingSession | null>(null);
  const all = s.data?.sessions ?? [];

  useEffect(() => {
    const timer = window.setInterval(s.reload, 15000);
    return () => window.clearInterval(timer);
  }, [s.reload]);

  const groups: { header: string; footer?: string; rows: CodingSession[] }[] = [
    { header: "Waiting for You", footer: "Answer it at the Mac. Nothing can be sent from here.",
      rows: all.filter((x) => x.state === "waiting") },
    { header: "Working", rows: all.filter((x) => x.state === "working" || x.state === "error") },
    { header: "Idle", footer: "Open, and finished with what it was asked.", rows: all.filter((x) => x.state === "idle") },
    { header: "Ended Today", rows: all.filter((x) => x.state === "ended") },
  ];

  return (
    <Page title="Coding Sessions" backTo="/assistant" backLabel="Hobbes AI">
      {s.error && <div className="notice error" role="alert">{s.error}</div>}

      {s.data && all.length === 0 && (
        <div className="empty">
          <TerminalIcon />
          <p className="subhead" style={{ margin: 0 }}>No Claude Code or Codex sessions on the Mac today.</p>
        </div>
      )}

      {groups.filter((g) => g.rows.length > 0).map((g) => (
        <Section key={g.header} header={g.header} footer={g.footer}>
          <List>
            {g.rows.map((x) => (
              <Row key={x.id} icon={<TerminalIcon />} tile={x.state === "ended" ? "var(--gray)" : TILE[x.tool]}
                title={x.name} sub={[TOOL[x.tool], folder(x.cwd), x.state === "waiting" ? x.waiting_for : null].filter(Boolean).join(" · ")} onClick={() => setOpen(x)} chevron={false}
                value={x.state === "working" ? undefined
                  : x.state === "ended" ? (x.ended_at ? shortWhen(x.ended_at) : undefined)
                  : x.state === "waiting" ? <span style={{ color: "var(--caution)" }}>{since(x.state_since)}</span>
                  : x.state === "error" ? <span style={{ color: "var(--bad)" }}>Error</span>
                  : since(x.state_since)}
                trailing={x.state === "working" ? <Spinner label="Working" /> : undefined} />
            ))}
          </List>
        </Section>
      ))}

      {s.data && (
        <Section header="Checked" footer="Read only: this shows your sessions on the Mac and can't send them anything. It checks again every 15 seconds while open.">
          <List>
            {s.data.tools.map((t) => (
              <Row key={t.tool} title={t.label} chevron={false}
                sub={t.error ?? (t.checked_at ? `Checked ${shortWhen(t.checked_at)}` : undefined)}
                value={t.error ? "Couldn't check" : t.available
                  ? `${all.filter((x) => x.tool === t.tool && x.state !== "ended").length} open` : "Not running"} />
            ))}
          </List>
        </Section>
      )}

      <Sheet open={open !== null} title={open?.name ?? ""} onClose={() => setOpen(null)} cancelLabel="Done">
        {open && (
          <>
            <Section>
              <List>
                <Row title="State" value={stateText(open)} />
                <Row title={open.state === "ended" ? "Ended" : "Since"}
                  value={open.state === "ended" ? (open.ended_at ? shortWhen(open.ended_at) : "")
                    : since(open.state_since) === "now" ? shortWhen(open.state_since)
                    : `${shortWhen(open.state_since)} (${since(open.state_since)})`} />
                <Row title="Tool" value={TOOL[open.tool]} />
                <Row title="Where" value={WHERE[open.kind] ?? open.kind} />
                {open.started_at && <Row title="Started" value={shortWhen(open.started_at)} />}
                <Row title="Folder" sub={<span style={{ userSelect: "text", whiteSpace: "normal" }}>{tilde(open.cwd)}</span>} />
              </List>
            </Section>
            <Section footer={open.open_with ? "To open it, type this in Terminal on the Mac." : open.kind === "interactive"
              ? "It's open in a terminal window on the Mac." : undefined}>
              <List>
                {open.open_with && (
                  <Row title="Open With" sub={<code style={{ userSelect: "text", whiteSpace: "normal" }}>{open.open_with}</code>} />
                )}
                <Row title="Session ID" sub={<code style={{ userSelect: "text", whiteSpace: "normal" }}>{open.session_id}</code>} />
              </List>
            </Section>
          </>
        )}
      </Sheet>
    </Page>
  );
}

const CARD_SHOWN = 4;

/** Coding Sessions on Summary, under Codex: what's open on the Mac, waiting ones first. */
export function SessionsCard() {
  const s = useLoad(() => api.GET("/api/sessions"));
  const { reload } = s;
  useEffect(() => {
    const timer = window.setInterval(reload, 30000);
    return () => window.clearInterval(timer);
  }, [reload]);
  const live = s.data?.sessions.filter((x) => x.state !== "ended") ?? [];
  return (
    <Link to="/assistant/sessions" className="card summary-last" style={{ "--hue": "var(--gray)", "--hue-text": "var(--label)" } as CSSProperties}>
      <div className="card-head">
        <span className="card-label"><TerminalIcon />Coding Sessions</span>
        <span className="card-meta">{live.length > CARD_SHOWN ? `${live.length - CARD_SHOWN} more` : live.length ? `${live.length} open` : ""}<ChevronRight /></span>
      </div>
      {live.length ? (
        <ul className="as-sess-list">
          {live.slice(0, CARD_SHOWN).map((x) => (
            <li key={x.id}>
              <span className="as-sess-dot" style={{ "--sess-tile": TILE[x.tool] } as CSSProperties}><TerminalIcon /></span>
              <span className="as-sess-main">
                <span className="as-sess-title">{x.name}</span>
                <span className="as-sess-sub">{[TOOL[x.tool], folder(x.cwd), x.state === "waiting" ? x.waiting_for : null].filter(Boolean).join(" · ")}</span>
              </span>
              {x.state === "working" ? <Spinner label="Working" />
                : <span className={`as-sess-state ${x.state}`}>{x.state === "waiting" ? "Waiting" : x.state === "error" ? "Error" : "Idle"}</span>}
            </li>
          ))}
        </ul>
      ) : (
        <p className="subhead secondary" style={{ margin: 0 }}>{s.data ? "No Claude Code or Codex sessions open." : " "}</p>
      )}
    </Link>
  );
}
