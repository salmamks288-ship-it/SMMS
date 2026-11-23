import { useEffect, useState } from "react";
import { api } from "../api.js";
import { useApp } from "../ctx.jsx";
import { Msg } from "../ui.jsx";

// Targets of the e-mail links: /verify?token=... (FR-01) and /reset?token=... (FR-05)
export default function LinkView() {
  const { t } = useApp();
  const tok = new URLSearchParams(location.search).get("token") || "";
  const verify = location.pathname === "/verify";
  const [res, setRes] = useState(null);
  const [pw, setPw] = useState("");

  useEffect(() => {
    if (verify) api("POST", "/api/auth/verify", { token: tok }).then(setRes);
  }, [verify, tok]);

  if (verify) {
    return (
      <div className="card">
        <h2>E-mail verification</h2>
        {!res ? <p>…</p> : <Msg ok={res.ok}>{res.ok ? "Account activated - you can log in now." : (res.data.error || "error")}</Msg>}
        {res && <a href="/">Go to login</a>}
      </div>
    );
  }
  const save = async () => setRes(await api("POST", "/api/auth/password-reset/confirm", { token: tok, password: pw }));
  return (
    <div className="card">
      <h2>Choose a new password</h2>
      <label htmlFor="np">{t("password") + " (8+, letters + numbers)"}</label>
      <input type="password" id="np" value={pw} onChange={e => setPw(e.target.value)} />
      <p><button className="primary" onClick={save}>{t("save")}</button></p>
      {res && <div><Msg ok={res.ok}>{res.ok ? "Password changed - you can log in now." : (res.data.error || "error")}</Msg>{res.ok && <a href="/">Go to login</a>}</div>}
    </div>
  );
}
