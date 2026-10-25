import createClient from "openapi-fetch";
import { useCallback, useEffect, useState } from "react";
import type { components, paths } from "./schema";

// Types come from the backend's own schema (npm run gen:api), so the two can't drift apart unnoticed.
// Every request carries X-Hobbes, which the backend requires for changes made from a browser.
export const api = createClient<paths>({ baseUrl: "", headers: { "X-Hobbes": "1" } });

type S = components["schemas"];
export type Meta = S["Meta"];
export type Status = S["Status"];
export type Job = S["Job"];
export type Day = S["Day"];
export type Meal = S["Meal"];
export type Item = S["Item"];
export type Explanation = S["Explanation"];
export type Food = S["Food"];
export type Targets = S["Targets"];
export type GoalsView = S["GoalsView"];
export type GoalsIn = S["GoalsIn"];
export type DrinksView = S["DrinksView"];
export type DrinksSpan = S["DrinksSpan"];
export type History = S["History"];
export type HealthSummary = S["HealthSummary"];
export type WhoopStatus = S["WhoopStatus"];
export type HealthOverview = S["Overview"];
export type HealthMetric = S["Metric"];
export type AssistantTask = S["AssistantTask"];
export type AssistantTaskSummary = S["AssistantTaskSummary"];
export type AssistantResult = S["AssistantResult"];
export type AssistantQuestion = S["AssistantQuestion"];
export type AssistantSuggestion = S["AssistantSuggestion"];
export type AssistantProfile = S["AssistantProfile"];
export type AssistantFact = S["AssistantFact"];
export type AssistantFactPrompt = S["AssistantFactPrompt"];
export type AssistantWatch = S["AssistantWatch"];
export type AssistantIdea = S["AssistantIdea"];
export type AssistantIdeas = S["AssistantIdeas"];
export type CodingSession = S["CodingSession"];
export type CodingSessions = S["CodingSessions"];
export type Backups = S["Backups"];

export function problemText(error: unknown, fallback = "Something went wrong."): string {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

type Loaded<T> = { data: T | undefined; error: string | null; loading: boolean; reload: () => void };

/** Load something from the API when the page opens (and when `deps` change), with a way to load it
 *  again. While reloading, the previous data stays on screen. */
export function useLoad<T>(load: () => Promise<{ data?: T; error?: unknown }>, deps: unknown[] = []): Loaded<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const run = useCallback(load, deps);

  useEffect(() => {
    let live = true;
    setLoading(true);
    run()
      .then((r) => {
        if (!live) return;
        if (r.error !== undefined) setError(problemText(r.error));
        else {
          setData(r.data);
          setError(null);
        }
      })
      .catch(() => live && setError("The dashboard can't be reached. Is the Mac on?"))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [run, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}

/** Wait for a background job to finish, checking every second or so. */
export async function waitForJob(id: number, timeoutMs = 240_000): Promise<Job> {
  const until = Date.now() + timeoutMs;
  for (;;) {
    const { data, error } = await api.GET("/api/jobs/{job_id}", { params: { path: { job_id: id } } });
    if (error) throw new Error(problemText(error));
    if (data.status === "done" || data.status === "failed") return data;
    if (Date.now() > until) throw new Error("Still running. Check back in a minute.");
    await new Promise((r) => setTimeout(r, 1200));
  }
}
