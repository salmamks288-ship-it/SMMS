import { useEffect, useState } from "react";

export const Msg = ({ ok, children }) => <div className={"msg " + (ok ? "ok" : "err")} role="alert">{children}</div>;

// Loads data when the view opens; reload() fetches again (replaces the old "render()" refresh).
export function useLoad(fn, deps = []) {
  const [st, setSt] = useState({ loading: true });
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    Promise.resolve().then(fn).then(
      data => live && setSt({ loading: false, data }),
      e => live && setSt({ loading: false, error: e.message || String(e) }));
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { ...st, reload: () => setN(x => x + 1) };
}

export const Loading = () => <p>…</p>;
export const Failed = ({ error }) => <Msg>{"Error: " + error}</Msg>;

// Generic card form: fields = [[key, label, attrs]]; attrs.options makes it a <select>.
export function FormCard({ title, fields, submit, okText, saveLabel }) {
  const init = () => Object.fromEntries(fields.map(([k, , a]) => [k, a && a.options ? String(a.options[0]) : ""]));
  const [vals, setVals] = useState(init);
  const [out, setOut] = useState(null);
  const run = async () => {
    const body = {};
    for (const [k, , a] of fields) {
      const v = vals[k];
      if (v !== "") body[k] = a && a.type === "number" ? +v : v;
    }
    const r = await submit(body);
    setOut(<Msg ok={r.ok}>{r.ok ? (okText || "Saved") : (r.data.error || "Error") + (r.data.fields ? ": " + r.data.fields.join(", ") : "")}</Msg>);
  };
  return (
    <div className="card">
      <b>{title}</b>
      {fields.map(([k, label, attrs = {}]) => {
        const { options, ...rest } = attrs;
        const set = e => setVals(v => ({ ...v, [k]: e.target.value }));
        return [
          <label key={k + "l"}>{label}</label>,
          options
            ? <select key={k} value={vals[k]} onChange={set}>{options.map(o => <option key={o} value={o}>{o}</option>)}</select>
            : <input key={k} {...rest} value={vals[k]} onChange={set} />,
        ];
      })}
      <p><button className="primary" onClick={run}>{saveLabel}</button></p>
      {out}
    </div>
  );
}

export function BarChart({ rows, labelKey, valKey, cut = 0 }) {
  const W = 560, H = 160, max = Math.max(1, ...rows.map(r => r[valKey])), bw = Math.min(70, W / Math.max(1, rows.length)), x0 = (W - bw * rows.length) / 2;
  return (
    <svg viewBox={`0 0 ${W} ${H + 20}`} width="100%" role="img">
      {rows.map((r, i) => {
        const hh = (r[valKey] / max) * H;
        return [
          <rect key={"r" + i} className="bar" x={x0 + i * bw + 4} y={H - hh} width={bw - 8} height={hh} />,
          <text key={"t" + i} x={x0 + i * bw + 4} y={H + 14}>{String(r[labelKey]).slice(cut)}</text>,
        ];
      })}
    </svg>
  );
}
