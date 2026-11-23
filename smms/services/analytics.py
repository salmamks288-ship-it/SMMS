"""S6 Analytics & Reporting (FR-37..FR-41, FR-26 display). Aggregated values only - no personal identifiers (FR-41, NFR-22)."""
import csv, io
from flask import Blueprint, current_app, g, jsonify, request, Response
from ..db import q, x, iso, local_now
from ..security import require_auth

bp = Blueprint("analytics", __name__)
now = lambda: current_app.config["NOW"]()

def _filters(src):
    f = {"from": src.get("from"), "to": src.get("to"), "exhibition_id": src.get("exhibition_id"), "ticket_type_id": src.get("ticket_type_id")}
    where, args = ["b.status IN ('confirmed','completed')"], []
    if f["from"]: where.append("s.slot_date >= ?"); args.append(f["from"])
    if f["to"]: where.append("s.slot_date <= ?"); args.append(f["to"])
    if f["exhibition_id"]: where.append("s.exhibition_id = ?"); args.append(f["exhibition_id"])
    if f["ticket_type_id"]: where.append("b.ticket_type_id = ?"); args.append(f["ticket_type_id"])
    return f, " AND ".join(where), args

BASE = "FROM booking b JOIN time_slot s ON s.slot_id=b.slot_id JOIN ticket_type t ON t.ticket_type_id=b.ticket_type_id"

def sales(src, trend=True):
    f, w, a = _filters(src)
    tot = q(f"SELECT COALESCE(SUM(b.quantity),0) tickets, COALESCE(SUM(b.total_price),0) revenue, COUNT(*) bookings {BASE} WHERE {w}", a, one=True)
    out = _sales_core(src, f, w, a, tot)
    return with_trend(out, src) if trend else out

def _sales_core(src, f, w, a, tot):
    return {"filters": f, "tickets_sold": tot["tickets"], "revenue": round(tot["revenue"], 2), "bookings": tot["bookings"],
            "avg_booking_value": round(tot["revenue"] / tot["bookings"], 2) if tot["bookings"] else 0.0,
            "by_date": q(f"SELECT s.slot_date date, SUM(b.quantity) tickets, SUM(b.total_price) revenue {BASE} WHERE {w} GROUP BY s.slot_date ORDER BY s.slot_date", a),
            "by_slot": q(f"SELECT s.slot_date date, s.start_time slot, SUM(b.quantity) tickets {BASE} WHERE {w} GROUP BY s.slot_date, s.start_time ORDER BY 1,2", a),
            "by_ticket_type": q(f"SELECT t.name ticket_type, SUM(b.quantity) tickets, SUM(b.total_price) revenue {BASE} WHERE {w} GROUP BY t.name ORDER BY tickets DESC", a),
            "peak_hours": q(f"SELECT substr(s.start_time,1,2) hour, SUM(b.quantity) tickets {BASE} WHERE {w} GROUP BY hour ORDER BY tickets DESC, hour", a)}

def with_trend(d, src):
    """Table 36: peak hour, share of each ticket type and change against the previous period of the same length."""
    from datetime import date, timedelta
    tot = d["tickets_sold"]
    for r in d["by_ticket_type"]: r["share_pct"] = round(100.0 * r["tickets"] / tot, 1) if tot else 0.0
    d["peak_hour"] = (d["peak_hours"][0]["hour"] + ":00") if d["peak_hours"] else None
    d["change_vs_previous_pct"] = None
    try:
        if src.get("from") and src.get("to"):
            f0, t0 = date.fromisoformat(src["from"]), date.fromisoformat(src["to"])
            span = (t0 - f0).days + 1
            prev = sales({"from": str(f0 - timedelta(days=span)), "to": str(f0 - timedelta(days=1)), "exhibition_id": src.get("exhibition_id"), "ticket_type_id": src.get("ticket_type_id")}, trend=False)
            if prev["tickets_sold"]: d["change_vs_previous_pct"] = round(100.0 * (tot - prev["tickets_sold"]) / prev["tickets_sold"], 1)
    except ValueError:
        pass
    return d

def visitors_per_day():
    return q("SELECT substr(validated_at,1,10) date, COUNT(*) visitors FROM entry_validation WHERE result='valid' GROUP BY date ORDER BY date")

def engagement():
    shown = q("SELECT COUNT(*) n, COALESCE(SUM(clicked),0) c FROM recommendation", one=True)
    turns = q("SELECT COUNT(*) n, COALESCE(SUM(was_fallback),0) u FROM chat_turn", one=True)
    return {"most_viewed_exhibits": q("""SELECT a.title,
                                          (SELECT COALESCE(SUM(clicked),0) FROM recommendation r WHERE r.artifact_id=a.artifact_id)
                                            + (SELECT COUNT(*) FROM feedback f WHERE f.artifact_id=a.artifact_id) AS interactions,
                                          (SELECT ROUND(AVG(rating),1) FROM feedback f WHERE f.artifact_id=a.artifact_id) AS avg_rating,
                                          (SELECT COUNT(*) FROM ar_session s JOIN ar_content c ON c.content_id=s.content_id WHERE c.artifact_id=a.artifact_id) AS ar_sessions
                                          FROM artifact a WHERE a.is_archived=0 ORDER BY interactions DESC, a.title LIMIT 10"""),
            "recommendation_click_through_rate": round(shown["c"] / shown["n"], 3) if shown["n"] else 0.0,
            "chatbot_questions": turns["n"], "chatbot_unanswered_rate": round(turns["u"] / turns["n"], 3) if turns["n"] else 0.0,
            "ar_sessions": q("SELECT COUNT(*) n FROM ar_session", one=True)["n"]}

def inventory():
    return {"by_status": q("SELECT status, COUNT(*) n FROM artifact WHERE is_archived=0 GROUP BY status"),
            "by_category": q("SELECT c.name category, COUNT(*) n FROM artifact a JOIN category c ON c.category_id=a.category_id WHERE a.is_archived=0 GROUP BY c.name"),
            "by_condition": q("SELECT condition, COUNT(*) n FROM artifact WHERE is_archived=0 GROUP BY condition"),
            "inspection_overdue": q("SELECT artifact_id, title, inspection_date FROM artifact WHERE is_archived=0 AND inspection_date IS NOT NULL AND inspection_date < ?", (iso(local_now())[:10],))}

@bp.get("/api/analytics/summary")
@require_auth("Manager")
def summary():
    d = sales(request.args)
    d["visitors_per_day"] = visitors_per_day(); d.update(engagement())
    live = q("SELECT visitors_in FROM live_visitor_counter WHERE counter_date=?", (iso(local_now())[:10],), one=True)
    d["visitors_in_museum_now"] = live["visitors_in"] if live else 0
    return jsonify(d)

@bp.get("/api/analytics/inventory")
@require_auth("Manager", "Staff")
def inventory_summary():
    return jsonify(inventory())

def _rows(data):
    rows = [["Section", "Item", "Value", "Extra"]]
    rows += [["Summary", "Tickets sold", data["tickets_sold"], ""], ["Summary", "Revenue (AED)", data["revenue"], ""], ["Summary", "Bookings", data["bookings"], ""],
             ["Summary", "Average booking value (AED)", data["avg_booking_value"], ""], ["Summary", "Peak hour", data["peak_hour"] or "-", ""],
             ["Summary", "Change vs previous period (%)", "n/a" if data["change_vs_previous_pct"] is None else data["change_vs_previous_pct"], ""]]
    rows += [["Tickets per day", r["date"], r["tickets"], r["revenue"]] for r in data["by_date"]]
    rows += [["Sales by ticket type", r["ticket_type"], r["tickets"], f"{r['revenue']} AED / {r['share_pct']}%"] for r in data["by_ticket_type"]]
    rows += [["Peak hour", r["hour"] + ":00", r["tickets"], ""] for r in data["peak_hours"]]
    rows += [["Top exhibits", r["title"], r["interactions"], f"rating {r['avg_rating'] if r['avg_rating'] is not None else '-'}; AR sessions {r['ar_sessions']}"] for r in engagement()["most_viewed_exhibits"][:5]]
    return rows

def _filter_text(d):
    names = {}
    if d.get("exhibition_id"):
        r = q("SELECT title FROM exhibition WHERE exhibition_id=?", (d["exhibition_id"],), one=True); names["Exhibition"] = r["title"] if r else d["exhibition_id"]
    if d.get("ticket_type_id"):
        r = q("SELECT name FROM ticket_type WHERE ticket_type_id=?", (d["ticket_type_id"],), one=True); names["Ticket type"] = r["name"] if r else d["ticket_type_id"]
    return ", ".join(f"{k}: {v}" for k, v in names.items()) or "none (all exhibitions and ticket types)"

@bp.post("/api/reports/export")
@require_auth("Manager")
def export():
    """FR-40: export the filtered view as PDF or CSV (layout of Table 36 / Fig. 4.12). Only aggregated values are exported (FR-41)."""
    d = request.get_json(force=True); fmt = (d.get("format") or "").upper()
    if fmt not in ("PDF", "CSV"): return jsonify(error="format must be PDF or CSV"), 400
    data = sales(d); rows = _rows(data)
    x("INSERT INTO report_export(generated_by,period_start,period_end,filter_exhibition_id,filter_ticket_type_id,format,generated_at) VALUES (?,?,?,?,?,?,?)",
      (g.user["id"], d.get("from") or "1970-01-01", d.get("to") or iso(local_now())[:10], d.get("exhibition_id") or None, d.get("ticket_type_id") or None, fmt, iso(now())))
    if fmt == "CSV":
        buf = io.StringIO(); csv.writer(buf).writerows(rows)
        return Response(buf.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=report.csv"})
    return Response(_pdf(d, data, engagement()["most_viewed_exhibits"][:5]), mimetype="application/pdf", headers={"Content-Disposition": "attachment; filename=report.pdf"})

def _pdf(d, data, top):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    st = getSampleStyleSheet(); buf = io.BytesIO()
    who = q("SELECT COALESCE(m.full_name, a.email) n FROM account a LEFT JOIN manager m ON m.manager_id=a.account_id WHERE a.account_id=?", (g.user["id"],), one=True)["n"]
    def table(rows, widths=None):
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2d4a")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 8)]))
        return t
    chg = "n/a" if data["change_vs_previous_pct"] is None else f"{data['change_vs_previous_pct']:+}%"
    parts = [Paragraph("Smart Museum Management System", st["Title"]), Paragraph("Ticket Sales and Visitor Report", st["Heading2"]),
             Paragraph(f"Period: {d.get('from') or 'all'} to {d.get('to') or 'all'}<br/>Filters: {_filter_text(d)}<br/>Generated by: {who} | Generated on: {iso(now())} UTC | Format: PDF", st["Normal"]), Spacer(1, 8),
             Paragraph("1. Summary", st["Heading3"]),
             table([["Tickets sold", "Revenue (AED)", "Visitors admitted", "Peak hour", "Avg booking (AED)", "Change vs previous"],
                    [data["tickets_sold"], data["revenue"], q("SELECT COUNT(*) n FROM entry_validation WHERE result='valid'", one=True)["n"], data["peak_hour"] or "-", data["avg_booking_value"], chg]]),
             Spacer(1, 8), Paragraph("2. Tickets sold per day", st["Heading3"])]
    dr = Drawing(170 * mm, 60 * mm); ch = VerticalBarChart(); ch.x, ch.y, ch.width, ch.height = 30, 20, 440, 100
    ch.data = [[r["tickets"] for r in data["by_date"]] or [0]]; ch.categoryAxis.categoryNames = [r["date"][5:] for r in data["by_date"]] or ["-"]
    ch.categoryAxis.labels.fontSize = 6; ch.valueAxis.valueMin = 0; ch.bars[0].fillColor = colors.HexColor("#1f2d4a"); dr.add(ch); parts += [dr]
    parts += [Paragraph("3. Sales by ticket type", st["Heading3"]),
              table([["Ticket type", "Tickets", "Revenue (AED)", "Share (%)"]] + [[r["ticket_type"], r["tickets"], r["revenue"], r["share_pct"]] for r in data["by_ticket_type"]]),
              Spacer(1, 8), Paragraph("4. Top exhibits", st["Heading3"]),
              table([["Exhibit", "Views", "Rating", "AR sessions"]] + [[r["title"], r["interactions"], r["avg_rating"] if r["avg_rating"] is not None else "-", r["ar_sessions"]] for r in top]),
              Spacer(1, 10), Paragraph("Only aggregated values are shown; no personal identifiers are included.", st["Italic"])]
    def footer(c, doc):
        c.saveState(); c.setFont("Helvetica", 8); c.drawRightString(A4[0] - 15 * mm, 10 * mm, f"Page {doc.page}"); c.restoreState()
    SimpleDocTemplate(buf, pagesize=A4).build(parts, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
