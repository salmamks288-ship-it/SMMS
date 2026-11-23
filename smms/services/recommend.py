"""S4 Recommendation & Chatbot (FR-27..FR-33). Scikit-learn TF-IDF + cosine similarity (content-based recommender)."""
import json, re
from collections import Counter
from flask import Blueprint, Response, current_app, g, jsonify, request, stream_with_context
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.metrics.pairwise import cosine_similarity
from ..db import q, x, tx, iso
from ..security import require_auth
from .integration import GatewayUnavailable, NO_ANSWER, generate_answer, llm_configured, stream_llm

bp = Blueprint("recommend", __name__)
now = lambda: current_app.config["NOW"]()

def _text(a):
    return " ".join(str(a.get(k) or "") for k in ("title", "category_name", "category_name", "description", "period", "origin"))

def _on_display():
    return q("""SELECT a.*, c.name AS category_name FROM artifact a JOIN category c ON c.category_id=a.category_id
                WHERE a.is_archived=0 AND a.status='onDisplay' ORDER BY a.artifact_id""")

def popular(limit=5, exclude=()):
    """Popular exhibits when there is no visitor data or consent was withdrawn (FR-29)."""
    arts = [a for a in _on_display() if a["artifact_id"] not in exclude]
    pop = Counter()
    for r in q("SELECT artifact_id, COUNT(*) n FROM feedback GROUP BY artifact_id"): pop[r["artifact_id"]] += r["n"]
    for r in q("SELECT artifact_id, SUM(clicked) n FROM recommendation GROUP BY artifact_id"): pop[r["artifact_id"]] += r["n"] or 0
    arts.sort(key=lambda a: (-pop[a["artifact_id"]], a["artifact_id"]))
    return arts[:limit]

def rank_for_visitor(vid, limit=5, max_per_category=2):
    """SPEC-2: profile vector from interests + ratings, cosine similarity, remove dismissed, limit one category in the top 5."""
    arts = _on_display()
    if not arts: return [], "none"
    interests = [r["name"] for r in q("""SELECT c.name FROM profile_category pc JOIN interest_profile ip ON ip.profile_id=pc.profile_id
                                         JOIN category c ON c.category_id=pc.category_id WHERE ip.visitor_id=?""", (vid,))]
    rated = {r["artifact_id"]: r["rating"] for r in q("SELECT artifact_id, rating FROM feedback WHERE visitor_id=?", (vid,))}
    clicked = {r["artifact_id"] for r in q("SELECT artifact_id FROM recommendation WHERE visitor_id=? AND clicked=1", (vid,))}
    dismissed = {r["artifact_id"] for r in q("SELECT artifact_id FROM recommendation WHERE visitor_id=? AND dismissed=1", (vid,))}
    if not interests and not rated and not clicked: return None, "no-profile"
    by_id = {a["artifact_id"]: a for a in arts}
    prof = " ".join(interests * 3)                                   # interests weigh most
    for aid, rt in rated.items():
        if aid in by_id and rt >= 4: prof += (" " + _text(by_id[aid])) * (rt - 3)
    for aid in clicked:
        if aid in by_id: prof += " " + _text(by_id[aid])
    vec = TfidfVectorizer(stop_words="english")
    mat = vec.fit_transform([_text(a) for a in arts] + [prof])
    sims = cosine_similarity(mat[-1], mat[:-1]).ravel()
    # Exposure-aware re-ranking (NFR-32): exhibits already shown in many lists are penalised so that no single exhibit
    # dominates the top-five lists of different visitors.
    impr = Counter({r["artifact_id"]: r["n"] for r in q("SELECT artifact_id, COUNT(*) n FROM recommendation GROUP BY artifact_id")})
    lists_shown = max(1.0, sum(impr.values()) / 5.0)
    adj = [sims[i] - 0.35 * (impr[arts[i]["artifact_id"]] / lists_shown) for i in range(len(arts))]
    order = sorted(range(len(arts)), key=lambda i: (-adj[i], arts[i]["artifact_id"]))
    out, per_cat = [], Counter()
    for i in order:                                                  # variety rule
        a = arts[i]
        if a["artifact_id"] in dismissed: continue
        if per_cat[a["category_name"]] >= max_per_category and len(out) < limit: continue
        per_cat[a["category_name"]] += 1
        a = dict(a); a["score"] = float(sims[i])
        liked = [by_id[k]["title"] for k, v in rated.items() if v >= 4 and k in by_id and by_id[k]["category_id"] == a["category_id"]]
        if a["category_name"] in interests: a["reason"] = f"Because you are interested in {a['category_name']}"
        elif liked: a["reason"] = f"Because you rated {liked[0]} highly"
        else: a["reason"] = "Similar to your interests"
        out.append(a)
        if len(out) >= limit and len(out) >= 5: break
    if len(out) < limit:                                             # fewer than five suitable: relax the variety rule
        for i in order:
            a = arts[i]
            if a["artifact_id"] in dismissed or any(o["artifact_id"] == a["artifact_id"] for o in out): continue
            a = dict(a); a["score"] = float(sims[i]); a["reason"] = "Similar to your interests"; out.append(a)
            if len(out) >= limit: break
    return out, "personalised"

@bp.get("/api/recommendations")
@require_auth("Visitor")
def recommendations():
    vid = g.user["id"]
    v = q("SELECT consent_personalisation FROM visitor WHERE visitor_id=?", (vid,), one=True)
    mode, items = "personalised", None
    if not v["consent_personalisation"]:
        mode = "popular (consent not given or withdrawn)"
        items = [dict(a, reason="Popular with visitors") for a in popular()]
    else:
        items, flag = rank_for_visitor(vid)
        if items is None:
            mode = "popular (no interests or history yet)"
            items = [dict(a, reason="Popular with visitors") for a in popular()]
    out = []
    for rank, a in enumerate(items, 1):
        if v["consent_personalisation"]:            # impressions are stored only with consent (FR-07)
            x("INSERT INTO recommendation(visitor_id,artifact_id,rank,reason,shown_at) VALUES (?,?,?,?,?)", (vid, a["artifact_id"], rank, a["reason"], iso(now())))
        out.append({"rank": rank, "artifact_id": a["artifact_id"], "title": a["title"], "category": a["category_name"],
                    "reason": a["reason"], "image_url": a["image_url"], "gallery_location": a["location"]})
    return jsonify(mode=mode, items=out)

@bp.post("/api/recommendations/<int:aid>/action")
@require_auth("Visitor")
def reco_action(aid):
    """Open (click) or dismiss a recommended exhibit (FR-28)."""
    act = request.get_json(force=True).get("action")
    col = {"click": "clicked", "dismiss": "dismissed"}.get(act)
    if not col: return jsonify(error="action must be click or dismiss"), 400
    r = q("SELECT recommendation_id FROM recommendation WHERE visitor_id=? AND artifact_id=? ORDER BY recommendation_id DESC", (g.user["id"], aid), one=True)
    if not r: return jsonify(error="no such recommendation"), 404
    x(f"UPDATE recommendation SET {col}=1 WHERE recommendation_id=?", (r["recommendation_id"],))
    return jsonify(message="stored")

@bp.post("/api/feedback")
@require_auth("Visitor")
def feedback():
    d = request.get_json(force=True)
    try: aid, rating = int(d["artifact_id"]), int(d["rating"])
    except Exception: return jsonify(error="artifact_id and rating required"), 400
    if not 1 <= rating <= 5: return jsonify(error="rating must be 1-5"), 400
    if not q("SELECT 1 FROM artifact WHERE artifact_id=?", (aid,), one=True): return jsonify(error="unknown exhibit"), 404
    x("""INSERT INTO feedback(visitor_id,artifact_id,rating,comment,submitted_at) VALUES (?,?,?,?,?)
         ON CONFLICT(visitor_id,artifact_id) DO UPDATE SET rating=excluded.rating, comment=excluded.comment, submitted_at=excluded.submitted_at""",
      (g.user["id"], aid, rating, d.get("comment"), iso(now())))
    return jsonify(message="feedback stored"), 201

@bp.get("/api/exhibits/<int:aid>")
@require_auth("Visitor")
def exhibit(aid):
    """FR-27: exhibit information for the page opened by scanning the exhibit QR code."""
    a = q("""SELECT a.artifact_id,a.title,a.description,a.period,a.origin,a.location,a.image_url,a.category_id,c.name AS category
             FROM artifact a JOIN category c ON c.category_id=a.category_id WHERE a.artifact_id=? AND a.is_archived=0""", (aid,), one=True)
    if not a: return jsonify(error="not found"), 404
    a["related"] = q("SELECT artifact_id,title FROM artifact WHERE category_id=? AND artifact_id<>? AND is_archived=0 LIMIT 4", (a["category_id"], aid))
    a["ar_enabled"] = bool(q("SELECT 1 FROM ar_content WHERE artifact_id=? AND published=1", (aid,), one=True))
    return jsonify(a)

@bp.get("/api/exhibits/by-code/<code>")
@require_auth("Visitor")
def exhibit_by_code(code):
    a = q("SELECT artifact_id FROM artifact WHERE qr_code_value=? AND is_archived=0", (code,), one=True)
    return exhibit(a["artifact_id"]) if a else (jsonify(error="unknown code"), 404)

# ---------------- chatbot (FR-31, FR-32) and knowledge base (FR-33) ----------------
# Domain synonyms and light stemming so that "photos" matches "photography" and "cost" matches "price".
SYNONYMS = {"open": "hour", "opening": "hour", "opens": "hour", "hours": "hour", "close": "hour", "closing": "hour", "time": "hour", "times": "hour",
            "photo": "photograph", "photos": "photograph", "photography": "photograph", "photographs": "photograph", "camera": "photograph", "cameras": "photograph", "pictures": "photograph",
            "cost": "price", "costs": "price", "much": "price", "fee": "price", "fees": "price", "ticket": "price", "tickets": "price", "cheap": "price", "pay": "price",
            "wheelchair": "access", "wheelchairs": "access", "accessible": "access", "accessibility": "access", "disabled": "access", "lift": "access", "lifts": "access"}

def _stem(w):
    for suf in ("ing", "es", "ed", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf): return w[: -len(suf)]
    return w

def tokens(text, language="EN"):
    words = re.findall(r"\w+", text.lower())
    if language != "EN": return words
    return [SYNONYMS.get(w) or _stem(w) for w in words if w not in ENGLISH_STOP_WORDS]

def retrieve(question, language):
    entries = q("SELECT * FROM knowledge_entry WHERE status='published' AND language=?", (language,))
    if not entries: return None, 0.0
    vec = TfidfVectorizer(analyzer=lambda t: tokens(t, language))
    try: mat = vec.fit_transform([e["question"] + " " + e["answer"] for e in entries] + [question])
    except ValueError: return None, 0.0
    sims = cosine_similarity(mat[-1], mat[:-1]).ravel()
    best = int(sims.argmax())
    return (entries[best], float(sims[best])) if sims[best] > 0 else (None, 0.0)

def _owned_session(sid, lang):
    """Reuse the visitor's chat session or open a new one (a session id from another visitor is ignored)."""
    if sid and q("SELECT 1 FROM chat_session WHERE session_id=? AND visitor_id=?", (sid, g.user["id"]), one=True): return sid
    return x("INSERT INTO chat_session(visitor_id,language,started_at) VALUES (?,?,?)", (g.user["id"], lang, iso(now())))

def _history(sid, n=6):
    rows = q("SELECT question, answer FROM chat_turn WHERE session_id=? AND was_fallback=0 AND answer IS NOT NULL ORDER BY turn_id DESC LIMIT ?", (sid, n))
    out = []
    for r in reversed(rows): out += [{"role": "user", "content": r["question"]}, {"role": "assistant", "content": r["answer"]}]
    return out

def _llm_context(question):
    """Published knowledge entries (best matches first, any language) + exhibits on display. This is everything the model may answer from."""
    entries = q("SELECT * FROM knowledge_entry WHERE status='published' ORDER BY entry_id")
    best, best_score = None, 0.0
    if entries:
        try:
            vec = TfidfVectorizer(analyzer=lambda t: tokens(t, "EN"))
            mat = vec.fit_transform([e["question"] + " " + e["answer"] for e in entries] + [question])
            sims = cosine_similarity(mat[-1], mat[:-1]).ravel()
            order = sorted(range(len(entries)), key=lambda i: -sims[i])
            if sims[order[0]] > 0.1: best, best_score = entries[order[0]], float(sims[order[0]])
            entries = [entries[i] for i in order]
        except ValueError: pass
    lines = [f"[Q&A] Q: {e['question']} A: {e['answer']}" for e in entries[:25]]
    lines += [f"[EXHIBIT] {a['title']} ({a['category_name']}), {a['period']}, from {a['origin']}, shown in {a['location']}. {a['description']}" for a in _on_display()[:40]]
    return "\n".join(lines), best, best_score

def chat_events(question, lang, sid):
    """Yields ('delta', text) pieces and a final ('done', {...}). Real-time language-model answer grounded in the museum information;
    without a language model (or when it is down) the extractive knowledge-base answer is used instead (NFR-13)."""
    help_ = current_app.config["HELPDESK"]
    if llm_configured():
        context, best, score = _llm_context(question)
        hist, full, held, started = _history(sid), "", "", False
        try:
            for piece in stream_llm(question, context, hist):
                started = True; full += piece; held += piece
                i = held.find("[")
                if i == -1: yield "delta", held; held = ""
                elif i > 0: yield "delta", held[:i]; held = held[i:]
                elif len(held) > len(NO_ANSWER) or not NO_ANSWER.startswith(held[:len(NO_ANSWER)]): yield "delta", held.replace(NO_ANSWER, ""); held = ""
            fallback = NO_ANSWER in full
            if held and NO_ANSWER not in held: yield "delta", held
            ans = full.replace(NO_ANSWER, "").strip()
            if not ans: ans, fallback = "Sorry, I cannot answer that from the museum's information. " + help_, True
            x("INSERT INTO chat_turn(session_id,entry_id,question,answer,was_fallback,created_at) VALUES (?,?,?,?,?,?)",
              (sid, None if fallback or not best else best["entry_id"], question, None if fallback else ans, 1 if fallback else 0, iso(now())))
            yield "done", {"fallback": fallback, "answer": ans, "mode": "llm", "source": None if fallback or not best else (best["source_page"] or f"entry {best['entry_id']}")}
            return
        except GatewayUnavailable:
            if started: yield "delta", " …"; yield "done", {"fallback": False, "answer": full.strip(), "mode": "llm"}; return   # connection broke mid-answer
            # nothing was sent yet: use the knowledge-base answer below
    entry, score = retrieve(question, lang)
    if entry is None or score < current_app.config["CHATBOT_THRESHOLD"]:
        ans = "Sorry, I cannot answer that from the museum's information. " + help_
        x("INSERT INTO chat_turn(session_id,question,answer,was_fallback,created_at) VALUES (?,?,?,?,?)", (sid, question, None, 1, iso(now())))
        yield "delta", ans; yield "done", {"fallback": True, "answer": ans, "mode": "knowledge-base"}; return
    ans = generate_answer(question, [entry])
    x("INSERT INTO chat_turn(session_id,entry_id,question,answer,was_fallback,created_at) VALUES (?,?,?,?,?,?)", (sid, entry["entry_id"], question, ans, 0, iso(now())))
    yield "delta", ans
    yield "done", {"fallback": False, "answer": ans, "mode": "knowledge-base", "source": entry["source_page"] or f"entry {entry['entry_id']}", "relevance": round(score, 2)}

def _chat_args():
    d = request.get_json(force=True, silent=True) or {}; question = (d.get("question") or "").strip()[:1000]
    lang = d.get("language", "EN")
    if not question or lang not in ("EN", "AR"): return None
    return question, lang, _owned_session(d.get("session_id"), lang)

@bp.post("/api/chat")
@require_auth("Visitor")
def chat():
    """SPEC-4: answer only from published museum information, otherwise fall back and log. (Non-streaming variant.)"""
    a = _chat_args()
    if not a: return jsonify(error="question and language (EN/AR) required"), 400
    question, lang, sid = a; out = {}
    for kind, val in chat_events(question, lang, sid):
        if kind == "done": out = val
    out.pop("mode", None)
    return jsonify(session_id=sid, **out)

@bp.post("/api/chat/stream")
@require_auth("Visitor")
def chat_stream():
    """Server-sent events: 'meta' (session), 'delta' (text pieces as they are produced), 'done' (final answer, fallback flag, source)."""
    a = _chat_args()
    if not a: return jsonify(error="question and language (EN/AR) required"), 400
    question, lang, sid = a
    def gen():
        yield "event: meta\ndata: " + json.dumps({"session_id": sid, "mode": "llm" if llm_configured() else "knowledge-base"}) + "\n\n"
        try:
            for kind, val in chat_events(question, lang, sid):
                yield f"event: {kind}\ndata: " + json.dumps({"text": val} if kind == "delta" else {**val, "session_id": sid}) + "\n\n"
        except Exception as e:
            current_app.logger.exception(e)
            yield "event: error\ndata: " + json.dumps({"error": "internal error"}) + "\n\n"
    return Response(stream_with_context(gen()), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@bp.get("/api/kb/entries")
@require_auth("Staff")
def kb_list():
    return jsonify(q("SELECT * FROM knowledge_entry ORDER BY entry_id"))

@bp.post("/api/kb/entries")
@require_auth("Staff")
def kb_add():
    d = request.get_json(force=True)
    if not d.get("question") or not d.get("answer") or d.get("language") not in ("EN", "AR"): return jsonify(error="question, answer, language required"), 400
    eid = x("INSERT INTO knowledge_entry(artifact_id,question,answer,language,status,source_page,updated_by,updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (d.get("artifact_id"), d["question"], d["answer"], d["language"], "draft", d.get("source_page"), g.user["id"], iso(now())))
    return jsonify(entry_id=eid), 201

@bp.patch("/api/kb/entries/<int:eid>")
@require_auth("Staff")
def kb_edit(eid):
    d = request.get_json(force=True)
    if "status" in d and d["status"] not in ("draft", "published", "unpublished"): return jsonify(error="invalid status"), 400
    for f in ("question", "answer", "language", "status", "source_page"):
        if f in d: x(f"UPDATE knowledge_entry SET {f}=?, updated_by=?, updated_at=? WHERE entry_id=?", (d[f], g.user["id"], iso(now()), eid))
    return jsonify(message="updated")

@bp.get("/api/kb/unanswered")
@require_auth("Staff")
def kb_unanswered():
    return jsonify(q("SELECT question, COUNT(*) AS asks FROM chat_turn WHERE was_fallback=1 GROUP BY question ORDER BY asks DESC, question"))
