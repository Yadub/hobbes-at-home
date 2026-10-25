import { oneDp, whole } from "../../lib/format";

/** A UK unit of alcohol is 8 g of pure alcohol (diet/drinks.py). */
export const unitsOf = (grams: number | null | undefined) => (grams ? grams / 8 : 0);

/** " · 80 mg caffeine · 1.6 units" for what has any, "" otherwise. */
export function drinksText(caffeine: number | null | undefined, alcohol: number | null | undefined): string {
  const parts: string[] = [];
  if (caffeine && caffeine >= 1) parts.push(`${whole(caffeine)} mg caffeine`);
  if (alcohol && unitsOf(alcohol) >= 0.05) parts.push(`${oneDp(unitsOf(alcohol))} ${unitsOf(alcohol) === 1 ? "unit" : "units"}`);
  return parts.length ? ` · ${parts.join(" · ")}` : "";
}
