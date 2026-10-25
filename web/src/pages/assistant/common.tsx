import { useEffect, useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import type { AssistantQuestion, AssistantTaskSummary } from "../../api/client";
import { Spinner } from "../../components/Icons";
import "./assistant.css";

export type TaskStatus = AssistantTaskSummary["status"];

export const STATUS_NAMES: Record<TaskStatus, string> = {
  working: "Working", needs_you: "Needs you", done: "Done", failed: "Couldn't finish", cancelled: "Stopped",
};

const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();

/** A time as a list shows it: the time today, "Yesterday", or the date. */
export function shortWhen(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  if (sameDay(d, now)) return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  if (sameDay(d, y)) return "Yesterday";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** A time still to come: "today, 09:00", "tomorrow, 09:00", "Mon, 09:00", or the date. */
export function aheadWhen(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (d <= now || sameDay(d, now)) return `today, ${time}`;
  const t = new Date(now);
  t.setDate(now.getDate() + 1);
  if (sameDay(d, t)) return `tomorrow, ${time}`;
  if (d.getTime() - now.getTime() < 6 * 86_400_000) return `${d.toLocaleDateString(undefined, { weekday: "short" })}, ${time}`;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** A time in a log: the time today, otherwise the date and time. */
export function logWhen(iso: string): string {
  const d = new Date(iso);
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return sameDay(d, new Date()) ? time : `${d.toLocaleDateString(undefined, { day: "numeric", month: "short" })}, ${time}`;
}

/** The site an address belongs to, for a link's label. */
export function siteOf(link: string): string {
  try {
    return new URL(link).hostname.replace(/^www\./, "");
  } catch {
    return link;
  }
}

/** A text box in a card with a button: the large "What do you need?" box, and the smaller one on a
 *  task for answers and changes. Command-Return sends. */
export function Composer({ placeholder, button, onSend, big = false, note, inputRef, initial = "" }: {
  placeholder: string;
  button: string;
  onSend: (text: string) => Promise<boolean>;
  big?: boolean;
  note?: ReactNode;
  inputRef?: RefObject<HTMLTextAreaElement | null>;
  initial?: string;
}) {
  const [text, setText] = useState(initial);
  const [busy, setBusy] = useState(false);
  const own = useRef<HTMLTextAreaElement>(null);
  const ref = inputRef ?? own;

  useEffect(() => setText(initial), [initial]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [text, ref]);

  async function send() {
    if (!text.trim() || busy) return;
    setBusy(true);
    try {
      if (await onSend(text.trim())) setText("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={`as-compose${big ? " big" : ""}`} onSubmit={(e) => { e.preventDefault(); send(); }}>
      <textarea ref={ref} className="as-compose-field" value={text} placeholder={placeholder} aria-label={placeholder}
        rows={big ? 2 : 1} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); send(); } }} />
      <div className="as-compose-bar">
        <span className="footnote secondary">{note}</span>
        <button type="submit" className="button small" disabled={!text.trim() || busy}>
          {busy ? <Spinner label="Sending" /> : button}
        </button>
      </div>
    </form>
  );
}

/** The one question a task is waiting on, with its ready answers as buttons. */
export function Choices({ question, onChoose, busy }: {
  question: AssistantQuestion; onChoose: (choice: string) => void; busy: boolean;
}) {
  return (
    <>
      <p className="as-question">{question.text}</p>
      {question.why && <p className="subhead secondary as-why">{question.why}</p>}
      {question.choices.length > 0 && (
        <div className="as-choices">
          {question.choices.map((c) => (
            <button key={c} type="button" className="button small tinted" disabled={busy} onClick={() => onChoose(c)}>{c}</button>
          ))}
        </div>
      )}
    </>
  );
}
