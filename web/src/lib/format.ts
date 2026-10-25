export const whole = (n: number | null | undefined) =>
  n === null || n === undefined ? "–" : Math.round(n).toLocaleString();

export const oneDp = (n: number | null | undefined) =>
  n === null || n === undefined ? "–" : (Math.round(n * 10) / 10).toLocaleString(undefined, { maximumFractionDigits: 1 });

export const SOURCES: Record<string, string> = {
  indb: "Indian Nutrient Databank",
  ifct: "Indian Food Composition Tables 2017",
  fndds: "USDA FoodData Central",
  mine: "Your foods",
};

export const sourceName = (id: string | null | undefined) =>
  id ? SOURCES[id.split(":")[0] ?? ""] ?? "Food tables" : "AI estimate";
