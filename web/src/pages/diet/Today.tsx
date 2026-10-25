import { useEffect, useState } from "react";
import { api, problemText, useLoad, waitForJob } from "../../api/client";
import type { Meal } from "../../api/client";
import { CalendarIcon, ChartIcon, ChevronLeft, ChevronRight, CupIcon, ForkKnifeIcon, PlusIcon, Spinner, TargetIcon } from "../../components/Icons";
import { List, Row, Section } from "../../components/List";
import { Page } from "../../components/Page";
import { addDays, dayLabel, timeLabel, today } from "../../lib/dates";
import { whole } from "../../lib/format";
import { go, Link, useQuery } from "../../router";
import { CalendarSheet } from "./CalendarSheet";
import { drinksText, unitsOf } from "./drinksText";
import { DayOverview } from "./DayOverview";
import { LogSheet } from "./LogSheet";
import { Suggestions } from "./Suggestions";
import type { Suggestion } from "./Suggestions";

const SLOT_NAMES: Record<string, string> = { breakfast: "Breakfast", lunch: "Lunch", snack: "Snacks", dinner: "Dinner" };

function MealRow({ m, drinks }: { m: Meal; drinks: boolean }) {
  const thumb = m.photos > 0
    ? <img className="thumb" src={`/api/diet/meals/${m.id}/photos/0`} alt="" loading="lazy" />
    : <span className="thumb"><ForkKnifeIcon /></span>;
  const title = m.status === "analysing" ? (m.note || "Meal") : m.title || m.note || "Meal";
  const sub = m.status === "analysing"
    ? <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}><Spinner label="Reading" />Reading…</span>
    : m.status === "failed" ? <span className="danger">{m.error ?? "Couldn't read this"}</span>
      : `${timeLabel(m.eaten_at)} · ${m.items.length} ${m.items.length === 1 ? "item" : "items"}${drinks ? drinksText(m.totals.caffeine, m.totals.alcohol) : ""}`;
  return <Row thumb={thumb} title={title} sub={sub} value={m.status === "ready" ? `${whole(m.totals.kcal)} kcal` : undefined}
    to={`/diet/meal/${m.id}`} />;
}

export function Today() {
  const q = useQuery();
  const day = q.get("day") ?? today();
  const d = useLoad(() => api.GET("/api/diet/day", { params: { query: { day } } }), [day]);
  const drinks = useLoad(() => api.GET("/api/diet/drinks", { params: { query: { day } } }), [day]);
  const showDrinks = drinks.data?.enabled ?? false;
  const [logOpen, setLogOpen] = useState(false);
  const [calOpen, setCalOpen] = useState(false);
  const [ideas, setIdeas] = useState<{ busy: boolean; list?: Suggestion[]; error?: string }>({ busy: false });
  const reading = d.data?.meals.some((m) => m.status === "analysing");

  useEffect(() => {
    if (!reading) return;
    const t = window.setInterval(d.reload, 2500);
    return () => window.clearInterval(t);
  }, [reading, d.reload]);

  useEffect(() => setIdeas({ busy: false }), [day]);

  async function suggest() {
    setIdeas({ busy: true });
    try {
      const { data, error } = await api.POST("/api/diet/suggest", { body: { day } });
      if (error) throw new Error(problemText(error));
      const job = await waitForJob(data.job_id);
      if (job.status === "failed") throw new Error(job.error ?? "No suggestions this time.");
      setIdeas({ busy: false, list: (job.result as { suggestions: Suggestion[] }).suggestions });
    } catch (e) {
      setIdeas({ busy: false, error: e instanceof Error ? e.message : "No suggestions this time." });
    }
  }

  const setDay = (n: number) => {
    const next = addDays(day, n);
    go(next === today() ? "/diet" : `/diet?day=${next}`, { replace: true });
  };
  const bySlot = ["breakfast", "lunch", "snack", "dinner"].map((s) => ({
    slot: s, meals: (d.data?.meals ?? []).filter((m) => m.slot === s),
  })).filter((g) => g.meals.length);
  const isToday = day === today();

  return (
    <Page title="Diet" eyebrow={dayLabel(day, { long: true })}
      trailing={<>
        <Link to="/diet/history" className="bar-button" aria-label="History"><ChartIcon /></Link>
        <Link to="/diet/goals" className="bar-button" aria-label="Goal"><TargetIcon /></Link>
      </>}>
      <div className="daynav">
        <button className="bar-button" onClick={() => setDay(-1)} aria-label={`Previous day, ${dayLabel(addDays(day, -1))}`}><ChevronLeft /></button>
        <button className="date-button" onClick={() => setCalOpen(true)} aria-label="Choose a day">
          <CalendarIcon />{dayLabel(day)}
        </button>
        <button className="bar-button" onClick={() => setDay(1)} disabled={isToday} aria-label={`Next day, ${dayLabel(addDays(day, 1))}`}>
          <ChevronRight className="chev" />
        </button>
      </div>

      {d.error && <div className="notice error">{d.error}</div>}
      {d.data && <DayOverview d={d.data} onChanged={d.reload} />}

      <div style={{ display: "grid", gridTemplateColumns: isToday ? "1fr 1fr" : "1fr", gap: 10, marginBottom: 28 }}>
        <button className="button" onClick={() => setLogOpen(true)}><PlusIcon />Log Food</button>
        {isToday && (
          <button className="button gray" onClick={suggest} disabled={ideas.busy}>
            {ideas.busy ? <><Spinner label="Thinking" />Thinking…</> : "Suggest Meals"}
          </button>
        )}
      </div>

      {ideas.error && <div className="notice error">{ideas.error}</div>}
      {ideas.list && <Suggestions list={ideas.list} onLogged={d.reload} />}

      {bySlot.map((g) => (
        <Section key={g.slot} header={SLOT_NAMES[g.slot]}
          action={<span className="num secondary">{whole(g.meals.reduce((a, m) => a + m.totals.kcal, 0))} kcal</span>}>
          <List>{g.meals.map((m) => <MealRow key={m.id} m={m} drinks={showDrinks} />)}</List>
        </Section>
      ))}

      {showDrinks && d.data && (
        <Section>
          <List>
            <Row icon={<CupIcon />} tile="var(--energy)" title="Caffeine and Alcohol" to="/diet/drinks"
              sub={`${isToday ? "Today" : dayLabel(day)}: ${Math.round(d.data.eaten.caffeine ?? 0)} mg caffeine · ${(Math.round(unitsOf(d.data.eaten.alcohol) * 10) / 10).toString()} units of alcohol.${drinks.data?.week.caffeine_per_week != null ? ` Last 7 days: about ${Math.round(drinks.data.week.caffeine_per_week).toLocaleString()} mg caffeine a week.` : ""}`} />
          </List>
        </Section>
      )}

      {d.data && d.data.meals.length === 0 && (
        <div className="empty">
          <ForkKnifeIcon />
          <p className="subhead" style={{ margin: 0 }}>Nothing logged {isToday ? "yet today" : `for ${dayLabel(day)}`}.</p>
        </div>
      )}

      <CalendarSheet open={calOpen} day={day} onClose={() => setCalOpen(false)}
        onPick={(d) => { setCalOpen(false); go(d === today() ? "/diet" : `/diet?day=${d}`, { replace: true }); }} />

      <LogSheet open={logOpen} day={day} onClose={() => setLogOpen(false)}
        onLogged={(_, mealDay) => { if (mealDay !== day) go(mealDay === today() ? "/diet" : `/diet?day=${mealDay}`); else d.reload(); }} />
    </Page>
  );
}
