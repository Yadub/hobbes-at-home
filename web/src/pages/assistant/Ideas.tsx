import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { api, problemText, useLoad } from "../../api/client";
import type { AssistantIdea } from "../../api/client";
import { useToast } from "../../components/Controls";
import { ChecklistIcon, ForkKnifeIcon, GiftIcon, PeopleIcon, Spinner } from "../../components/Icons";
import { Section } from "../../components/List";
import { BedIcon, EyeIcon, PlaneIcon, RupeeIcon, SparklesIcon, TicketIcon } from "./icons";

const KINDS: Record<AssistantIdea["kind"], { icon: ReactNode; hue: string; name: string }> = {
  travel: { icon: <PlaneIcon />, hue: "var(--mail)", name: "Travel" },
  stays: { icon: <BedIcon />, hue: "var(--sleep)", name: "Stays" },
  food: { icon: <ForkKnifeIcon />, hue: "var(--carbs)", name: "Eating out" },
  gifts: { icon: <GiftIcon />, hue: "var(--heart)", name: "Gift" },
  tickets: { icon: <TicketIcon />, hue: "var(--body)", name: "Tickets" },
  admin: { icon: <ChecklistIcon />, hue: "var(--gray)", name: "Admin" },
  money: { icon: <RupeeIcon />, hue: "var(--energy)", name: "Money" },
  people: { icon: <PeopleIcon />, hue: "var(--people)", name: "People" },
  other: { icon: <SparklesIcon />, hue: "var(--assistant)", name: "Idea" },
};

function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (mins < 2) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  return hours < 24 ? `${hours} h ago` : new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** Jobs the assistant thinks it could take on, from the calendar, Coming Up, email and people. One tap
 *  starts one (and watches it, if it's the kind of thing that changes); Not Now means it isn't
 *  suggested again. */
export function Ideas({ onStarted }: { onStarted: () => void }) {
  const ideas = useLoad(() => api.GET("/api/assistant/ideas"));
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();
  const d = ideas.data;
  const thinking = Boolean(d?.thinking);
  const { reload } = ideas;

  useEffect(() => {
    if (!thinking) return;
    const timer = window.setInterval(reload, 4000);
    return () => window.clearInterval(timer);
  }, [thinking, reload]);

  async function start(i: AssistantIdea) {
    setBusy(i.id);
    const { error } = await api.POST("/api/assistant/ideas/{idea_id}/start", { params: { path: { idea_id: i.id } } });
    setBusy(null);
    if (error) { toast({ text: problemText(error) }); return; }
    toast({ text: i.watch ? `Started, and watching it ${i.watch}.` : "Started. It'll be here when it's done." });
    reload();
    onStarted();
  }

  async function dismiss(i: AssistantIdea) {
    setBusy(i.id);
    const { error } = await api.POST("/api/assistant/ideas/{idea_id}/dismiss", { params: { path: { idea_id: i.id } } });
    setBusy(null);
    if (error) { toast({ text: problemText(error) }); return; }
    toast({ text: "It won't suggest that again." });
    reload();
  }

  async function refresh() {
    const { error } = await api.POST("/api/assistant/ideas/refresh");
    if (error) { toast({ text: problemText(error) }); return; }
    reload();
  }

  if (!d) return null;
  const list = d.ideas;
  const action = thinking
    ? <span className="as-ideas-thinking"><Spinner label="Thinking" />Thinking…</span>
    : <button type="button" className="as-inline" onClick={refresh}>New Ideas</button>;

  return (
    <Section header="Suggested for You" action={action}
      footer={list.length > 0 && d.at ? `From your calendar, Coming Up and email, ${ago(d.at)}. Nothing starts until you tap Start.` : undefined}>
      {list.length > 0 ? (
        <div className="as-ideas">
          {list.map((i) => {
            const k = KINDS[i.kind] ?? KINDS.other;
            return (
              <div key={i.id} className="card as-idea" style={{ "--tile": k.hue } as CSSProperties}>
                <div className="as-idea-head">
                  <span className="icon-tile">{k.icon}</span>
                  <span className="as-idea-title">{i.title}</span>
                </div>
                <p className="as-idea-why">{i.why}</p>
                <p className="as-idea-request">“{i.request}”</p>
                <div className="as-idea-foot">
                  {i.watch && <span className="as-idea-watch"><EyeIcon />Watches {i.watch}</span>}
                  <span className="as-inline-group">
                    <button type="button" className="as-inline quiet" onClick={() => dismiss(i)} disabled={busy === i.id}>Not Now</button>
                    <button type="button" className="button small tinted" onClick={() => start(i)} disabled={busy === i.id}>Start</button>
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="card as-ideas-empty">
          <SparklesIcon />
          <p className="subhead secondary">
            {thinking ? "Looking through your calendar, Coming Up and email for jobs it could take on."
              : d.at ? `Nothing worth suggesting right now (looked ${ago(d.at)}). It looks again twice a day.`
                : "It looks through your calendar, Coming Up and email for jobs it could take on, twice a day."}
          </p>
        </div>
      )}
    </Section>
  );
}
