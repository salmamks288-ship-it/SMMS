import { useState } from "react";
import { api } from "../api.js";
import { useApp } from "../ctx.jsx";
import { Msg } from "../ui.jsx";

export default function LoginView({ onLogin }) {
  const { t, lang } = useApp();
  // login
  const [em, setEm] = useState(""), [pw, setPw] = useState(""), [otp, setOtp] = useState("");
  const [needOtp, setNeedOtp] = useState(false), [status, setStatus] = useState(null);
  // register
  const [rn, setRn] = useState(""), [re, setRe] = useState(""), [rp, setRp] = useState(""), [rm, setRm] = useState(""), [rc, setRc] = useState(false), [rs, setRs] = useState(null);

  const go = async () => {
    const r = await api("POST", "/api/auth/login", { email: em, password: pw, otp: otp || undefined });
    if (r.data.mfa_required) { setNeedOtp(true); setStatus(<Msg ok>Enter the one-time code</Msg>); return; }
    if (!r.ok) { setStatus(<Msg>{r.data.error || "error"}</Msg>); return; }
    onLogin(r.data.token, r.data.role);
  };
  const forgot = async () => {
    const r = await api("POST", "/api/auth/password-reset", { email: em });
    setStatus(<Msg ok>{r.data.message || "sent"}</Msg>);
  };
  const register = async () => {
    const r = await api("POST", "/api/auth/register", { display_name: rn, email: re, password: rp, consent_personalisation: rc, preferred_language: lang, mobile_number: rm || undefined });
    if (!r.ok) { setRs(<Msg>{r.data.error}</Msg>); return; }
    if (r.data.verification_token) await api("POST", "/api/auth/verify", { token: r.data.verification_token });   // development mode: link is auto-opened
    setRs(<Msg ok>{"Account created. " + (r.data.verification_token ? "Verified in development mode - you can log in." : "Check your e-mail.")}</Msg>);
  };

  return (
    <div>
      <div className="card">
        <h2>{t("login")}</h2>
        <label htmlFor="em">{t("email")}</label>
        <input type="email" id="em" autoComplete="username" value={em} onChange={e => setEm(e.target.value)} />
        <label htmlFor="pw">{t("password")}</label>
        <input type="password" id="pw" autoComplete="current-password" value={pw} onChange={e => setPw(e.target.value)} />
        {needOtp && <div><label htmlFor="otp">{t("otp")}</label><input id="otp" inputMode="numeric" value={otp} onChange={e => setOtp(e.target.value)} /></div>}
        <p><button className="primary" onClick={go}>{t("login")}</button></p>
        <button className="link" onClick={forgot}>{t("forgot")}</button>
        {status}
      </div>
      <div className="card">
        <h2>{t("register")}</h2>
        <label htmlFor="rn">{t("name")}</label><input id="rn" value={rn} onChange={e => setRn(e.target.value)} />
        <label htmlFor="re">{t("email")}</label><input type="email" id="re" value={re} onChange={e => setRe(e.target.value)} />
        <label htmlFor="rp">{t("password") + " (8+, letters + numbers)"}</label><input type="password" id="rp" value={rp} onChange={e => setRp(e.target.value)} />
        <label htmlFor="rm">{t("mobile")}</label><input type="tel" id="rm" value={rm} onChange={e => setRm(e.target.value)} />
        <label><input type="checkbox" id="rc" checked={rc} onChange={e => setRc(e.target.checked)} /> {t("consent")}</label>
        <p><button className="primary" onClick={register}>{t("register")}</button></p>
        {rs}
      </div>
    </div>
  );
}
