import { useCallback, useEffect, useMemo, useState } from "react";
import { AppCtx } from "./ctx.jsx";
import { I18N } from "./i18n.js";
import { api, setOnExpired, setToken } from "./api.js";
import LoginView from "./views/LoginView.jsx";
import LinkView from "./views/LinkView.jsx";
import { ExhibitionsView, TicketsView, RecoView, AccountView, ExhibitView } from "./views/Visitor.jsx";
import ChatView from "./views/ChatView.jsx";
import { StaffScanView, ArtifactsView, ExhibSetupView, ArView, KbView } from "./views/Staff.jsx";
import DashboardView from "./views/Dashboard.jsx";
import AdminView from "./views/Admin.jsx";

const store = {
  get: (s, k) => { try { return s.getItem(k); } catch (e) { return null; } },
  set: (s, k, v) => { try { s.setItem(k, v); } catch (e) { /* storage blocked */ } },
};

export default function App() {
  const [lang, setLangState] = useState(store.get(localStorage, "lang") || "EN");
  const [token, setTok] = useState(store.get(sessionStorage, "token"));
  const [role, setRole] = useState(store.get(sessionStorage, "role"));
  const [tab, setTab] = useState(null);
  const [large, setLarge] = useState(false);
  const [contrast, setContrast] = useState(false);
  const [dark, setDark] = useState(() => {
    const saved = store.get(localStorage, "theme");
    return saved ? saved === "dark" : !!(window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches);
  });
  setToken(token);                                   // keep the fetch helper in sync during render

  const logout = useCallback(() => {
    setToken(null); setTok(null); setRole(null); setTab(null);
    try { sessionStorage.clear(); } catch (e) { /* ignore */ }
  }, []);
  useEffect(() => { setOnExpired(logout); }, [logout]);

  const login = (tk, rl) => {
    setToken(tk); setTok(tk); setRole(rl); setTab(null);
    store.set(sessionStorage, "token", tk); store.set(sessionStorage, "role", rl);
  };
  const setLang = l => { setLangState(l); store.set(localStorage, "lang", l); };
  const toggleDark = () => setDark(d => { store.set(localStorage, "theme", d ? "light" : "dark"); return !d; });

  useEffect(() => {
    document.documentElement.lang = lang.toLowerCase();
    document.documentElement.dir = lang === "AR" ? "rtl" : "ltr";
  }, [lang]);
  useEffect(() => {
    document.body.classList.toggle("dark", dark);
    document.body.classList.toggle("large", large);
    document.body.classList.toggle("contrast", contrast);
  }, [dark, large, contrast]);

  const t = useCallback(k => I18N[lang][k] || k, [lang]);
  const ctx = useMemo(() => ({ lang, t, role, logout }), [lang, t, role, logout]);

  const tabs = {
    Visitor: [["ex", t("exhibitions"), ExhibitionsView], ["tk", t("tickets"), TicketsView], ["rec", t("foryou"), RecoView], ["ob", t("exhibit"), ExhibitView], ["ch", t("chat"), ChatView], ["me", t("account"), AccountView]],
    Staff: [["sc", t("scan"), StaffScanView], ["ar", t("artifacts"), ArtifactsView], ["ex", t("exhib"), ExhibSetupView], ["arc", t("ar"), ArView], ["kb", t("kb"), KbView]],
    Manager: [["db", t("dashboard"), DashboardView]],
    ITAdmin: [["ad", t("accounts"), AdminView]],
  }[role];

  let body;
  if (location.pathname === "/verify" || location.pathname === "/reset") body = <LinkView />;
  else if (!token || !tabs) body = <LoginView onLogin={login} />;
  else {
    const current = tabs.find(x => x[0] === tab) || tabs[0];
    const View = current[2];
    body = (
      <div>
        <nav>{tabs.map(([k, label]) => <button key={k} className={k === current[0] ? "on" : ""} onClick={() => setTab(k)}>{label}</button>)}</nav>
        <div><View key={current[0]} /></div>
      </div>
    );
  }

  return (
    <AppCtx.Provider value={ctx}>
      <header id="bar">
        <h1>{"SMMS " + t("title")}</h1>
        <select aria-label="language" value={lang} onChange={e => setLang(e.target.value)}><option value="EN">EN</option><option value="AR">AR</option></select>
        <button title="Larger text" aria-label="Larger text" onClick={() => setLarge(x => !x)}>A+</button>
        <button title="High contrast" aria-label="High contrast" onClick={() => setContrast(x => !x)}>◐</button>
        <button title="Night mode" aria-label="Night mode" onClick={toggleDark}>{dark ? "☀" : "🌙"}</button>
        {token && <button onClick={logout}>{t("logout") + " (" + role + ")"}</button>}
      </header>
      <main id="app" aria-live="polite">{body}</main>
      <footer>SWE401 Group 5 - Smart Museum Management System (prototype)</footer>
    </AppCtx.Provider>
  );
}
