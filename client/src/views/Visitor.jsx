import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../ctx.jsx";
import { Msg, useLoad, Loading, Failed } from "../ui.jsx";

const today = () => new Date().toISOString().slice(0, 10);

/* ---------------- exhibitions + booking ---------------- */
function HoldCountdown({ expires, onZero }) {
  const until = new Date(expires.replace(" ", "T") + "Z").getTime();
  const calc = () => Math.max(0, Math.round((until - Date.now()) / 1000));
  const [s, setS] = useState(calc);
  useEffect(() => {
    const iv = setInterval(() => { const v = calc(); setS(v); if (v === 0) { clearInterval(iv); onZero(); } }, 1000);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return <b>{`${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`}</b>;
}

function Booking({ exhibitionId }) {
  const { t } = useApp();
  const [date, setDate] = useState(today());
  const [sel, setSel] = useState(null), [tt, setTt] = useState(""), [qty, setQty] = useState(1);
  const [st, setSt] = useState(null), [held, setHeld] = useState(null), [expired, setExpired] = useState(false);
  const av = useLoad(() => api("GET", `/api/exhibitions/${exhibitionId}/availability?date=${date}`).then(r => r.data), [exhibitionId, date]);

  useEffect(() => { setSel(null); }, [date]);
  const d = av.data;
  useEffect(() => { if (d && d.ticket_types && d.ticket_types.length && tt === "") setTt(String(d.ticket_types[0].ticket_type_id)); }, [d, tt]);

  const book = async () => {
    if (!sel) { setSt(<Msg>Choose a time slot</Msg>); return; }
    const b = await api("POST", "/api/bookings", { slot_id: sel.slot_id, ticket_type_id: +tt, quantity: +qty });
    if (!b.ok) { setSt(<Msg>{b.data.error + (b.data.remaining !== undefined ? ` (remaining ${b.data.remaining})` : "")}</Msg>); return; }
    setExpired(false); setSt(null); setHeld(b.data);
    av.reload();
  };
  const pay = async () => {
    const p = await api("POST", `/api/bookings/${held.booking_id}/pay`, { gateway_token: "tok_success" });
    if (p.ok) { setHeld(null); setSt(<Msg ok>{"Booking confirmed: " + p.data.booking_reference}</Msg>); av.reload(); }
    else setSt(<Msg>{p.data.error}</Msg>);
  };

  if (!d) return av.error ? <Failed error={av.error} /> : <Loading />;
  return (
    <div>
      <label>{t("date")}</label>
      <input type="date" value={date} onChange={e => setDate(e.target.value)} />
      <div>
        <label>{t("slot")}</label>
        <div className="slots">
          {d.slots.map(s => (
            <div key={s.slot_id} tabIndex={0} className={"slot" + (s.remaining <= 0 ? " full" : "") + (sel && sel.slot_id === s.slot_id ? " sel" : "")}
              onClick={() => { if (s.remaining > 0) setSel(s); }}
              onKeyDown={e => { if ((e.key === "Enter" || e.key === " ") && s.remaining > 0) setSel(s); }}>
              {`${s.start_time}–${s.end_time} (${s.remaining <= 0 ? t("full") : s.remaining + " " + t("left")})`}
            </div>
          ))}
        </div>
        <label>Ticket</label>
        <select value={tt} onChange={e => setTt(e.target.value)}>{d.ticket_types.map(x => <option key={x.ticket_type_id} value={x.ticket_type_id}>{`${x.name} - AED ${x.price}`}</option>)}</select>
        <label>{t("qty")}</label>
        <input type="number" min="1" max="10" value={qty} onChange={e => setQty(e.target.value)} />
        <p><button className="primary" onClick={book}>{t("book")}</button></p>
        {held && (
          <Msg ok>
            {`Reference ${held.booking_reference} - ${t("total")}: AED ${held.total_price} - seats held for `}
            <HoldCountdown key={held.booking_id} expires={held.hold_expires_at} onZero={() => setExpired(true)} />
            {" "}<button className="primary" disabled={expired} onClick={pay}>{t("paynow")}</button>
          </Msg>
        )}
        {st}
      </div>
    </div>
  );
}

export function ExhibitionsView() {
  const ex = useLoad(() => api("GET", "/api/exhibitions").then(r => r.data));
  if (!ex.data) return ex.error ? <Failed error={ex.error} /> : <Loading />;
  return (
    <div>
      {ex.data.map(e => (
        <div className="card" key={e.exhibition_id}>
          <h3>{e.title}</h3>
          <p>{`${e.gallery} · ${e.start_date} – ${e.end_date}`}</p>
          <Booking exhibitionId={e.exhibition_id} />
        </div>
      ))}
    </div>
  );
}

/* ---------------- my tickets ---------------- */
function TicketQR({ ticket }) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    let url, live = true;
    api("GET", `/api/tickets/${ticket.ticket_id}/qr.png`, undefined, true).then(async r => {
      if (r.ok && live) { url = URL.createObjectURL(await r.blob()); setSrc(url); }
    });
    return () => { live = false; if (url) URL.revokeObjectURL(url); };
  }, [ticket.ticket_id]);
  return <div><img className="qr" alt={"ticket QR " + ticket.ticket_id} src={src || undefined} /><code>{ticket.token}</code>{" "}{ticket.status}</div>;
}

function BookingCard({ b, onChange }) {
  const { t } = useApp();
  const [out, setOut] = useState(null), [newSlot, setNewSlot] = useState("");
  const details = useLoad(() => b.status === "confirmed" ? api("GET", `/api/bookings/${b.booking_id}`).then(r => r.data) : null, [b.booking_id, b.status]);
  const slots = useLoad(async () => {
    if (b.status !== "confirmed") return [];
    const ex = await api("GET", "/api/exhibitions"); const e = ex.data.find(x => x.title === b.title); if (!e) return [];
    const av = await api("GET", `/api/exhibitions/${e.exhibition_id}/availability`);
    return av.data.slots.filter(s => s.remaining >= b.quantity && !(s.slot_date === b.slot_date && s.start_time === b.start_time));
  }, [b.booking_id, b.status]);
  useEffect(() => { if (slots.data && slots.data.length && newSlot === "") setNewSlot(String(slots.data[0].slot_id)); }, [slots.data, newSlot]);

  const reschedule = async () => {
    const c = await api("PATCH", `/api/bookings/${b.booking_id}`, { action: "reschedule", new_slot_id: +newSlot });
    setOut(<Msg ok={c.ok}>{c.ok ? "Rescheduled" : c.data.error}</Msg>); if (c.ok) setTimeout(onChange, 700);
  };
  const cancel = async () => {
    const c = await api("PATCH", `/api/bookings/${b.booking_id}`, { action: "cancel" });
    setOut(<Msg ok={c.ok}>{c.ok ? "Cancelled - " + c.data.refund_status : c.data.error}</Msg>);
  };
  return (
    <div className="card">
      <b>{b.booking_reference}</b>{` ${b.title} · ${b.slot_date} ${b.start_time} · ${b.quantity} × · AED ${b.total_price} · ${b.status}`}
      {b.status === "confirmed" && (
        <p>
          <select value={newSlot} onChange={e => setNewSlot(e.target.value)}>
            {(slots.data || []).map(s => <option key={s.slot_id} value={s.slot_id}>{`${s.slot_date} ${s.start_time} (${s.remaining} ${t("left")})`}</option>)}
          </select>{" "}
          <button className="link" onClick={reschedule}>{t("reschedule")}</button>
        </p>
      )}
      {(b.status === "confirmed" || b.status === "pending") && <p><button className="link" onClick={cancel}>{t("cancel")}</button></p>}
      {out}
      <div>{details.data && details.data.tickets.map(tk => <TicketQR key={tk.ticket_id} ticket={tk} />)}</div>
    </div>
  );
}

export function TicketsView() {
  const r = useLoad(() => api("GET", "/api/bookings").then(x => x.data));
  if (!r.data) return r.error ? <Failed error={r.error} /> : <Loading />;
  return (
    <div>
      {r.data.map(b => <BookingCard key={b.booking_id} b={b} onChange={r.reload} />)}
      {!r.data.length && <p>No bookings yet.</p>}
    </div>
  );
}

/* ---------------- recommendations ---------------- */
function RecoItem({ it, onDismiss }) {
  const { t } = useApp();
  const rate = async e => { if (e.target.value) await api("POST", "/api/feedback", { artifact_id: it.artifact_id, rating: +e.target.value }); };
  return (
    <div className="card">
      <b>{`#${it.rank} ${it.title}`}</b>
      <div><i>{it.reason}</i></div>
      <div>{`${it.category} · ${it.gallery_location}`}</div>
      <select defaultValue="" onChange={rate}><option value="">{t("rate")}</option>{[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{"★".repeat(n)}</option>)}</select>{" "}
      <button className="link" onClick={onDismiss}>{t("dismiss")}</button>
    </div>
  );
}

export function RecoView() {
  const { t } = useApp();
  const data = useLoad(async () => {
    const me = await api("GET", "/api/me"), cats = await api("GET", "/api/categories"), rec = await api("GET", "/api/recommendations");
    return { me: me.data, cats: cats.data, rec: rec.data };
  });
  if (!data.data) return data.error ? <Failed error={data.error} /> : <Loading />;
  const { me, cats, rec } = data.data;
  const chosen = new Set(me.interests || []);
  const toggle = async (name, on) => {
    on ? chosen.add(name) : chosen.delete(name);
    await api("PATCH", "/api/me", { interests: [...chosen] }); data.reload();
  };
  return (
    <div>
      <div className="card">
        <b>Interests</b>
        <div>{cats.map(c => (
          <label key={c.name} style={{ display: "inline-block", marginRight: 10, fontWeight: "normal" }}>
            <input type="checkbox" checked={chosen.has(c.name)} onChange={e => toggle(c.name, e.target.checked)} />{" " + c.name}
          </label>))}
        </div>
        <label><input type="checkbox" checked={!!me.profile.consent_personalisation}
          onChange={async e => { await api("PATCH", "/api/me", { consent_personalisation: e.target.checked }); data.reload(); }} />{" " + t("consent")}</label>
      </div>
      <p>{"Mode: " + rec.mode}</p>
      {rec.items.map(it => <RecoItem key={it.artifact_id} it={it} onDismiss={async () => { await api("POST", `/api/recommendations/${it.artifact_id}/action`, { action: "dismiss" }); data.reload(); }} />)}
    </div>
  );
}

/* ---------------- account ---------------- */
export function AccountView() {
  const { t, logout } = useApp();
  const me = useLoad(() => api("GET", "/api/me").then(r => r.data));
  const [f, setF] = useState(null), [out, setOut] = useState(null);
  useEffect(() => { if (me.data && !f) setF({ name: me.data.profile.display_name, mob: me.data.profile.mobile_number || "", lang: me.data.profile.preferred_language }); }, [me.data, f]);
  if (!f) return me.error ? <Failed error={me.error} /> : <Loading />;
  const save = async () => {
    const r = await api("PATCH", "/api/me", { display_name: f.name, mobile_number: f.mob, preferred_language: f.lang });
    setOut(<Msg ok={r.ok}>{r.ok ? "Profile saved" : r.data.error}</Msg>);
  };
  const del = async () => {
    if (!confirm("Delete your account and personal data?")) return;
    const r = await api("DELETE", "/api/me"); if (r.ok) logout(); else setOut(<Msg>{r.data.error}</Msg>);
  };
  return (
    <div>
      <div className="card">
        <h3>{t("account") + ": " + me.data.email}</h3>
        <label>{t("name")}</label><input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} />
        <label>{t("mobile")}</label><input type="tel" value={f.mob} onChange={e => setF({ ...f, mob: e.target.value })} />
        <label>Language</label>
        <select value={f.lang} onChange={e => setF({ ...f, lang: e.target.value })}><option>EN</option><option>AR</option></select>
        <p><button className="primary" onClick={save}>{t("save")}</button></p>
      </div>
      <div className="card">
        <p>Deleting your account removes your personal data (FR-07).</p>
        <button onClick={del}>{t("del")}</button>
      </div>
      {out}
    </div>
  );
}

/* ---------------- exhibit / 3D / AR ---------------- */
function ModelViewer({ src, alt, onError, innerRef }) {
  const ref = useRef(null);
  useEffect(() => {
    const mv = ref.current; if (!mv) return;
    innerRef.current = mv;
    const attrs = { src, alt, ar: "", "ar-modes": "webxr scene-viewer quick-look", "ar-scale": "auto", "camera-controls": "", "auto-rotate": "", "shadow-intensity": "1", "touch-action": "pan-y", loading: "eager", class: "mv" };
    for (const [k, v] of Object.entries(attrs)) mv.setAttribute(k, v);
    mv.addEventListener("error", onError);
    return () => mv.removeEventListener("error", onError);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [src]);
  return <model-viewer ref={ref} />;
}

function ExhibitCard({ d }) {
  const { t } = useApp();
  const ar = useLoad(() => api("GET", `/api/ar/${d.artifact_id}`).then(r => r.data), [d.artifact_id]);
  const mv = useRef(null), [status, setStatus] = useState(null);
  if (!ar.data) return ar.error ? <Failed error={ar.error} /> : <Loading />;
  const a = ar.data, viewer = a.ar && customElements.get("model-viewer");
  const record = async fb => (await api("POST", "/api/ar/sessions", { content_id: a.content_id, duration_seconds: 30, device_type: /Android|iPhone|iPad/i.test(navigator.userAgent) ? "mobile" : "web", used_fallback: fb })).ok;
  const viewAR = async () => {
    if (mv.current && mv.current.canActivateAR) { await record(false); mv.current.activateAR(); }
    else { await record(true); setStatus(<Msg ok>Camera AR needs a phone or tablet (HTTPS connection, ARCore/ARKit). Showing the interactive 3D viewer instead.</Msg>); }
  };
  return (
    <div className="card">
      <h3>{d.title}</h3><p>{d.description}</p><p>{`${d.period} · ${d.origin} · ${d.location}`}</p>
      {viewer ? (
        <>
          <ModelViewer src={a.model_url} alt={"3D model of " + d.title} innerRef={mv} onError={() => setStatus(<Msg>The 3D model could not be loaded.</Msg>)} />
          <p className="hint">{(a.overlay_text || "") + " · drag to rotate, scroll or pinch to zoom"}</p>
          <button className="primary" onClick={viewAR}>{t("viewAR")}</button>{status}
        </>
      ) : (
        <>
          {d.image_url && <img src={d.image_url} alt={d.title} style={{ maxWidth: "100%" }} />}
          <p className="hint">{a.ar ? "3D viewer failed to load - showing text only." : "No AR/3D content has been published for this exhibit yet."}</p>
        </>
      )}
    </div>
  );
}

export function ExhibitView() {
  const [code, setCode] = useState("ART-DEMO00"), [res, setRes] = useState(null);
  const open = async () => setRes(await api("GET", `/api/exhibits/by-code/${encodeURIComponent(code)}`));
  return (
    <div>
      <label>Exhibit QR code</label>
      <input value={code} onChange={e => setCode(e.target.value)} />
      <button className="primary" onClick={open}>Open</button>
      <div>{res && (res.ok ? <ExhibitCard key={res.data.artifact_id} d={res.data} /> : <Msg>{res.data.error}</Msg>)}</div>
    </div>
  );
}
