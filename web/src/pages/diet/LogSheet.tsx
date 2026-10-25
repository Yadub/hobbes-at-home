import { useEffect, useRef, useState } from "react";
import { api, problemText, useLoad } from "../../api/client";
import { CameraIcon, PhotoIcon, XCircleFill } from "../../components/Icons";
import { List, Row, Section } from "../../components/List";
import { Segmented } from "../../components/Controls";
import { Sheet } from "../../components/Sheet";
import { useToast } from "../../components/Controls";
import { today, toLocalInput, withOffset } from "../../lib/dates";
import { whole } from "../../lib/format";

type Slot = "breakfast" | "lunch" | "snack" | "dinner";
const SLOTS: { value: Slot; label: string }[] = [
  { value: "breakfast", label: "Breakfast" }, { value: "lunch", label: "Lunch" },
  { value: "snack", label: "Snack" }, { value: "dinner", label: "Dinner" },
];

// Where tapping a meal puts the time, on the sheet's day (mostly for logging earlier days)
const PRESET: Record<Slot, string> = { breakfast: "09:00", lunch: "13:30", snack: "17:00", dinner: "21:00" };

export function slotFor(d: Date): Slot {
  const h = d.getHours() + d.getMinutes() / 60;
  return h >= 4 && h < 11 ? "breakfast" : h < 15.5 && h >= 11 ? "lunch" : h < 18.5 && h >= 15.5 ? "snack" : "dinner";
}

/** Photos from an iPhone can be 5 MB HEIC files; send a 1600 px JPEG instead (faster, and every
 *  browser and the AI can read it). */
async function shrink(file: File, max = 1600): Promise<Blob> {
  let source: ImageBitmap | HTMLImageElement;
  try {
    source = await createImageBitmap(file);
  } catch {
    const url = URL.createObjectURL(file);
    try {
      source = await new Promise<HTMLImageElement>((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error("This photo's format can't be read here."));
        img.src = url;
      });
    } finally {
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  }
  const w = "naturalWidth" in source ? source.naturalWidth : source.width;
  const h = "naturalHeight" in source ? source.naturalHeight : source.height;
  const scale = Math.min(1, max / Math.max(w, h));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(w * scale);
  canvas.height = Math.round(h * scale);
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Couldn't prepare the photo.");
  ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Couldn't prepare the photo."))), "image/jpeg", 0.85));
}

type Picked = { blob: Blob; url: string };

export function LogSheet({ open, day, onClose, onLogged }: {
  open: boolean; day: string; onClose: () => void; onLogged: (mealId: number, day: string) => void;
}) {
  const [photos, setPhotos] = useState<Picked[]>([]);
  const [note, setNote] = useState("");
  const [when, setWhen] = useState("");
  const [slot, setSlot] = useState<Slot>("lunch");
  const [slotTouched, setSlotTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const camera = useRef<HTMLInputElement>(null);
  const library = useRef<HTMLInputElement>(null);
  const toast = useToast();
  // What's usually had around the time in the sheet comes first, so it follows a change of time too.
  const at = when ? withOffset(new Date(when)) : "";
  const recent = useLoad(() => (open && at ? api.GET("/api/diet/recent", { params: { query: { at } } }) : Promise.resolve({ data: undefined })), [open, at]);

  // A time already in that meal stays (now, while logging as you eat); a preset still to come today isn't used.
  function pickSlot(v: Slot) {
    setSlot(v);
    setSlotTouched(true);
    if (when && slotFor(new Date(when)) === v) return;
    const preset = new Date(`${when.slice(0, 10) || day}T${PRESET[v]}`);
    if (preset <= new Date()) setWhen(toLocalInput(preset));
  }

  useEffect(() => {
    if (!open) return;
    const d = day === today() ? new Date() : new Date(`${day}T${PRESET.lunch}`);
    setWhen(toLocalInput(d));
    setSlot(slotFor(d));
    setSlotTouched(false);
    setNote("");
    setError(null);
    setPhotos((old) => { old.forEach((p) => URL.revokeObjectURL(p.url)); return []; });
  }, [open, day]);

  async function addFiles(list: FileList | null) {
    if (!list) return;
    setError(null);
    try {
      const picked: Picked[] = [];
      for (const f of Array.from(list).slice(0, 4 - photos.length)) {
        const blob = await shrink(f);
        picked.push({ blob, url: URL.createObjectURL(blob) });
      }
      setPhotos((p) => [...p, ...picked]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't add that photo.");
    }
  }

  async function submit() {
    setBusy(true);
    setError(null);
    const at = new Date(when);
    const form = new FormData();
    form.set("eaten_at", withOffset(at));
    form.set("note", note);
    form.set("slot", slot);
    photos.forEach((p, i) => form.append("photos", p.blob, `photo-${i}.jpg`));
    try {
      const r = await fetch("/api/diet/meals", { method: "POST", body: form, headers: { "X-Hobbes": "1" } });
      const body = await r.json();
      if (!r.ok) throw new Error(problemText(body));
      onLogged(body.meal_id as number, withOffset(at).slice(0, 10));
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the meal.");
    } finally {
      setBusy(false);
    }
  }

  async function again(mealId: number) {
    const at = new Date(when);
    const { data, error: err } = await api.POST("/api/diet/meals/{meal_id}/again", {
      params: { path: { meal_id: mealId } }, body: { eaten_at: withOffset(at) },
    });
    if (err) { setError(problemText(err)); return; }
    toast({ text: "Logged again" });
    onLogged(data.meal_id, withOffset(at).slice(0, 10));
    onClose();
  }

  const canAdd = photos.length > 0 || note.trim().length > 0;

  return (
    <Sheet open={open} title="Log Food" onClose={onClose} action={{ label: "Add", onClick: submit, disabled: !canAdd, busy }}>
      <input ref={camera} type="file" accept="image/*" capture="environment" hidden onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />
      <input ref={library} type="file" accept="image/*" multiple hidden onChange={(e) => { addFiles(e.target.files); e.target.value = ""; }} />

      {error && <div className="notice error" role="alert">{error}</div>}

      {photos.length > 0 && (
        <div style={{ display: "flex", gap: 10, overflowX: "auto", marginBottom: 14 }}>
          {photos.map((p, i) => (
            <div key={p.url} style={{ position: "relative", flex: "none" }}>
              <img src={p.url} alt={`Photo ${i + 1}`} style={{ width: 132, height: 132, objectFit: "cover", borderRadius: 12 }} />
              <button type="button" aria-label="Remove photo" onClick={() => setPhotos((all) => all.filter((x) => x !== p))}
                style={{ position: "absolute", top: 6, right: 6, border: 0, background: "none", padding: 0, color: "rgba(0,0,0,0.55)", width: 26, height: 26 }}>
                <XCircleFill />
              </button>
            </div>
          ))}
        </div>
      )}

      {photos.length < 4 && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 22 }}>
          <button type="button" className="button gray" onClick={() => camera.current?.click()}><CameraIcon />Take Photo</button>
          <button type="button" className="button gray" onClick={() => library.current?.click()}><PhotoIcon />Choose Photo</button>
        </div>
      )}

      <Section footer="Amounts you write here count over what the photo shows.">
        <List>
          <div className="row">
            <textarea className="field" aria-label="What did you eat?" value={note} onChange={(e) => setNote(e.target.value)}
              placeholder="What did you eat? For example: 2 slices of toast, scrambled eggs, a cappuccino" rows={3} />
          </div>
        </List>
      </Section>

      <Section>
        <List>
          <div className="row">
            <span className="row-main"><span className="row-title">Time</span></span>
            <input className="field" type="datetime-local" aria-label="Time" value={when}
              onChange={(e) => { setWhen(e.target.value); if (!slotTouched && e.target.value) setSlot(slotFor(new Date(e.target.value))); }} />
          </div>
          <div className="row" style={{ display: "block" }}>
            <Segmented label="Meal" value={slot} options={SLOTS} onChange={pickSlot} />
          </div>
        </List>
      </Section>

      {recent.data && recent.data.length > 0 && (
        <Section header="Log again" footer="What you have most comes first, especially around this time of day. Copies the meal with its amounts, at the time above. No AI needed.">
          <List>
            {recent.data.slice(0, 6).map((m) => (
              <Row key={m.id} title={m.title} value={`${whole(m.totals.kcal)} kcal`} onClick={() => again(m.id)} chevron={false}
                sub={`${m.times === 1 ? "Once" : `${m.times} times`}${m.usual_at ? ` · usually around ${m.usual_at}` : ""}`} />
            ))}
          </List>
        </Section>
      )}
    </Sheet>
  );
}
