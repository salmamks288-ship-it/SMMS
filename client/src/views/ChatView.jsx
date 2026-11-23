import { useEffect, useRef, useState } from "react";
import { api, chatStream } from "../api.js";
import { useApp } from "../ctx.jsx";

export default function ChatView() {
  const { t, lang, logout } = useApp();
  const greeting = lang === "AR" ? "مرحباً! اسألني عن ساعات العمل والتذاكر وإمكانية الوصول والمعروضات." : "Hi! Ask me about opening hours, tickets, accessibility or our exhibits.";
  const [msgs, setMsgs] = useState([{ id: 0, who: "bot", text: greeting, greeting: true }]);
  const [q, setQ] = useState(""), [busy, setBusy] = useState(false), [hint, setHint] = useState("");
  const session = useRef(null), logRef = useRef(null), inRef = useRef(null), nextId = useRef(1);

  useEffect(() => { if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight; }, [msgs]);
  // keep the greeting in the current language until the conversation starts
  useEffect(() => { setMsgs(m => m.length === 1 && m[0].greeting ? [{ ...m[0], text: greeting }] : m); }, [greeting]);

  const patch = (id, p) => setMsgs(ms => ms.map(m => m.id === id ? { ...m, ...p } : m));

  const send = async () => {
    const text = q.trim(); if (!text || busy) return;
    setBusy(true); setQ("");
    const botId = nextId.current + 1; nextId.current += 2;
    setMsgs(ms => [...ms, { id: botId - 1, who: "me", text }, { id: botId, who: "bot", text: "", typing: true }]);
    let got = "", final = null;
    try {
      const r = await chatStream({ question: text, language: lang, session_id: session.current });
      if (r.status === 401) { logout(); return; }
      if (!r.ok || !r.body) throw new Error("stream unavailable");
      const rd = r.body.getReader(), dec = new TextDecoder(); let buf = "";
      for (;;) {
        const { value, done } = await rd.read(); if (done) break;
        buf += dec.decode(value, { stream: true }); let i;
        while ((i = buf.indexOf("\n\n")) >= 0) {
          const block = buf.slice(0, i); buf = buf.slice(i + 2);
          const ev = (block.match(/^event: (.*)$/m) || [])[1], data = JSON.parse((block.match(/^data: (.*)$/m) || [, "{}"])[1]);
          if (ev === "meta") { session.current = data.session_id; setHint(data.mode === "llm" ? "" : "Basic mode: answers come from the museum knowledge base. Set GROQ_API_KEY or ANTHROPIC_API_KEY in .env for live AI answers."); }
          else if (ev === "delta") { got += data.text; patch(botId, { text: got, typing: false }); }
          else if (ev === "done") { final = data; session.current = data.session_id || session.current; }
          else if (ev === "error") throw new Error(data.error);
        }
      }
    } catch (e) {                      // streaming failed: fall back to the plain request
      if (!got) {
        const r = await api("POST", "/api/chat", { question: text, language: lang, session_id: session.current });
        if (r.ok) { final = r.data; session.current = r.data.session_id; got = r.data.answer; } else got = r.data.error || "Sorry, something went wrong.";
        patch(botId, { text: got, typing: false });
      }
    }
    patch(botId, { typing: false, text: got || "…", fallback: !!(final && final.fallback), source: final && final.source });
    setBusy(false);
    setTimeout(() => inRef.current && inRef.current.focus(), 0);
  };

  return (
    <div>
      <h3>{t("ask")}</h3>
      <div className="chat card" aria-live="polite" ref={logRef}>
        {msgs.map(m => (
          <div key={m.id} className={m.who === "me" ? "bubble me" : m.fallback ? "bubble fallback" : "bubble bot"}>
            <span>{m.typing ? <span className="typing">●●●</span> : m.text}</span>
            {m.source && <div><small>{"Source: " + m.source}</small></div>}
          </div>
        ))}
      </div>
      <div className="chatrow">
        <input className="chatin" aria-label={t("ask")} autoComplete="off" ref={inRef} value={q} onChange={e => setQ(e.target.value)} onKeyDown={e => { if (e.key === "Enter") send(); }} />
        <button className="primary" disabled={busy} onClick={send}>{t("send")}</button>
      </div>
      <small className="hint">{hint}</small>
    </div>
  );
}
