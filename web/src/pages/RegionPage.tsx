import { useEffect, useState } from "react";
import { api, problemText, useLoad } from "../api/client";
import { useToast } from "../components/Controls";
import { List, Section } from "../components/List";
import { Page } from "../components/Page";

/** Where you live and what you mostly eat: how meals are read, where labels are looked up, and prices' currency. */
export function RegionPage() {
  const r = useLoad(() => api.GET("/api/region"));
  const toast = useToast();
  const [country, setCountry] = useState("");
  const [cuisine, setCuisine] = useState("");
  const [currency, setCurrency] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!r.data) return;
    setCountry(r.data.country_code);
    setCuisine(r.data.chosen ? r.data.cuisine : "");
    setCurrency(r.data.chosen ? r.data.currency : "");
  }, [r.data]);

  async function save() {
    setBusy(true);
    setError(null);
    const { error: e } = await api.PUT("/api/region", { body: { country, cuisine, currency } });
    setBusy(false);
    if (e) { setError(problemText(e)); return; }
    toast({ text: "Saved" });
    r.reload();
  }

  const d = r.data;
  return (
    <Page title="Region" backTo="/settings" backLabel="Settings">
      {(r.error || error) && <div className="notice error">{r.error ?? error}</div>}
      {d && (
        <>
          <Section footer={d.chosen ? undefined : "Not chosen yet, so this Mac's region is used."}>
            <List>
              <div className="row">
                <span className="row-main"><span className="row-title">Country</span></span>
                <select className="field" aria-label="Country" value={country} onChange={(e) => setCountry(e.target.value)}>
                  {!d.countries.some((c) => c.code === country) && <option value={country}>{country}</option>}
                  {d.countries.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
                </select>
              </div>
            </List>
          </Section>
          <Section header="What you mostly eat" footer="In your own words. Meals are read and named the way they're usually made and served. Leave it empty for the usual food where you live.">
            <List>
              <div className="row">
                <input className="field left" aria-label="What you mostly eat" value={cuisine} maxLength={200}
                  onChange={(e) => setCuisine(e.target.value)} placeholder={d.cuisine} />
              </div>
            </List>
          </Section>
          <Section header="Currency" footer="Hobbes AI gives prices in it. Leave it empty for your country's.">
            <List>
              <div className="row">
                <input className="field left" aria-label="Currency" value={currency} maxLength={3}
                  autoCapitalize="characters" autoCorrect="off" spellCheck={false}
                  onChange={(e) => setCurrency(e.target.value.toUpperCase())} placeholder={d.currency} />
              </div>
            </List>
          </Section>
          <button className="button block" onClick={save} disabled={busy || !country}>{busy ? "Saving…" : "Save"}</button>
        </>
      )}
    </Page>
  );
}
