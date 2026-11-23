import { useState } from "react";
import { api } from "../api.js";
import { useApp } from "../ctx.jsx";
import { Msg, useLoad, Loading, Failed } from "../ui.jsx";

const ROLES = ["Staff", "Manager", "ITAdmin"];
const EVENTS = ["login", "failedLogin", "roleChange", "artifactChange", "ticketValidation", "accessDenied"];

function AuditTable({ rows }) {
  return (
    <table><tbody>
      <tr>{["Time", "User", "Event", "Details"].map(x => <th key={x}>{x}</th>)}</tr>
      {rows.slice(0, 50).map((a, i) => <tr key={i}><td>{a.event_time}</td><td>{a.user_id || "-"}</td><td>{a.event_type}</td><td>{a.details || ""}</td></tr>)}
    </tbody></table>
  );
}

export default function AdminView() {
  const { t } = useApp();
  const d = useLoad(async () => ({ acc: (await api("GET", "/api/admin/accounts")).data, audit: (await api("GET", "/api/audit")).data, health: (await api("GET", "/api/health")).data }));
  const [em, setEm] = useState(""), [pw, setPw] = useState(""), [role, setRole] = useState("Staff"), [out, setOut] = useState(null);
  const [ev, setEv] = useState(""), [txt, setTxt] = useState(""), [auditRows, setAuditRows] = useState(null);
  if (!d.data) return d.error ? <Failed error={d.error} /> : <Loading />;
  const { acc, audit, health } = d.data;
  const changeRole = async (a, v) => { const x = await api("PATCH", `/api/admin/accounts/${a.account_id}`, { role: v }); setOut(x.ok ? <Msg ok>Role changed</Msg> : <Msg>{x.data.error}</Msg>); };
  const toggleActive = async a => { await api("PATCH", `/api/admin/accounts/${a.account_id}`, { is_active: !a.is_active }); d.reload(); };
  const create = async () => {
    const c = await api("POST", "/api/admin/accounts", { email: em, password: pw, role });
    setOut(c.ok ? <Msg ok>{"Created. Authenticator secret (shown once): " + c.data.mfa_secret}</Msg> : <Msg>{c.data.error}</Msg>);
    if (c.ok) d.reload();
  };
  const search = async () => {
    const qs = new URLSearchParams(Object.entries({ event_type: ev, text: txt }).filter(([, v]) => v));
    setAuditRows((await api("GET", "/api/audit?" + qs)).data);
  };
  return (
    <div>
      <h3>{t("health")}</h3>
      {health.alerts.length ? <Msg>{health.alerts.join("; ")}</Msg> : <Msg ok>All components OK</Msg>}
      <h3>{t("accounts")}</h3>
      <table><tbody>
        <tr>{["ID", "E-mail", "Role", "Active", ""].map(x => <th key={x}>{x}</th>)}</tr>
        {acc.map(a => (
          <tr key={a.account_id}>
            <td>{a.account_id}</td><td>{a.email}</td>
            <td>{a.role === "Visitor" ? "Visitor" : <select defaultValue={a.role} onChange={e => changeRole(a, e.target.value)}>{ROLES.map(r => <option key={r}>{r}</option>)}</select>}</td>
            <td>{a.is_active ? "yes" : "no"}</td>
            <td><button className="link" onClick={() => toggleActive(a)}>{a.is_active ? "Deactivate" : "Reactivate"}</button></td>
          </tr>))}
      </tbody></table>
      <div className="card">
        <input placeholder="e-mail" value={em} onChange={e => setEm(e.target.value)} />
        <input placeholder="password" type="password" value={pw} onChange={e => setPw(e.target.value)} />
        <select value={role} onChange={e => setRole(e.target.value)}>{ROLES.map(r => <option key={r}>{r}</option>)}</select>
        <button className="primary" onClick={create}>Create account</button>
        {out}
      </div>
      <h3>{t("audit")}</h3>
      <div className="card">
        <select value={ev} onChange={e => setEv(e.target.value)}><option value="">all events</option>{EVENTS.map(x => <option key={x}>{x}</option>)}</select>{" "}
        <input placeholder="text in details" value={txt} onChange={e => setTxt(e.target.value)} />{" "}
        <button className="primary" onClick={search}>Search</button>
      </div>
      <div><AuditTable rows={auditRows || audit} /></div>
    </div>
  );
}
