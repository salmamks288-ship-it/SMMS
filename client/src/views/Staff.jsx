import { useState } from "react";
import { api } from "../api.js";
import { useApp } from "../ctx.jsx";
import { Msg, FormCard, useLoad, Loading, Failed } from "../ui.jsx";

const STATUSES = ["onDisplay", "inStorage", "onLoan", "underRestoration"];
const CONDITIONS = ["excellent", "good", "fair", "poor"];
const Th = ({ cols }) => <tr>{cols.map((x, i) => <th key={i}>{x}</th>)}</tr>;

/* ---------------- scan / validate / alerts ---------------- */
function ScanResult({ a }) {
  const { t } = useApp();
  const [loc, setLoc] = useState(a.location), [st, setSt] = useState(a.status), [cond, setCond] = useState(a.condition), [out, setOut] = useState(null);
  const save = async () => {
    const u = await api("PATCH", `/api/artifacts/${a.artifact_id}`, { location: loc, status: st, condition: cond, version: a.updated_at });
    setOut(<Msg ok={u.ok}>{u.ok ? "Saved" + (u.data.alert ? " - ALERT: condition poor" : "") : (u.data.error + (u.data.latest ? " - reload to see latest values" : ""))}</Msg>);
  };
  return (
    <div className="card">
      <h3>{`${a.title} (#${a.artifact_id})`}</h3>
      {a.read_only && <Msg>Archived - read only</Msg>}
      <label>Location</label><input value={loc} onChange={e => setLoc(e.target.value)} />
      <label>Status</label><select value={st} onChange={e => setSt(e.target.value)}>{STATUSES.map(s => <option key={s}>{s}</option>)}</select>
      <label>Condition</label><select value={cond} onChange={e => setCond(e.target.value)}>{CONDITIONS.map(s => <option key={s}>{s}</option>)}</select>
      <p><button className="primary" disabled={a.read_only} onClick={save}>{t("save")}</button></p>
      {out}
    </div>
  );
}

export function StaffScanView() {
  const { t } = useApp();
  const [tag, setTag] = useState("ART-DEMO00"), [scanRes, setScanRes] = useState(null);
  const [tok, setTok] = useState(""), [vout, setVout] = useState(null);
  const info = useLoad(async () => ({ alerts: (await api("GET", "/api/alerts")).data, live: (await api("GET", "/api/visitors/live")).data }));
  const scan = async () => setScanRes(await api("GET", `/api/scan/${encodeURIComponent(tag)}`));
  const validate = async () => {
    const r = await api("POST", "/api/entry/validate", { token: tok });
    setVout(<Msg ok={r.data.result === "valid"}>{r.data.result === "valid" ? `VALID - ${r.data.ticket_type} - visitors in museum: ${r.data.visitors_in_museum}` : "REJECTED: " + (r.data.reason || r.data.error)}</Msg>);
    info.reload();
  };
  if (!info.data) return info.error ? <Failed error={info.error} /> : <Loading />;
  const { alerts, live } = info.data;
  return (
    <div>
      <h3>{t("scan")}</h3>
      <input value={tag} onChange={e => setTag(e.target.value)} />
      <button className="primary" onClick={scan}>{t("scan")}</button>
      <div>{scanRes && (scanRes.ok ? <ScanResult key={scanRes.data.artifact_id + scanRes.data.updated_at} a={scanRes.data} /> : <Msg>{scanRes.data.error}</Msg>)}</div>
      <h3>{t("validate")}</h3>
      <input style={{ width: "70%" }} placeholder="ticket token" value={tok} onChange={e => setTok(e.target.value)} />
      <button className="primary" onClick={validate}>{t("validate")}</button>
      {vout}
      <p>{"Visitors in museum now: " + live.visitors_in_museum}</p>
      <h3>{t("alerts")}</h3>
      {alerts.length ? <ul>{alerts.map((a, i) => <li key={i}>{`${a.title}: ${a.reason}`}</li>)}</ul> : <p>No alerts</p>}
    </div>
  );
}

/* ---------------- artifacts ---------------- */
export function ArtifactsView() {
  const { t } = useApp();
  const [title, setTitle] = useState(""), [status, setStatus] = useState(""), [query, setQuery] = useState({}), [hist, setHist] = useState(null);
  const cats = useLoad(() => api("GET", "/api/categories").then(r => r.data));
  const list = useLoad(() => {
    const qs = new URLSearchParams(); if (query.title) qs.set("title", query.title); if (query.status) qs.set("status", query.status);
    return api("GET", "/api/artifacts?" + qs).then(r => r.data);
  }, [query]);
  if (!cats.data || !list.data) return cats.error || list.error ? <Failed error={cats.error || list.error} /> : <Loading />;
  const showHistory = async a => {
    const hh = await api("GET", `/api/artifacts/${a.artifact_id}/history`);
    setHist(<><b>{"History of " + a.title}</b><ul>{hh.data.map((x, i) => <li key={i}>{`${x.changed_at}: ${x.field_name} ${x.old_value} → ${x.new_value}`}</li>)}</ul></>);
  };
  const archive = async a => {
    const reason = prompt("Reason for archiving?"); if (!reason) return;
    const z = await api("POST", `/api/artifacts/${a.artifact_id}/archive`, { reason });
    setHist(<Msg ok={z.ok}>{z.ok ? "Archived" : z.data.error}</Msg>); list.reload();
  };
  return (
    <div>
      <h3>{t("artifacts")}</h3>
      <div className="card">
        <input placeholder="title contains" value={title} onChange={e => setTitle(e.target.value)} />
        <select value={status} onChange={e => setStatus(e.target.value)}><option value="">any status</option>{STATUSES.map(x => <option key={x}>{x}</option>)}</select>
        <button className="primary" onClick={() => setQuery({ title, status })}>Search</button>
      </div>
      <div>
        <table><tbody>
          <Th cols={["ID", "Title", "Location", "Status", "Condition", "QR value", ""]} />
          {list.data.map(a => (
            <tr key={a.artifact_id}>
              <td>{a.artifact_id}</td><td>{a.title}</td><td>{a.location}</td><td>{a.status}</td><td>{a.condition}</td><td>{a.qr_code_value}</td>
              <td><button className="link" onClick={() => showHistory(a)}>History</button>{" "}<button className="link" onClick={() => archive(a)}>Archive</button></td>
            </tr>))}
        </tbody></table>
      </div>
      <div>{hist}</div>
      <FormCard title="New artifact (all fields marked * are mandatory)" saveLabel={t("save")} okText="Created"
        fields={[["title", "Title *"], ["category_id", "Category *", { options: cats.data.map(c => c.category_id) }], ["description", "Description *"], ["period", "Period *"], ["origin", "Origin *"],
          ["condition", "Condition *", { options: CONDITIONS }], ["location", "Location *"], ["status", "Status *", { options: STATUSES }], ["inspection_date", "Next inspection date", { type: "date" }], ["rfid_tag_id", "RFID tag ID (optional)"]]}
        submit={async b => { const r = await api("POST", "/api/artifacts", b); if (r.ok) list.reload(); return r; }} />
      <p>{"Categories: " + cats.data.map(c => `${c.category_id}=${c.name}`).join(", ")}</p>
    </div>
  );
}

/* ---------------- exhibitions setup ---------------- */
export function ExhibSetupView() {
  const { t } = useApp();
  const ex = useLoad(() => api("GET", "/api/exhibitions").then(r => r.data));
  if (!ex.data) return ex.error ? <Failed error={ex.error} /> : <Loading />;
  const sv = t("save");
  return (
    <div>
      <h3>{t("exhib")}</h3>
      <FormCard title="New exhibition" saveLabel={sv} fields={[["title", "Title"], ["gallery", "Gallery"], ["start_date", "Start date", { type: "date" }], ["end_date", "End date", { type: "date" }], ["description", "Description"]]}
        submit={async b => { const r = await api("POST", "/api/exhibitions", b); if (r.ok) setTimeout(ex.reload, 600); return r; }} />
      {ex.data.map(e => (
        <div className="card" key={e.exhibition_id}>
          <b>{`#${e.exhibition_id} ${e.title}`}</b>
          <div>{`${e.gallery} · ${e.start_date} – ${e.end_date}`}</div>
          <FormCard title="Add ticket type" saveLabel={sv} fields={[["name", "Name"], ["price", "Price (AED)", { type: "number", step: "0.01", min: 0 }], ["per_booking_limit", "Per-booking limit", { type: "number", min: 1 }]]}
            submit={b => api("POST", `/api/exhibitions/${e.exhibition_id}/ticket-types`, b)} />
          <FormCard title="Add time slot" saveLabel={sv} fields={[["slot_date", "Date", { type: "date" }], ["start_time", "Start (HH:MM)"], ["end_time", "End (HH:MM)"], ["capacity", "Capacity", { type: "number", min: 1 }]]}
            submit={b => api("POST", `/api/exhibitions/${e.exhibition_id}/slots`, b)} />
          <FormCard title="Assign artifact" saveLabel={sv} fields={[["artifact_id", "Artifact ID", { type: "number" }], ["display_start_date", "Display from", { type: "date" }], ["display_end_date", "Display until", { type: "date" }]]}
            submit={b => api("POST", `/api/exhibitions/${e.exhibition_id}/items`, b)} />
        </div>))}
    </div>
  );
}

/* ---------------- AR content ---------------- */
export function ArView() {
  const { t } = useApp();
  const r = useLoad(() => api("GET", "/api/ar-content").then(x => x.data));
  if (!r.data) return r.error ? <Failed error={r.error} /> : <Loading />;
  const toggle = async c => { await api("PATCH", `/api/ar-content/${c.content_id}`, { published: c.published ? 0 : 1 }); r.reload(); };
  return (
    <div>
      <h3>{t("ar")}</h3>
      <table><tbody>
        <Th cols={["ID", "Artifact", "Model", "MB", "Published", ""]} />
        {r.data.map(c => (
          <tr key={c.content_id}>
            <td>{c.content_id}</td><td>{c.title}</td><td>{c.model_url}</td><td>{c.file_size_mb}</td><td>{c.published ? "yes" : "no"}</td>
            <td><button className="link" onClick={() => toggle(c)}>{c.published ? "Unpublish" : "Publish"}</button></td>
          </tr>))}
      </tbody></table>
      <FormCard title="Upload AR content (max 20 MB)" saveLabel={t("save")} fields={[["artifact_id", "Artifact ID", { type: "number" }], ["model_url", "Model URL"], ["file_size_mb", "File size (MB)", { type: "number", step: "0.1" }], ["overlay_text", "Overlay text"]]}
        submit={async b => { const x = await api("POST", "/api/ar-content", b); if (x.ok) setTimeout(r.reload, 600); return x; }} />
    </div>
  );
}

/* ---------------- knowledge base ---------------- */
export function KbView() {
  const { t } = useApp();
  const r = useLoad(async () => ({ entries: (await api("GET", "/api/kb/entries")).data, un: (await api("GET", "/api/kb/unanswered")).data }));
  if (!r.data) return r.error ? <Failed error={r.error} /> : <Loading />;
  const toggle = async e => { await api("PATCH", `/api/kb/entries/${e.entry_id}`, { status: e.status === "published" ? "unpublished" : "published" }); r.reload(); };
  return (
    <div>
      <h3>{t("kb")}</h3>
      <table><tbody>
        <Th cols={["Question", "Lang", "Status", ""]} />
        {r.data.entries.map(e => (
          <tr key={e.entry_id}><td>{e.question}</td><td>{e.language}</td><td>{e.status}</td>
            <td><button className="link" onClick={() => toggle(e)}>{e.status === "published" ? "Unpublish" : "Publish"}</button></td></tr>))}
      </tbody></table>
      <FormCard title="Add knowledge entry (saved as draft)" saveLabel={t("save")} fields={[["question", "Question"], ["answer", "Answer"], ["language", "Language", { options: ["EN", "AR"] }], ["source_page", "Source page"]]}
        submit={async b => { const x = await api("POST", "/api/kb/entries", b); if (x.ok) setTimeout(r.reload, 600); return x; }} />
      <h3>Unanswered questions</h3>
      <ul>{r.data.un.map((x, i) => <li key={i}>{`${x.question} (${x.asks})`}</li>)}</ul>
    </div>
  );
}
