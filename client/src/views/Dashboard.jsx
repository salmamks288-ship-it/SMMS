import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../ctx.jsx";
import { BarChart, useLoad, Loading, Failed } from "../ui.jsx";

export default function DashboardView() {
  const { t } = useApp();
  const [from, setFrom] = useState(""), [to, setTo] = useState(""), [ex, setEx] = useState(""), [tt, setTt] = useState("");
  const [applied, setApplied] = useState({});
  const exs = useLoad(() => api("GET", "/api/exhibitions").then(r => r.data));
  const tts = useLoad(async () => {
    const id = ex || (exs.data && exs.data[0] && exs.data[0].exhibition_id);
    return id ? (await api("GET", `/api/exhibitions/${id}/ticket-types`)).data : [];
  }, [ex, exs.data]);
  const filt = f => ({ from: f.from || undefined, to: f.to || undefined, exhibition_id: f.ex || undefined, ticket_type_id: f.tt || undefined });
  const sum = useLoad(async () => {
    const qs = new URLSearchParams(Object.entries(filt(applied)).filter(([, v]) => v));
    return (await api("GET", "/api/analytics/summary?" + qs)).data;
  }, [applied]);
  useEffect(() => { setTt(""); }, [ex]);

  const exp = fmt => async () => {
    const r = await api("POST", "/api/reports/export", { format: fmt, ...filt({ from, to, ex, tt }) }, true);
    const a = document.createElement("a"); a.href = URL.createObjectURL(await r.blob()); a.download = "report." + fmt.toLowerCase();
    document.body.append(a); a.click(); a.remove();
  };
  const r = sum.data;
  const kp = (k, v) => <div className="card kpi" key={k}><b>{v}</b>{k}</div>;
  return (
    <div>
      <div className="card">
        From <input type="date" value={from} onChange={e => setFrom(e.target.value)} /> To <input type="date" value={to} onChange={e => setTo(e.target.value)} />{" "}
        <select value={ex} onChange={e => setEx(e.target.value)}><option value="">all exhibitions</option>{(exs.data || []).map(e => <option key={e.exhibition_id} value={e.exhibition_id}>{e.title}</option>)}</select>{" "}
        <select value={tt} onChange={e => setTt(e.target.value)}><option value="">all ticket types</option>{(tts.data || []).map(x => <option key={x.ticket_type_id} value={x.ticket_type_id}>{x.name}</option>)}</select>{" "}
        <button className="primary" onClick={() => setApplied({ from, to, ex, tt })}>{t("apply")}</button>{" "}
        <button onClick={exp("PDF")}>Export PDF</button>{" "}<button onClick={exp("CSV")}>Export CSV</button>
      </div>
      {!r ? (sum.error ? <Failed error={sum.error} /> : <Loading />) : (
        <div>
          <div className="kpis">
            {kp("Tickets sold", r.tickets_sold)}{kp("Revenue (AED)", r.revenue)}{kp("Visitors in museum now", r.visitors_in_museum_now)}
            {kp("Chatbot unanswered", Math.round(r.chatbot_unanswered_rate * 100) + "%")}{kp("Avg booking (AED)", r.avg_booking_value)}
            {kp("Peak hour", r.peak_hour || "-")}{kp("Change vs previous period", r.change_vs_previous_pct == null ? "n/a" : r.change_vs_previous_pct + "%")}
          </div>
          <div className="card"><b>Tickets per day</b><BarChart rows={r.by_date} labelKey="date" valKey="tickets" cut={5} /></div>
          <div className="card"><b>Peak hours</b><BarChart rows={r.peak_hours.map(p => ({ label: String(p.hour), tickets: p.tickets }))} labelKey="label" valKey="tickets" /></div>
          <div className="card"><b>Most viewed exhibits</b>
            <ul>{r.most_viewed_exhibits.slice(0, 5).map((x, i) => <li key={i}>{`${x.title}: ${x.interactions} views, rating ${x.avg_rating ?? "-"}, AR sessions ${x.ar_sessions}`}</li>)}</ul></div>
          <p>Aggregated data only (no personal identifiers).</p>
        </div>)}
    </div>
  );
}
