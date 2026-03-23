import io
import json
import os
import smtplib
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import openpyxl
from flask import (
    Blueprint, flash, redirect, render_template,
    request, send_file, url_for
)
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from utils.db import get_db
from utils.config import STATIC_FOLDER
from utils.decorators import login_required, module_required

odmori_bp = Blueprint("odmori", __name__, url_prefix="/odmori")

# ─────────────────────────────────────────────────────────────
# EMAIL КОНФИГУРАЦИЈА
# ─────────────────────────────────────────────────────────────
_EMAIL_HOST     = "smtp.gmail.com"
_EMAIL_PORT     = 587
_EMAIL_USER     = "fersedoo@gmail.com"
_EMAIL_PASSWORD = "ejvu srce tvls wqtw"

_LOGO_PATH = r"C:\Users\Server\Desktop\Proekt Fersedo\static\logo2.png"

TIP_LABELS = {
    "boluvanje":       "Болување",
    "privatni_raboti": "Приватни работи",
    "sluzben_pat":     "Службен пат",
    "obuka":           "Обука",
    "drugo":           "Друго",
    "vtora_smena":     "Втора смена",
}
TIP_COLORS = {
    "boluvanje":       "#ef4444",
    "privatni_raboti": "#f59e0b",
    "sluzben_pat":     "#3b82f6",
    "obuka":           "#8b5cf6",
    "drugo":           "#6b7280",
    "vtora_smena":     "#7c3aed",
}

_ODMOR_COLOR  = "#10b981"
_VTORA_COLOR  = "#7c3aed"
_VTORA_LIGHT  = "#ede9fe"
_VTORA_DARK   = "#4c1d95"


# ─────────────────────────────────────────────────────────────
# LOGO HELPER
# ─────────────────────────────────────────────────────────────

def _get_logo_path():
    if os.path.exists(_LOGO_PATH):
        return _LOGO_PATH
    for name in ("logo2.png", "logo.png", "logo.webp"):
        p = os.path.join(STATIC_FOLDER, name)
        if os.path.exists(p):
            return p
    return None


def _build_email_with_logo(subject, html_body):
    logo_path = _get_logo_path()
    if logo_path:
        msg_root = MIMEMultipart("related")
        msg_root["From"]    = _EMAIL_USER
        msg_root["Subject"] = subject
        msg_alt = MIMEMultipart("alternative")
        msg_alt.attach(MIMEText(html_body, "html", "utf-8"))
        msg_root.attach(msg_alt)
        try:
            with open(logo_path, "rb") as f:
                img_data = f.read()
            img = MIMEImage(img_data)
            img.add_header("Content-ID", "<fersedo_logo>")
            img.add_header("Content-Disposition", "inline", filename="logo.png")
            msg_root.attach(img)
            print(f"[LOGO] Вчитано: {logo_path}")
            return msg_root, True
        except Exception as e:
            print(f"[LOGO] Грешка при читање: {e}")
    msg = MIMEMultipart("alternative")
    msg["From"]    = _EMAIL_USER
    msg["Subject"] = subject
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg, False


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def ensure_odmor_salda_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odmor_salda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vraboten_id INTEGER NOT NULL,
            godina INTEGER NOT NULL,
            vkupno_dena INTEGER DEFAULT 20,
            UNIQUE(vraboten_id, godina),
            FOREIGN KEY(vraboten_id) REFERENCES vraboteni(id) ON DELETE CASCADE
        )
    """)


def ensure_manager_emails_table(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS otsustva_manager_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            ime TEXT DEFAULT '',
            aktiven INTEGER DEFAULT 1
        )
    """)


def ensure_salda_for_all(cursor, godina):
    ensure_odmor_salda_table(cursor)
    vraboteni = cursor.execute("SELECT id FROM vraboteni").fetchall()
    for v in vraboteni:
        cursor.execute("""
            INSERT OR IGNORE INTO odmor_salda (vraboten_id, godina, vkupno_dena)
            VALUES (?, ?, 20)
        """, (v["id"], godina))


def calc_working_days(datum_od, datum_do, praznici):
    try:
        start = datetime.strptime(datum_od, "%Y-%m-%d").date()
        end   = datetime.strptime(datum_do, "%Y-%m-%d").date()
    except Exception:
        return 0
    count = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5 and cur.strftime("%Y-%m-%d") not in praznici:
            count += 1
        cur += timedelta(days=1)
    return count


def get_saldo_all(cursor, godina):
    ensure_salda_for_all(cursor, godina)
    praznici = {r["datum"] for r in cursor.execute("SELECT datum FROM nerabotni_deni").fetchall()}
    baranja  = cursor.execute("""
        SELECT vraboten_id, datum_od, datum_do
        FROM baranja_odmor
        WHERE status = 'approved' AND strftime('%Y', datum_od) = ?
    """, (str(godina),)).fetchall()
    iskoristeni = defaultdict(int)
    for b in baranja:
        iskoristeni[b["vraboten_id"]] += calc_working_days(b["datum_od"], b["datum_do"], praznici)
    salda = cursor.execute(
        "SELECT vraboten_id, vkupno_dena FROM odmor_salda WHERE godina = ?", (godina,)
    ).fetchall()
    result = {}
    for s in salda:
        vid    = s["vraboten_id"]
        vkupno = s["vkupno_dena"]
        isk    = iskoristeni.get(vid, 0)
        result[vid] = {"vkupno": vkupno, "iskoristeni": isk, "preostanati": max(0, vkupno - isk)}
    return result


def _get_manager_emails():
    try:
        conn = get_db()
        cursor = conn.cursor()
        ensure_manager_emails_table(cursor)
        conn.commit()
        rows = cursor.execute(
            "SELECT email FROM otsustva_manager_emails WHERE aktiven = 1"
        ).fetchall()
        conn.close()
        return [r["email"] for r in rows]
    except Exception as e:
        print(f"[MANAGER EMAIL] Грешка: {e}")
        return []


def _isprati_email_do_menadzeri(emails, subject, html, log_prefix="[EMAIL]"):
    if not emails:
        print(f"{log_prefix} Нема примачи.")
        return
    try:
        msg, has_logo = _build_email_with_logo(subject, html)
        msg["To"] = ", ".join(emails)
        with smtplib.SMTP(_EMAIL_HOST, _EMAIL_PORT, timeout=15) as server:
            server.ehlo(); server.starttls(); server.ehlo()
            server.login(_EMAIL_USER, _EMAIL_PASSWORD)
            server.sendmail(_EMAIL_USER, emails, msg.as_string())
        print(f"{log_prefix} Испратено до: {emails} (лого: {'да' if has_logo else 'не'})")
    except Exception as e:
        print(f"{log_prefix} Грешка: {e}")


# ─────────────────────────────────────────────────────────────
# ПОМОШНА ФУНКЦИЈА: HTML блок за одмори
# ─────────────────────────────────────────────────────────────

def _build_odmori_rows_html(odmori_list):
    if not odmori_list:
        return """
        <tr>
          <td colspan="2"
              style="padding:28px 16px;text-align:center;
                     color:#94a3b8;font-size:14px;font-style:italic;
                     font-family:Arial,Helvetica,sans-serif;">
            Нема одобрени одмори за овој период
          </td>
        </tr>"""

    rows_html = ""
    for idx, o in enumerate(odmori_list):
        row_bg    = "#f0fdf4" if idx % 2 == 0 else "#ffffff"
        zabeleska = o.get("zabeleska") or ""
        pad_b     = "3px" if zabeleska else "11px"
        period_txt = (
            f"{_fmt_date(o['datum_od'])} – {_fmt_date(o['datum_do'])}"
            f"&nbsp;&nbsp;<span style='color:#6b7280;font-weight:normal;'>"
            f"({o['working_days']} раб. дена)</span>"
        )

        zab_row = ""
        if zabeleska:
            zab_row = f"""
            <tr>
              <td colspan="2" bgcolor="{row_bg}"
                  style="background-color:{row_bg};padding:3px 14px 11px 14px;
                         border-bottom:1px solid #d1fae5;font-size:12px;color:#64748b;
                         font-family:Arial,Helvetica,sans-serif;">
                <strong style="color:#94a3b8;">ЗАБЕЛЕШКА:</strong> {zabeleska}
              </td>
            </tr>"""

        rows_html += f"""
        <tr>
          <td bgcolor="{row_bg}"
              style="background-color:{row_bg};padding:11px 14px {pad_b} 14px;
                     vertical-align:top;
                     border-bottom:{'none' if zabeleska else '1px solid #d1fae5'};">
            <p style="margin:0 0 4px 0;font-weight:bold;font-size:14px;
                       color:#1e293b;font-family:Arial,Helvetica,sans-serif;">
              {o['prezime']} {o['ime']}
            </p>
            <p style="margin:0;font-size:12px;font-weight:bold;
                       color:{_ODMOR_COLOR};font-family:Arial,Helvetica,sans-serif;">
              {period_txt}
            </p>
          </td>
          <td bgcolor="{row_bg}"
              style="background-color:{row_bg};padding:11px 14px {pad_b} 14px;
                     vertical-align:top;text-align:right;
                     border-bottom:{'none' if zabeleska else '1px solid #d1fae5'};">
            <table cellpadding="0" cellspacing="0" border="0"
                   style="display:inline-table;margin-left:auto;">
              <tr>
                <td bgcolor="#d1fae5"
                    style="background-color:#d1fae5;padding:3px 10px;font-size:11px;
                           font-weight:bold;color:#065f46;
                           font-family:Arial,Helvetica,sans-serif;white-space:nowrap;">
                  Одмор
                </td>
              </tr>
            </table>
          </td>
        </tr>
        {zab_row}"""

    return rows_html


def _fmt_date(d_str):
    try:
        return datetime.strptime(d_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    except Exception:
        return d_str


def _get_odmori_for_date(cursor, date_str, praznici):
    rows = cursor.execute("""
        SELECT v.ime, v.prezime, b.datum_od, b.datum_do, b.zabeleska
        FROM baranja_odmor b
        JOIN vraboteni v ON b.vraboten_id = v.id
        WHERE b.status = 'approved'
          AND b.datum_od <= ?
          AND b.datum_do >= ?
        ORDER BY v.prezime, v.ime
    """, (date_str, date_str)).fetchall()

    result = []
    for r in rows:
        wd = calc_working_days(r["datum_od"], r["datum_do"], praznici)
        result.append({
            "ime":          r["ime"],
            "prezime":      r["prezime"],
            "datum_od":     r["datum_od"],
            "datum_do":     r["datum_do"],
            "working_days": wd,
            "zabeleska":    r["zabeleska"] or "",
        })
    return result


def _get_odmori_for_range(cursor, date_from_str, date_to_str, praznici):
    rows = cursor.execute("""
        SELECT v.ime, v.prezime, b.datum_od, b.datum_do, b.zabeleska
        FROM baranja_odmor b
        JOIN vraboteni v ON b.vraboten_id = v.id
        WHERE b.status = 'approved'
          AND b.datum_od <= ?
          AND b.datum_do >= ?
        ORDER BY b.datum_od ASC, v.prezime, v.ime
    """, (date_to_str, date_from_str)).fetchall()

    result = []
    for r in rows:
        wd = calc_working_days(r["datum_od"], r["datum_do"], praznici)
        result.append({
            "ime":          r["ime"],
            "prezime":      r["prezime"],
            "datum_od":     r["datum_od"],
            "datum_do":     r["datum_do"],
            "working_days": wd,
            "zabeleska":    r["zabeleska"] or "",
        })
    return result


def _build_odmori_section_html(odmori_rows_html, count):
    return f"""
    <tr>
      <td class="mob-pad" style="padding:18px 24px 8px 24px;">
        <p style="margin:0;font-size:10px;font-weight:bold;color:#94a3b8;
                  font-family:Arial,Helvetica,sans-serif;
                  text-transform:uppercase;letter-spacing:1px;">
          Одобрени одмори
        </p>
      </td>
    </tr>
    <tr>
      <td class="mob-pad" style="padding:0 24px 0 24px;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr bgcolor="{_ODMOR_COLOR}" style="background-color:{_ODMOR_COLOR};">
            <td style="padding:9px 14px;font-size:11px;font-weight:bold;
                       color:#ffffff;font-family:Arial,Helvetica,sans-serif;">
              Вработен / Период
            </td>
            <td style="padding:9px 14px;font-size:11px;font-weight:bold;
                       color:#ffffff;font-family:Arial,Helvetica,sans-serif;
                       text-align:right;">
              Статус ({count})
            </td>
          </tr>
          {odmori_rows_html}
        </table>
      </td>
    </tr>
    <tr><td style="padding-bottom:8px;"></td></tr>"""


def _build_vtora_smena_rows_html(vtora_list):
    """Гради HTML редови за втора смена — иста структура како одмори."""
    if not vtora_list:
        return """
        <tr>
          <td colspan="2"
              style="padding:20px 16px;text-align:center;
                     color:#94a3b8;font-size:14px;font-style:italic;
                     font-family:Arial,Helvetica,sans-serif;">
            Нема вработени на втора смена
          </td>
        </tr>"""

    rows_html = ""
    for idx, o in enumerate(vtora_list):
        row_bg    = "#f5f3ff" if idx % 2 == 0 else "#ffffff"
        zabeleska = o.get("zabeleska") or ""
        pad_b     = "3px" if zabeleska else "11px"

        zab_row = ""
        if zabeleska:
            zab_row = f"""
            <tr>
              <td colspan="2" bgcolor="{row_bg}"
                  style="background-color:{row_bg};padding:3px 14px 11px 14px;
                         border-bottom:1px solid {_VTORA_LIGHT};font-size:12px;color:#64748b;
                         font-family:Arial,Helvetica,sans-serif;">
                <strong style="color:#94a3b8;">ЗАБЕЛЕШКА:</strong> {zabeleska}
              </td>
            </tr>"""

        rows_html += f"""
        <tr>
          <td bgcolor="{row_bg}"
              style="background-color:{row_bg};padding:11px 14px {pad_b} 14px;
                     vertical-align:top;
                     border-bottom:{'none' if zabeleska else f'1px solid {_VTORA_LIGHT}'};">
            <p style="margin:0 0 4px 0;font-weight:bold;font-size:14px;
                       color:#1e293b;font-family:Arial,Helvetica,sans-serif;">
              {o['prezime']} {o['ime']}
            </p>
            <p style="margin:0;font-size:12px;font-weight:bold;
                       color:{_VTORA_COLOR};font-family:Arial,Helvetica,sans-serif;">
              Втора смена
              <span style="font-weight:normal;color:#64748b;">
                &nbsp;&middot;&nbsp; {o['casovi']:.0f}h
              </span>
            </p>
          </td>
          <td bgcolor="{row_bg}"
              style="background-color:{row_bg};padding:11px 14px {pad_b} 14px;
                     vertical-align:top;text-align:right;
                     border-bottom:{'none' if zabeleska else f'1px solid {_VTORA_LIGHT}'};">
            <table cellpadding="0" cellspacing="0" border="0"
                   style="display:inline-table;margin-left:auto;">
              <tr>
                <td bgcolor="{_VTORA_LIGHT}"
                    style="background-color:{_VTORA_LIGHT};padding:3px 10px;font-size:11px;
                           font-weight:bold;color:{_VTORA_DARK};
                           font-family:Arial,Helvetica,sans-serif;white-space:nowrap;">
                  Втора смена
                </td>
              </tr>
            </table>
          </td>
        </tr>
        {zab_row}"""

    return rows_html


def _build_vtora_smena_section_html(vtora_rows_html, count):
    """Гради целосна секција за втора смена — иста структура како одмори."""
    return f"""
    <tr>
      <td class="mob-pad" style="padding:18px 24px 8px 24px;">
        <p style="margin:0;font-size:10px;font-weight:bold;color:#94a3b8;
                  font-family:Arial,Helvetica,sans-serif;
                  text-transform:uppercase;letter-spacing:1px;">
          Втора смена
        </p>
      </td>
    </tr>
    <tr>
      <td class="mob-pad" style="padding:0 24px 0 24px;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0">
          <tr bgcolor="{_VTORA_COLOR}" style="background-color:{_VTORA_COLOR};">
            <td style="padding:9px 14px;font-size:11px;font-weight:bold;
                       color:#ffffff;font-family:Arial,Helvetica,sans-serif;">
              Вработен / Часови
            </td>
            <td style="padding:9px 14px;font-size:11px;font-weight:bold;
                       color:#ffffff;font-family:Arial,Helvetica,sans-serif;
                       text-align:right;">
              Статус ({count})
            </td>
          </tr>
          {vtora_rows_html}
        </table>
      </td>
    </tr>
    <tr><td style="padding-bottom:8px;"></td></tr>"""


# ─────────────────────────────────────────────────────────────
# ДНЕВЕН ИЗВЕШТАЈ
# ─────────────────────────────────────────────────────────────

def isprati_dnevni_izvestaj_otsustva():
    print(f"[OTSUSTVA DNEVNI] Почнува — {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    try:
        from app import app
        with app.app_context():
            manager_emails = _get_manager_emails()
            if not manager_emails:
                print("[OTSUSTVA DNEVNI] Нема менаџер emails. Прескокнување.")
                return

            conn      = get_db()
            cursor    = conn.cursor()
            today_str = datetime.now().strftime("%Y-%m-%d")
            today_fmt = datetime.now().strftime("%d.%m.%Y")
            mk_days   = {0:"Понеделник",1:"Вторник",2:"Среда",3:"Четврток",
                         4:"Петок",5:"Сабота",6:"Недела"}
            dan_naziv = mk_days[datetime.now().weekday()]

            otsustva = cursor.execute("""
                SELECT v.ime, v.prezime, o.tip, o.casovi, o.plateno, o.zabeleska
                FROM sekojdnevni_otsustva o JOIN vraboteni v ON o.vraboten_id = v.id
                WHERE o.datum = ? ORDER BY v.prezime, v.ime
            """, (today_str,)).fetchall()

            praznici     = {r["datum"] for r in cursor.execute("SELECT datum FROM nerabotni_deni").fetchall()}
            odmori_denes = _get_odmori_for_date(cursor, today_str, praznici)
            conn.close()

            # ── Раздели отсуства и втора смена ──
            otsustva_regular = [o for o in otsustva if o["tip"] != "втора смена"]
            otsustva_vtora   = [o for o in otsustva if o["tip"] == "втора смена"]

            tip_count = defaultdict(int)
            for o in otsustva:
                tip_count[o["tip"]] += 1
            total = len(otsustva)

            # ── rows_html за обични отсуства ──
            rows_html = ""
            if otsustva_regular:
                for idx, o in enumerate(otsustva_regular):
                    tip_label   = TIP_LABELS.get(o["tip"], o["tip"])
                    tip_color   = TIP_COLORS.get(o["tip"], "#6b7280")
                    plateno_txt = "Платено"  if o["plateno"] else "Неплатено"
                    plateno_bg  = "#dcfce7"  if o["plateno"] else "#fef2f2"
                    plateno_fg  = "#166534"  if o["plateno"] else "#991b1b"
                    zabeleska   = o["zabeleska"] or ""
                    row_bg      = "#f9fafb" if idx % 2 == 0 else "#ffffff"
                    pad_b       = "3px" if zabeleska else "11px"

                    zab_row = ""
                    if zabeleska:
                        zab_row = f"""
                        <tr>
                          <td colspan="2" bgcolor="{row_bg}"
                              style="background-color:{row_bg};
                                     padding:3px 14px 11px 14px;
                                     border-bottom:1px solid #e5e7eb;
                                     font-size:12px;color:#64748b;
                                     font-family:Arial,Helvetica,sans-serif;">
                            <strong style="color:#94a3b8;">ЗАБЕЛЕШКА:</strong>
                            {zabeleska}
                          </td>
                        </tr>"""

                    rows_html += f"""
                    <tr>
                      <td bgcolor="{row_bg}"
                          style="background-color:{row_bg};
                                 padding:11px 14px {pad_b} 14px;
                                 vertical-align:top;
                                 border-bottom:{'none' if zabeleska else '1px solid #e5e7eb'};">
                        <p style="margin:0 0 4px 0;font-weight:bold;font-size:14px;
                                   color:#1e293b;font-family:Arial,Helvetica,sans-serif;">
                          {o['prezime']} {o['ime']}
                        </p>
                        <p style="margin:0;font-size:12px;font-weight:bold;
                                   color:{tip_color};font-family:Arial,Helvetica,sans-serif;">
                          {tip_label}
                          <span style="font-weight:normal;color:#64748b;">
                            &nbsp;&middot;&nbsp; {o['casovi']:.0f}h
                          </span>
                        </p>
                      </td>
                      <td bgcolor="{row_bg}"
                          style="background-color:{row_bg};
                                 padding:11px 14px {pad_b} 14px;
                                 vertical-align:top;text-align:right;
                                 border-bottom:{'none' if zabeleska else '1px solid #e5e7eb'};">
                        <table cellpadding="0" cellspacing="0" border="0"
                               style="display:inline-table;margin-left:auto;">
                          <tr>
                            <td bgcolor="{plateno_bg}"
                                style="background-color:{plateno_bg};
                                       padding:3px 10px;font-size:11px;
                                       font-weight:bold;color:{plateno_fg};
                                       font-family:Arial,Helvetica,sans-serif;
                                       white-space:nowrap;">
                              {plateno_txt}
                            </td>
                          </tr>
                        </table>
                      </td>
                    </tr>
                    {zab_row}"""
            else:
                rows_html = """
                <tr>
                  <td colspan="2"
                      style="padding:28px 16px;text-align:center;
                             color:#94a3b8;font-size:14px;font-style:italic;
                             font-family:Arial,Helvetica,sans-serif;">
                    Нема регистрирани отсуства за денес
                  </td>
                </tr>"""

            # ── Втора смена секција ──
            vtora_smena_rows = _build_vtora_smena_rows_html([
                {"ime": o["ime"], "prezime": o["prezime"],
                 "casovi": o["casovi"], "zabeleska": o["zabeleska"] or ""}
                for o in otsustva_vtora
            ])
            vtora_smena_section = _build_vtora_smena_section_html(vtora_smena_rows, len(otsustva_vtora))

            # ── Одмори секција ──
            odmori_rows_html    = _build_odmori_rows_html(odmori_denes)
            odmori_section_html = _build_odmori_section_html(odmori_rows_html, len(odmori_denes))

            summary_pills = ""
            if tip_count:
                summary_pills = '<table cellpadding="0" cellspacing="0" border="0"><tr>'
                for t, c in sorted(tip_count.items(), key=lambda x: -x[1]):
                    col = TIP_COLORS.get(t, "#6b7280")
                    lbl = TIP_LABELS.get(t, t)
                    summary_pills += f"""
                    <td style="padding:0 6px 0 0;vertical-align:top;">
                      <table cellpadding="0" cellspacing="0" border="0"
                             bgcolor="#ffffff"
                             style="border:2px solid {col};background-color:#ffffff;">
                        <tr>
                          <td style="padding:6px 12px;text-align:center;
                                     font-family:Arial,Helvetica,sans-serif;">
                            <p style="margin:0;font-size:20px;font-weight:bold;
                                       color:{col};line-height:1.1;">{c}</p>
                            <p style="margin:2px 0 0 0;font-size:11px;
                                       color:{col};font-weight:bold;">{lbl}</p>
                          </td>
                        </tr>
                      </table>
                    </td>"""
                summary_pills += "</tr></table>"

            html = f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="mk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>Дневен извештај</title>
<style type="text/css">
  body,table,td,p,div,span,a{{margin:0;padding:0;}}
  body{{background-color:#edf2f7;font-family:Arial,Helvetica,sans-serif;
        -webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}}
  table{{border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt;}}
  img{{display:block;border:0;outline:none;text-decoration:none;}}
  @media only screen and (max-width:599px){{
    .outer{{width:100% !important;}}
    .mob-pad{{padding-left:14px !important;padding-right:14px !important;}}
    .title-td{{padding:16px 14px !important;}}
    h1.ttl{{font-size:17px !important;}}
    .big-num{{font-size:30px !important;}}
  }}
</style>
</head>
<body style="margin:0;padding:0;background-color:#edf2f7;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#edf2f7">
  <tr><td align="center" style="padding:24px 8px;">
    <table class="outer" width="580" cellpadding="0" cellspacing="0" border="0"
           bgcolor="#ffffff" style="background-color:#ffffff;">

      <!-- HEADER -->
      <tr>
        <td bgcolor="#1e40af" style="background-color:#1e40af;">
          <table width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td class="title-td" style="padding:22px 24px;vertical-align:middle;">
                <h1 class="ttl" style="margin:0 0 5px 0;font-size:19px;font-weight:bold;
                       color:#ffffff;font-family:Arial,Helvetica,sans-serif;line-height:1.3;">
                  Дневен извештај за отсуства
                </h1>
                <p style="margin:0;font-size:13px;color:#bfdbfe;font-family:Arial,Helvetica,sans-serif;">
                  {dan_naziv}, {today_fmt}
                </p>
              </td>
              <td style="padding:18px 22px 18px 0;vertical-align:middle;text-align:right;width:80px;">
                <img src="cid:fersedo_logo" alt="Fersedo"
                     width="64" height="26" style="width:64px;height:26px;">
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- РЕЗИМЕ -->
      <tr>
        <td class="mob-pad" style="padding:20px 24px 0 24px;">
          <table width="100%" cellpadding="0" cellspacing="0" border="0"
                 bgcolor="#f0f4ff" style="background-color:#f0f4ff;border-left:4px solid #1e40af;">
            <tr><td style="padding:14px 16px;">
              <p style="margin:0 0 10px 0;font-size:10px;font-weight:bold;color:#94a3b8;
                         font-family:Arial,Helvetica,sans-serif;text-transform:uppercase;letter-spacing:1px;">
                Резиме на денот
              </p>
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="width:60px;vertical-align:middle;">
                    <p class="big-num" style="margin:0;font-size:38px;font-weight:bold;
                               color:#1e40af;font-family:Arial,Helvetica,sans-serif;line-height:1;">
                      {total}
                    </p>
                    <p style="margin:3px 0 0 0;font-size:10px;color:#64748b;font-family:Arial,Helvetica,sans-serif;">
                      отсуства
                    </p>
                  </td>
                  <td style="vertical-align:middle;padding-left:10px;padding-right:10px;">
                    {summary_pills if summary_pills else
                     '<p style="margin:0;color:#9ca3af;font-style:italic;font-size:13px;'
                     'font-family:Arial,Helvetica,sans-serif;">Нема отсуства денес</p>'}
                  </td>
                  <td style="vertical-align:middle;text-align:right;white-space:nowrap;">
                    <table cellpadding="0" cellspacing="0" border="0" style="display:inline-table;margin-left:auto;">
                      <tr>
                        <td bgcolor="#d1fae5"
                            style="background-color:#d1fae5;border:2px solid {_ODMOR_COLOR};
                                   padding:6px 12px;text-align:center;font-family:Arial,Helvetica,sans-serif;">
                          <p style="margin:0;font-size:20px;font-weight:bold;
                                     color:{_ODMOR_COLOR};line-height:1.1;">{len(odmori_denes)}</p>
                          <p style="margin:2px 0 0 0;font-size:11px;font-weight:bold;color:{_ODMOR_COLOR};">Одмори</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td></tr>
          </table>
        </td>
      </tr>

      <!-- ДЕТАЛЕН ПРЕГЛЕД — ОТСУСТВА -->
      <tr>
        <td class="mob-pad" style="padding:18px 24px 8px 24px;">
          <p style="margin:0;font-size:10px;font-weight:bold;color:#94a3b8;
                    font-family:Arial,Helvetica,sans-serif;text-transform:uppercase;letter-spacing:1px;">
            Детален преглед
          </p>
        </td>
      </tr>
      <tr>
        <td class="mob-pad" style="padding:0 24px 0 24px;">
          <table width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr bgcolor="#1e40af" style="background-color:#1e40af;">
              <td style="padding:9px 14px;font-size:11px;font-weight:bold;
                         color:#ffffff;font-family:Arial,Helvetica,sans-serif;">
                Вработен / Тип
              </td>
              <td style="padding:9px 14px;font-size:11px;font-weight:bold;
                         color:#ffffff;font-family:Arial,Helvetica,sans-serif;text-align:right;">
                Статус
              </td>
            </tr>
            {rows_html}
          </table>
        </td>
      </tr>
      <tr><td style="padding-bottom:8px;"></td></tr>

      <!-- ВТОРА СМЕНА -->
      {vtora_smena_section}

      <!-- ОДОБРЕНИ ОДМОРИ -->
      {odmori_section_html}

      <tr><td style="padding-bottom:16px;"></td></tr>

      <!-- FOOTER -->
      <tr>
        <td bgcolor="#f8fafc" style="background-color:#f8fafc;
             border-top:1px solid #e5e7eb;padding:12px 24px;">
          <p style="margin:0;font-size:11px;color:#94a3b8;text-align:center;
                    font-family:Arial,Helvetica,sans-serif;">
            Fersedo Production System &bull; Автоматски дневен извештај &bull; {today_fmt}
          </p>
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""

            subject = f"Дневен извештај за отсуства — {today_fmt} ({len(otsustva_regular)} отсуства, {len(otsustva_vtora)} втора смена, {len(odmori_denes)} одмори)"
            _isprati_email_do_menadzeri(manager_emails, subject, html, "[OTSUSTVA DNEVNI]")

    except Exception as e:
        print(f"[OTSUSTVA DNEVNI] Грешка: {e}")
        import traceback; traceback.print_exc()


# ─────────────────────────────────────────────────────────────
# НЕДЕЛЕН ИЗВЕШТАЈ
# ─────────────────────────────────────────────────────────────

def isprati_nedelen_izvestaj_otsustva():
    print(f"[OTSUSTVA NEDELEN] Почнува — {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    try:
        from app import app
        with app.app_context():
            manager_emails = _get_manager_emails()
            if not manager_emails:
                print("[OTSUSTVA NEDELEN] Нема менаџер emails. Прескокнување.")
                return

            conn       = get_db()
            cursor     = conn.cursor()
            today      = datetime.now().date()
            week_start = today - timedelta(days=today.weekday())
            week_end   = week_start + timedelta(days=4)
            ws_str     = week_start.strftime("%Y-%m-%d")
            we_str     = week_end.strftime("%Y-%m-%d")
            ws_fmt     = week_start.strftime("%d.%m.%Y")
            we_fmt     = week_end.strftime("%d.%m.%Y")
            week_num   = today.isocalendar()[1]

            otsustva = cursor.execute("""
                SELECT v.ime, v.prezime, o.datum, o.tip, o.casovi, o.plateno, o.zabeleska
                FROM sekojdnevni_otsustva o JOIN vraboteni v ON o.vraboten_id = v.id
                WHERE o.datum BETWEEN ? AND ?
                ORDER BY o.datum ASC, v.prezime, v.ime
            """, (ws_str, we_str)).fetchall()

            praznici      = {r["datum"] for r in cursor.execute("SELECT datum FROM nerabotni_deni").fetchall()}
            odmori_nedela = _get_odmori_for_range(cursor, ws_str, we_str, praznici)
            conn.close()

            tip_count  = defaultdict(int)
            tip_casovi = defaultdict(float)
            po_den     = defaultdict(list)
            for o in otsustva:
                tip_count[o["tip"]]  += 1
                tip_casovi[o["tip"]] += o["casovi"]
                po_den[o["datum"]].append(o)

            den_names = ["Понеделник","Вторник","Среда","Четврток","Петок"]
            total     = len(otsustva)

            summary_pills = ""
            if tip_count:
                summary_pills = '<table cellpadding="0" cellspacing="0" border="0"><tr>'
                for t, c in sorted(tip_count.items(), key=lambda x: -x[1]):
                    col = TIP_COLORS.get(t, "#6b7280")
                    lbl = TIP_LABELS.get(t, t)
                    summary_pills += f"""
                    <td style="padding:0 6px 0 0;vertical-align:top;">
                      <table cellpadding="0" cellspacing="0" border="0"
                             bgcolor="#ffffff" style="border:2px solid {col};background-color:#ffffff;">
                        <tr>
                          <td style="padding:8px 12px;text-align:center;font-family:Arial,Helvetica,sans-serif;">
                            <p style="margin:0;font-size:22px;font-weight:bold;color:{col};line-height:1.1;">{c}</p>
                            <p style="margin:2px 0 0 0;font-size:11px;font-weight:bold;color:{col};">{lbl}</p>
                            <p style="margin:2px 0 0 0;font-size:11px;color:#94a3b8;">{tip_casovi[t]:.0f}h</p>
                          </td>
                        </tr>
                      </table>
                    </td>"""
                summary_pills += "</tr></table>"

            deni_html = ""
            for i in range(5):
                d       = week_start + timedelta(days=i)
                d_str   = d.strftime("%Y-%m-%d")
                d_fmt   = d.strftime("%d.%m.%Y")
                den_ots = po_den.get(d_str, [])

                # ── Раздели отсуства и втора смена по ден ──
                den_regular = [o for o in den_ots if o["tip"] != "втора смена"]
                den_vtora   = [o for o in den_ots if o["tip"] == "втора смена"]

                if den_ots:
                    # ── Редови за обични отсуства ──
                    rows = ""
                    for o in den_regular:
                        tip_color   = TIP_COLORS.get(o["tip"], "#6b7280")
                        tip_label   = TIP_LABELS.get(o["tip"], o["tip"])
                        zabeleska   = o["zabeleska"] or ""
                        pad_b       = "3px" if zabeleska else "10px"
                        plateno_bg  = "#dcfce7" if o["plateno"] else "#fef2f2"
                        plateno_fg  = "#166534" if o["plateno"] else "#991b1b"
                        plateno_txt = "Платено"  if o["plateno"] else "Неплатено"

                        zab_row = ""
                        if zabeleska:
                            zab_row = f"""
                            <tr>
                              <td colspan="2"
                                  style="padding:3px 14px 10px 14px;border-bottom:1px solid #f1f5f9;
                                         font-size:12px;color:#64748b;font-family:Arial,Helvetica,sans-serif;">
                                <span style="font-weight:bold;color:#94a3b8;font-size:11px;">ЗАБЕЛЕШКА: </span>
                                {zabeleska}
                              </td>
                            </tr>"""

                        rows += f"""
                        <tr>
                          <td style="padding:10px 14px {pad_b} 14px;vertical-align:top;
                                     border-bottom:{'none' if zabeleska else '1px solid #f1f5f9'};">
                            <p style="margin:0 0 4px 0;font-weight:bold;font-size:14px;
                                       color:#1e293b;font-family:Arial,Helvetica,sans-serif;">
                              {o['prezime']} {o['ime']}
                            </p>
                            <p style="margin:0;font-size:12px;font-weight:bold;
                                       color:{tip_color};font-family:Arial,Helvetica,sans-serif;">
                              {tip_label} &nbsp;·&nbsp;
                              <span style="font-weight:normal;color:#64748b;">{o['casovi']:.0f}h</span>
                            </p>
                          </td>
                          <td style="padding:10px 14px {pad_b} 14px;vertical-align:top;text-align:right;
                                     border-bottom:{'none' if zabeleska else '1px solid #f1f5f9'};">
                            <table cellpadding="0" cellspacing="0" border="0"
                                   style="display:inline-table;margin-left:auto;">
                              <tr>
                                <td bgcolor="{plateno_bg}"
                                    style="background-color:{plateno_bg};padding:3px 9px;font-size:11px;
                                           font-weight:bold;color:{plateno_fg};
                                           font-family:Arial,Helvetica,sans-serif;white-space:nowrap;">
                                  {plateno_txt}
                                </td>
                              </tr>
                            </table>
                          </td>
                        </tr>
                        {zab_row}"""

                    # Ако нема обични отсуства
                    if not den_regular:
                        rows = """
                        <tr>
                          <td colspan="2"
                              style="padding:14px 16px;text-align:center;color:#94a3b8;
                                     font-size:13px;font-style:italic;font-family:Arial,Helvetica,sans-serif;">
                            Нема обични отсуства
                          </td>
                        </tr>"""

                    deni_html += f"""
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:6px;">
                      <tr>
                        <td bgcolor="#065f46" style="background-color:#065f46;padding:9px 14px;">
                          <table width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr>
                              <td style="font-weight:bold;font-size:13px;color:#ffffff;
                                         font-family:Arial,Helvetica,sans-serif;">
                                {den_names[i]} &mdash; {d_fmt}
                              </td>
                              <td style="text-align:right;">
                                <table cellpadding="0" cellspacing="0" border="0"
                                       style="display:inline-table;margin-left:auto;">
                                  <tr>
                                    <td style="background-color:rgba(255,255,255,0);
                                               border:1px solid rgba(255,255,255,.5);
                                               padding:2px 8px;font-size:11px;color:#ffffff;
                                               font-weight:bold;font-family:Arial,Helvetica,sans-serif;">
                                      {len(den_regular)} отсуства &bull; {len(den_vtora)} втора смена
                                    </td>
                                  </tr>
                                </table>
                              </td>
                            </tr>
                          </table>
                        </td>
                      </tr>
                      <tr>
                        <td style="border:1px solid #e5e7eb;border-top:none;">
                          <table width="100%" cellpadding="0" cellspacing="0" border="0">
                            <tr bgcolor="#f8fafc" style="background-color:#f8fafc;">
                              <td style="padding:7px 14px;font-size:11px;font-weight:bold;
                                         color:#64748b;font-family:Arial,Helvetica,sans-serif;">
                                Вработен / Тип
                              </td>
                              <td style="padding:7px 14px;font-size:11px;font-weight:bold;
                                         color:#64748b;text-align:right;font-family:Arial,Helvetica,sans-serif;">
                                Статус
                              </td>
                            </tr>
                            {rows}
                          </table>
                        </td>
                      </tr>
                    </table>"""

                    # ── Втора смена за овој ден ──
                    if den_vtora:
                        vtora_rows_den = ""
                        for idx_v, o in enumerate(den_vtora):
                            zabeleska = o["zabeleska"] or ""
                            row_bg_v  = "#f5f3ff" if idx_v % 2 == 0 else "#ffffff"
                            pad_b_v   = "3px" if zabeleska else "10px"

                            zab_row_v = ""
                            if zabeleska:
                                zab_row_v = f"""
                                <tr>
                                  <td colspan="2" bgcolor="{row_bg_v}"
                                      style="background-color:{row_bg_v};
                                             padding:3px 14px 10px 14px;
                                             border-bottom:1px solid {_VTORA_LIGHT};
                                             font-size:12px;color:#64748b;
                                             font-family:Arial,Helvetica,sans-serif;">
                                    <span style="font-weight:bold;color:#94a3b8;font-size:11px;">ЗАБЕЛЕШКА: </span>
                                    {zabeleska}
                                  </td>
                                </tr>"""

                            vtora_rows_den += f"""
                            <tr>
                              <td bgcolor="{row_bg_v}"
                                  style="background-color:{row_bg_v};
                                         padding:10px 14px {pad_b_v} 14px;vertical-align:top;
                                         border-bottom:{'none' if zabeleska else f'1px solid {_VTORA_LIGHT}'};">
                                <p style="margin:0 0 4px 0;font-weight:bold;font-size:14px;
                                           color:#1e293b;font-family:Arial,Helvetica,sans-serif;">
                                  {o['prezime']} {o['ime']}
                                </p>
                                <p style="margin:0;font-size:12px;font-weight:bold;
                                           color:{_VTORA_COLOR};font-family:Arial,Helvetica,sans-serif;">
                                  Втора смена &nbsp;·&nbsp;
                                  <span style="font-weight:normal;color:#64748b;">{o['casovi']:.0f}h</span>
                                </p>
                              </td>
                              <td bgcolor="{row_bg_v}"
                                  style="background-color:{row_bg_v};
                                         padding:10px 14px {pad_b_v} 14px;vertical-align:top;text-align:right;
                                         border-bottom:{'none' if zabeleska else f'1px solid {_VTORA_LIGHT}'};">
                                <table cellpadding="0" cellspacing="0" border="0"
                                       style="display:inline-table;margin-left:auto;">
                                  <tr>
                                    <td bgcolor="{_VTORA_LIGHT}"
                                        style="background-color:{_VTORA_LIGHT};padding:3px 9px;font-size:11px;
                                               font-weight:bold;color:{_VTORA_DARK};
                                               font-family:Arial,Helvetica,sans-serif;white-space:nowrap;">
                                      Втора смена
                                    </td>
                                  </tr>
                                </table>
                              </td>
                            </tr>
                            {zab_row_v}"""

                        deni_html += f"""
                        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:14px;">
                          <tr>
                            <td bgcolor="{_VTORA_COLOR}" style="background-color:{_VTORA_COLOR};padding:7px 14px;">
                              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                <tr>
                                  <td style="font-weight:bold;font-size:12px;color:#ffffff;
                                             font-family:Arial,Helvetica,sans-serif;">
                                    Втора смена &mdash; {d_fmt}
                                  </td>
                                  <td style="text-align:right;">
                                    <table cellpadding="0" cellspacing="0" border="0"
                                           style="display:inline-table;margin-left:auto;">
                                      <tr>
                                        <td style="border:1px solid rgba(255,255,255,.5);
                                                   padding:2px 8px;font-size:11px;color:#ffffff;
                                                   font-weight:bold;font-family:Arial,Helvetica,sans-serif;">
                                          {len(den_vtora)} вработени
                                        </td>
                                      </tr>
                                    </table>
                                  </td>
                                </tr>
                              </table>
                            </td>
                          </tr>
                          <tr>
                            <td style="border:1px solid {_VTORA_LIGHT};border-top:none;">
                              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                                {vtora_rows_den}
                              </table>
                            </td>
                          </tr>
                        </table>"""

                else:
                    deni_html += f"""
                    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="margin-bottom:10px;">
                      <tr>
                        <td bgcolor="#f9fafb" style="background-color:#f9fafb;
                            border:1px solid #e5e7eb;padding:10px 14px;
                            font-size:13px;color:#9ca3af;font-family:Arial,Helvetica,sans-serif;">
                          <strong style="color:#64748b;">{den_names[i]} &mdash; {d_fmt}:</strong>
                          Нема регистрирани отсуства
                        </td>
                      </tr>
                    </table>"""

            # ── Неделна втора смена секција (вкупна) ──
            vtora_nedela_list = [o for o in otsustva if o["tip"] == "втора смена"]
            vtora_nedela_rows = _build_vtora_smena_rows_html([
                {"ime": o["ime"], "prezime": o["prezime"],
                 "casovi": o["casovi"], "zabeleska": o["zabeleska"] or ""}
                for o in vtora_nedela_list
            ])
            vtora_nedela_section = _build_vtora_smena_section_html(vtora_nedela_rows, len(vtora_nedela_list))

            odmori_rows_html    = _build_odmori_rows_html(odmori_nedela)
            odmori_section_html = _build_odmori_section_html(odmori_rows_html, len(odmori_nedela))

            html = f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
  "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml" lang="mk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<title>Неделен извештај</title>
<style type="text/css">
  body,table,td,p,div,span,a{{margin:0;padding:0;}}
  body{{background-color:#edf2f7;font-family:Arial,Helvetica,sans-serif;
        -webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}}
  table{{border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt;}}
  img{{display:block;border:0;outline:none;text-decoration:none;}}
  @media only screen and (max-width:599px){{
    .outer{{width:100% !important;}}
    .mob-pad{{padding-left:14px !important;padding-right:14px !important;}}
    .title-td{{padding:16px 14px !important;}}
    h1.ttl{{font-size:17px !important;}}
    .big-num{{font-size:30px !important;}}
  }}
</style>
</head>
<body style="margin:0;padding:0;background-color:#edf2f7;">
<table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#edf2f7">
  <tr><td align="center" style="padding:24px 8px;">
    <table class="outer" width="580" cellpadding="0" cellspacing="0" border="0"
           bgcolor="#ffffff" style="background-color:#ffffff;">

      <!-- HEADER -->
      <tr>
        <td bgcolor="#065f46" style="background-color:#065f46;">
          <table width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>
              <td class="title-td" style="padding:22px 24px;vertical-align:middle;">
                <h1 class="ttl" style="margin:0 0 5px 0;font-size:19px;font-weight:bold;
                       color:#ffffff;font-family:Arial,Helvetica,sans-serif;line-height:1.3;">
                  Неделен извештај за отсуства
                </h1>
                <p style="margin:0;font-size:13px;color:#a7f3d0;font-family:Arial,Helvetica,sans-serif;">
                  КН {week_num} &bull; {ws_fmt} – {we_fmt}
                </p>
              </td>
              <td style="padding:18px 22px 18px 0;vertical-align:middle;text-align:right;width:80px;">
                <img src="cid:fersedo_logo" alt="Fersedo"
                     width="64" height="26" style="width:64px;height:26px;">
              </td>
            </tr>
          </table>
        </td>
      </tr>

      <!-- РЕЗИМЕ -->
      <tr>
        <td class="mob-pad" style="padding:20px 24px 0 24px;">
          <table width="100%" cellpadding="0" cellspacing="0" border="0"
                 bgcolor="#f0fdf4" style="background-color:#f0fdf4;border-left:4px solid #059669;">
            <tr><td style="padding:14px 16px;">
              <p style="margin:0 0 10px 0;font-size:10px;font-weight:bold;color:#94a3b8;
                         text-transform:uppercase;letter-spacing:1px;font-family:Arial,Helvetica,sans-serif;">
                Резиме за неделата
              </p>
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                <tr>
                  <td style="width:60px;vertical-align:middle;">
                    <p class="big-num" style="margin:0;font-size:38px;font-weight:bold;
                               color:#059669;font-family:Arial,Helvetica,sans-serif;line-height:1;">
                      {total}
                    </p>
                    <p style="margin:3px 0 0 0;font-size:10px;color:#64748b;font-family:Arial,Helvetica,sans-serif;">
                      отсуства
                    </p>
                  </td>
                  <td style="vertical-align:middle;padding-left:10px;padding-right:10px;">
                    {summary_pills if summary_pills else
                     '<p style="margin:0;color:#9ca3af;font-style:italic;font-size:13px;'
                     'font-family:Arial,Helvetica,sans-serif;">Нема отсуства оваа недела</p>'}
                  </td>
                  <td style="vertical-align:middle;text-align:right;white-space:nowrap;">
                    <table cellpadding="0" cellspacing="0" border="0" style="display:inline-table;margin-left:auto;">
                      <tr>
                        <td bgcolor="#d1fae5"
                            style="background-color:#d1fae5;border:2px solid {_ODMOR_COLOR};
                                   padding:6px 12px;text-align:center;font-family:Arial,Helvetica,sans-serif;">
                          <p style="margin:0;font-size:22px;font-weight:bold;
                                     color:{_ODMOR_COLOR};line-height:1.1;">{len(odmori_nedela)}</p>
                          <p style="margin:2px 0 0 0;font-size:11px;font-weight:bold;color:{_ODMOR_COLOR};">Одмори</p>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
              </table>
            </td></tr>
          </table>
        </td>
      </tr>

      <!-- ДЕТАЛЕН ПРЕГЛЕД ПО ДЕН -->
      <tr>
        <td class="mob-pad" style="padding:18px 24px 8px 24px;">
          <p style="margin:0;font-size:10px;font-weight:bold;color:#94a3b8;
                    font-family:Arial,Helvetica,sans-serif;text-transform:uppercase;letter-spacing:1px;">
            Детален преглед по ден
          </p>
        </td>
      </tr>
      <tr>
        <td class="mob-pad" style="padding:0 24px 24px 24px;">
          {deni_html}
        </td>
      </tr>

      <!-- НЕДЕЛНА ВТОРА СМЕНА (сумарно) -->
      {vtora_nedela_section}

      <!-- НЕДЕЛНИ ОДМОРИ (сумарно) -->
      {odmori_section_html}

      <tr><td style="padding-bottom:16px;"></td></tr>

      <!-- FOOTER -->
      <tr>
        <td bgcolor="#f8fafc" style="background-color:#f8fafc;
             border-top:1px solid #e5e7eb;padding:12px 24px;">
          <p style="margin:0;font-size:11px;color:#94a3b8;text-align:center;
                    font-family:Arial,Helvetica,sans-serif;">
            Fersedo Production System &bull; Автоматски неделен извештај &bull;
            Петок {datetime.now().strftime('%d.%m.%Y')}
          </p>
        </td>
      </tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""

            subject = (f"Неделен извештај за отсуства — КН {week_num} "
                       f"({ws_fmt} – {we_fmt}) — {total} отсуства, {len(vtora_nedela_list)} втора смена, {len(odmori_nedela)} одмори")
            _isprati_email_do_menadzeri(manager_emails, subject, html, "[OTSUSTVA NEDELEN]")

    except Exception as e:
        print(f"[OTSUSTVA NEDELEN] Грешка: {e}")
        import traceback; traceback.print_exc()


# ─────────────────────────────────────────────────────────────
# МЕНАЏЕР EMAIL ПОДЕСУВАЊА
# ─────────────────────────────────────────────────────────────

@odmori_bp.route("/manager_emails", methods=["GET", "POST"])
@login_required
@module_required("odmori_manager_emails")
def odmori_manager_emails():
    conn   = get_db()
    cursor = conn.cursor()
    ensure_manager_emails_table(cursor)
    conn.commit()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "add":
            email = request.form.get("email", "").strip()
            ime   = request.form.get("ime", "").strip()
            if email:
                try:
                    cursor.execute(
                        "INSERT INTO otsustva_manager_emails (email, ime, aktiven) VALUES (?,?,1)",
                        (email, ime)
                    )
                    conn.commit()
                    flash(f"Менаџерот {ime} ({email}) е успешно додаден!", "success")
                except sqlite3.IntegrityError:
                    flash("Оваа email адреса веќе постои!", "danger")
                except Exception as e:
                    flash(f"Грешка: {e}", "danger")

        elif action == "toggle":
            mid = request.form.get("manager_id")
            if mid:
                try:
                    cursor.execute(
                        "UPDATE otsustva_manager_emails SET aktiven = CASE WHEN aktiven=1 THEN 0 ELSE 1 END WHERE id=?",
                        (mid,)
                    )
                    conn.commit()
                    flash("Статусот е ажуриран!", "success")
                except Exception as e:
                    flash(f"Грешка: {e}", "danger")

        elif action == "delete":
            mid = request.form.get("manager_id")
            if mid:
                try:
                    cursor.execute("DELETE FROM otsustva_manager_emails WHERE id=?", (mid,))
                    conn.commit()
                    flash("Менаџерот е избришан!", "success")
                except Exception as e:
                    flash(f"Грешка: {e}", "danger")

        elif action == "test_dnevni":
            conn.close()
            isprati_dnevni_izvestaj_otsustva()
            flash("Тест дневен извештај испратен!", "success")
            return redirect(url_for("odmori.odmori_manager_emails"))

        elif action == "test_nedelen":
            conn.close()
            isprati_nedelen_izvestaj_otsustva()
            flash("Тест неделен извештај испратен!", "success")
            return redirect(url_for("odmori.odmori_manager_emails"))

    managers = cursor.execute(
        "SELECT * FROM otsustva_manager_emails ORDER BY ime, email"
    ).fetchall()
    conn.close()
    return render_template("manager_emails.html", managers=managers)


# ─────────────────────────────────────────────────────────────
# ВРАБОТЕНИ
# ─────────────────────────────────────────────────────────────

@odmori_bp.route("/vraboteni", methods=["GET", "POST"])
@login_required
@module_required("odmori_vraboteni")
def odmori_vraboteni():
    conn   = get_db()
    cursor = conn.cursor()
    godina = datetime.now().year

    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            try:
                cursor.execute("""
                    INSERT INTO vraboteni
                        (ime, prezime, maticen_broj, email, pozicija, datum_vrabotuvanje, oddel, prekin_staz)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (
                    request.form.get("ime", "").strip(),
                    request.form.get("prezime", "").strip(),
                    request.form.get("maticen_broj", "").strip(),
                    request.form.get("email", "").strip(),
                    request.form.get("pozicija", "").strip(),
                    request.form.get("datum_vrabotuvanje"),
                    request.form.get("oddel", "").strip(),
                    1 if request.form.get("prekin_staz") else 0,
                ))
                conn.commit()
                flash("Вработениот е успешно додаден!", "success")
            except sqlite3.IntegrityError:
                flash("Матичниот број веќе постои!", "danger")
            except Exception as e:
                flash(f"Грешка: {e}", "danger")

        elif action == "delete":
            vraboten_id = request.form.get("vraboten_id")
            if vraboten_id:
                try:
                    cursor.execute("DELETE FROM vraboteni WHERE id=?", (vraboten_id,))
                    conn.commit()
                    flash("Вработениот е успешно избришан!", "success")
                except Exception as e:
                    flash(f"Грешка: {e}", "danger")

        elif action == "edit":
            vraboten_id = request.form.get("vraboten_id")
            if vraboten_id:
                try:
                    cursor.execute("""
                        UPDATE vraboteni
                        SET ime=?, prezime=?, maticen_broj=?, email=?,
                            pozicija=?, datum_vrabotuvanje=?, oddel=?, prekin_staz=?
                        WHERE id=?
                    """, (
                        request.form.get("ime_edit", "").strip(),
                        request.form.get("prezime_edit", "").strip(),
                        request.form.get("maticen_broj_edit", "").strip(),
                        request.form.get("email_edit", "").strip(),
                        request.form.get("pozicija_edit", "").strip(),
                        request.form.get("datum_vrabotuvanje_edit"),
                        request.form.get("oddel_edit", "").strip(),
                        1 if request.form.get("prekin_staz_edit") else 0,
                        vraboten_id,
                    ))
                    conn.commit()
                    flash("Вработениот е успешно ажуриран!", "success")
                except sqlite3.IntegrityError:
                    flash("Матичниот број веќе постои!", "danger")
                except Exception as e:
                    flash(f"Грешка: {e}", "danger")

        elif action == "edit_saldo":
            vraboten_id = request.form.get("vraboten_id")
            vkupno      = request.form.get("vkupno_dena", 20)
            godina_form = request.form.get("godina_saldo", godina)
            if vraboten_id:
                try:
                    ensure_odmor_salda_table(cursor)
                    cursor.execute("""
                        INSERT INTO odmor_salda (vraboten_id, godina, vkupno_dena)
                        VALUES (?, ?, ?)
                        ON CONFLICT(vraboten_id, godina) DO UPDATE SET vkupno_dena = excluded.vkupno_dena
                    """, (vraboten_id, int(godina_form), int(vkupno)))
                    conn.commit()
                    flash("Салдото е успешно ажурирано!", "success")
                except Exception as e:
                    flash(f"Грешка при ажурирање на салдо: {e}", "danger")

    ensure_odmor_salda_table(cursor)
    vraboteni = cursor.execute("SELECT * FROM vraboteni ORDER BY prezime, ime").fetchall()
    saldo_map = get_saldo_all(cursor, godina)
    conn.commit()
    conn.close()
    return render_template("vraboteni.html", vraboteni=vraboteni, saldo_map=saldo_map, godina=godina)


# ─────────────────────────────────────────────────────────────
# ИМПОРТ / ТЕМПЛАТ
# ─────────────────────────────────────────────────────────────

@odmori_bp.route("/vraboteni/import", methods=["POST"])
@login_required
@module_required("odmori_vraboteni")
def odmori_import_vraboteni():
    file = request.files.get("excel_file")
    if not file or not file.filename.endswith((".xlsx", ".xls")):
        flash("Ве молиме прикачете валидна Excel датотека (.xlsx)!", "danger")
        return redirect(url_for("odmori.odmori_vraboteni"))
    try:
        wb = openpyxl.load_workbook(file, data_only=True)
        ws = wb.active
        expected = ["Ime *","Prezime *","Maticen broj *","Email",
                    "Pozicija","Datum vrabotuvanje (YYYY-MM-DD)","Oddel","Prekin staz (da/ne)"]
        if [str(ws.cell(1,c).value or "").strip() for c in range(1,9)] != expected:
            flash("Грешка: Хедерите не се совпаѓаат. Користете го официјалниот темплат!", "danger")
            return redirect(url_for("odmori.odmori_vraboteni"))
        conn = get_db(); cursor = conn.cursor()
        inserted = skipped = 0; errors = []
        for row_idx in range(2, ws.max_row + 1):
            vals = [ws.cell(row_idx, c).value for c in range(1, 9)]
            if all(v is None or str(v).strip() == "" for v in vals):
                continue
            ime = str(vals[0] or "").strip(); prezime = str(vals[1] or "").strip()
            maticen = str(vals[2] or "").strip()
            if not ime or not prezime or not maticen:
                errors.append(f"Ред {row_idx}: Недостасуваат задолжителни полиња."); skipped += 1; continue
            datum = str(vals[5] or "").strip() if vals[5] else None
            if datum and datum != "None":
                try:
                    if hasattr(vals[5], "strftime"): datum = vals[5].strftime("%Y-%m-%d")
                except Exception: pass
            else: datum = None
            prekin = 1 if str(vals[7] or "").strip().lower() in ("da","да","yes","1","true") else 0
            try:
                cursor.execute("""INSERT INTO vraboteni
                    (ime,prezime,maticen_broj,email,pozicija,datum_vrabotuvanje,oddel,prekin_staz)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (ime, prezime, maticen,
                     str(vals[3] or "").strip() or None,
                     str(vals[4] or "").strip() or None,
                     datum,
                     str(vals[6] or "").strip() or None,
                     prekin))
                inserted += 1
            except Exception as db_err:
                skipped += 1
                errors.append(f"Ред {row_idx} ({ime} {prezime}): {db_err}")
        conn.commit(); conn.close()
        if inserted: flash(f"Успешно увезени {inserted} вработени!", "success")
        if skipped:  flash(f"Прескокнати {skipped} редови поради грешки.", "warning")
        for err in errors[:5]: flash(err, "danger")
    except Exception as e:
        flash(f"Грешка при читање на Excel: {e}", "danger")
    return redirect(url_for("odmori.odmori_vraboteni"))


@odmori_bp.route("/vraboteni/template")
@login_required
@module_required("odmori_vraboteni")
def odmori_download_template():
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Вработени"
    display = ["Ime *","Prezime *","Maticen broj *","Email","Pozicija",
               "Datum vrabotuvanje (YYYY-MM-DD)","Oddel","Prekin staz (da/ne)"]
    hfill = PatternFill("solid", start_color="B91C1C")
    hfont = Font(bold=True, color="FFFFFF", name="Arial", size=11)
    ctr   = Alignment(horizontal="center", vertical="center")
    thin  = Side(style="thin", color="CCCCCC")
    brd   = Border(left=thin, right=thin, top=thin, bottom=thin)
    for ci, d in enumerate(display, 1):
        c = ws.cell(1, ci, d); c.font = hfont; c.fill = hfill; c.alignment = ctr; c.border = brd
    rfill = PatternFill("solid", start_color="FEF2F2")
    for ri, row in enumerate([
        ["Ana","Jovanoska","1234567890123","ana@primer.mk","Менаџер","2020-01-15","HR","ne"],
        ["Marko","Petrov","9876543210123","marko@primer.mk","Програмер","2021-06-01","IT","da"],
    ], 2):
        for ci, val in enumerate(row, 1):
            c = ws.cell(ri, ci, val); c.font = Font(name="Arial", size=10)
            c.fill = rfill; c.border = brd; c.alignment = Alignment(vertical="center")
    for i, w in enumerate([14,16,18,26,20,32,14,22], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 30
    ws2 = wb.create_sheet("Упатство")
    for r, (text, bold) in enumerate([
        ("УПАТСТВО ЗА ПОПОЛНУВАЊЕ",True),("",False),
        ("Полиња означени со * се задолжителни.",False),
        ("Датум: внесете во формат YYYY-MM-DD (пр. 2024-03-15)",False),
        ("Прекин во стаж: внесете 'da' или 'ne'",False),
        ("Матичниот број мора да биде единствен.",False),
        ("Не менувајте ги имињата на колоните!",False),
    ], 1):
        c = ws2.cell(r, 1, text)
        c.font = Font(bold=bold, name="Arial", size=11 if bold else 10,
                      color="B91C1C" if bold else "000000")
    ws2.column_dimensions["A"].width = 60
    output = io.BytesIO(); wb.save(output); output.seek(0)
    return send_file(output,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name="template_vraboteni.xlsx")


# ─────────────────────────────────────────────────────────────
# КАЛЕНДАР
# ─────────────────────────────────────────────────────────────

@odmori_bp.route("/kalendar", methods=["GET", "POST"])
@login_required
@module_required("odmori_kalendar")
def odmori_kalendar():
    conn   = get_db(); cursor = conn.cursor()
    vraboteni = cursor.execute("SELECT id, ime, prezime FROM vraboteni ORDER BY prezime, ime").fetchall()
    selected_vraboten_id = request.args.get("vraboten_id", "all")
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add_neraboten":
            datum = request.form.get("datum"); ime = request.form.get("ime","").strip()
            if datum and ime:
                try:
                    cursor.execute("INSERT INTO nerabotni_deni (datum, ime) VALUES (?,?)", (datum, ime))
                    conn.commit(); flash("Неработниот ден е успешно додаден!", "success")
                except sqlite3.IntegrityError: flash("Овој датум веќе постои!", "danger")
                except Exception as e: flash(f"Грешка: {e}", "danger")
        elif action == "delete_neraboten":
            nid = request.form.get("neraboten_id")
            if nid:
                try:
                    cursor.execute("DELETE FROM nerabotni_deni WHERE id=?", (nid,))
                    conn.commit(); flash("Неработниот ден е успешно избришан!", "success")
                except Exception as e: flash(f"Грешка: {e}", "danger")
        conn.close()
        return redirect(url_for("odmori.odmori_kalendar", vraboten_id=selected_vraboten_id))

    query = """SELECT b.datum_od,b.datum_do,b.zabeleska,v.ime,v.prezime
               FROM baranja_odmor b JOIN vraboteni v ON b.vraboten_id=v.id
               WHERE b.status='approved'"""
    params = []
    if selected_vraboten_id != "all":
        query += " AND b.vraboten_id=?"; params.append(selected_vraboten_id)
    odmor_baranja = cursor.execute(query, params).fetchall()
    nerabotni     = cursor.execute("SELECT id, datum, ime FROM nerabotni_deni ORDER BY datum").fetchall()
    events = []
    for b in odmor_baranja:
        try:
            start = datetime.strptime(b["datum_od"], "%Y-%m-%d").date()
            end   = datetime.strptime(b["datum_do"], "%Y-%m-%d").date() + timedelta(days=1)
        except Exception: continue
        events.append({"title":f"{b['ime']} {b['prezime']}","start":b["datum_od"],
            "end":end.strftime("%Y-%m-%d"),"backgroundColor":"#28a745","borderColor":"#1e7e34",
            "textColor":"white","extendedProps":{"ime":b["ime"],"prezime":b["prezime"],
            "zabeleska":b["zabeleska"] or "Нема забелешка",
            "period":f"Од {start.strftime('%d-%m-%Y')} до {(end-timedelta(days=1)).strftime('%d-%m-%Y')}"}})
    for n in nerabotni:
        events.append({"title":n["ime"],"start":n["datum"],"allDay":True,
            "backgroundColor":"#dc3545","borderColor":"#c82333","textColor":"white",
            "extendedProps":{"type":"neraboten","neraboten_id":n["id"],"ime":n["ime"]}})
    current_year = datetime.now().year
    mk_months = {"January":"Јануари","February":"Февруари","March":"Март","April":"Април",
        "May":"Мај","June":"Јуни","July":"Јули","August":"Август",
        "September":"Септември","October":"Октомври","November":"Ноември","December":"Декември"}
    nerabotni_by_month = defaultdict(list)
    for n in nerabotni:
        try:
            dt = datetime.strptime(n["datum"], "%Y-%m-%d")
            if dt.year == current_year:
                nerabotni_by_month[mk_months[dt.strftime("%B")]].append(
                    {"id":n["id"],"datum":dt.strftime("%d.%m.%Y"),"ime":n["ime"]})
        except Exception: continue
    month_order = ["Јануари","Февруари","Март","Април","Мај","Јуни",
                   "Јули","Август","Септември","Октомври","Ноември","Декември"]
    nerabotni_grouped = [{"month":m,"count":len(nerabotni_by_month.get(m,[])),
        "days":sorted(nerabotni_by_month.get(m,[]),key=lambda x:x["datum"])} for m in month_order]
    conn.close()
    return render_template("kalendar.html", events_json=json.dumps(events), vraboteni=vraboteni,
        selected_vraboten_id=selected_vraboten_id, nerabotni_grouped=nerabotni_grouped,
        current_year=current_year)


# ─────────────────────────────────────────────────────────────
# ПРЕГЛЕД НА ОДМОРИ
# ─────────────────────────────────────────────────────────────

@odmori_bp.route("/pregled_odmori", methods=["GET", "POST"])
@login_required
@module_required("odmori_pregled_odmori")
def odmori_pregled_odmori():
    conn = get_db(); cursor = conn.cursor()
    godina = datetime.now().year
    if request.method == "POST":
        action = request.form.get("action"); baranje_id = request.form.get("baranje_id")
        if baranje_id and action in ("approve", "reject"):
            new_status = "approved" if action == "approve" else "rejected"
            try:
                cursor.execute("UPDATE baranja_odmor SET status=? WHERE id=?", (new_status, baranje_id))
                conn.commit(); flash(f"Барањето е {new_status.upper()}!", "success")
                if new_status == "approved":
                    try:
                        from routes.main import _isprati_odobruvanje_email
                        b = cursor.execute("""SELECT b.datum_od,b.datum_do,b.zabeleska,b.vraboten_id,
                            v.ime,v.prezime,v.email FROM baranja_odmor b
                            JOIN vraboteni v ON b.vraboten_id=v.id WHERE b.id=?""", (baranje_id,)).fetchone()
                        if b and b["email"]:
                            praznici_set = {r["datum"] for r in cursor.execute("SELECT datum FROM nerabotni_deni").fetchall()}
                            working_days = 0
                            try:
                                s = datetime.strptime(b["datum_od"],"%Y-%m-%d").date()
                                e = datetime.strptime(b["datum_do"],"%Y-%m-%d").date()
                                c = s
                                while c <= e:
                                    if c.weekday() < 5 and c.strftime("%Y-%m-%d") not in praznici_set: working_days += 1
                                    c += timedelta(days=1)
                                godina_b = s.year
                            except Exception: godina_b = datetime.now().year
                            saldo_r = cursor.execute("SELECT vkupno_dena FROM odmor_salda WHERE vraboten_id=? AND godina=?",
                                (b["vraboten_id"],godina_b)).fetchone()
                            vkupno = saldo_r["vkupno_dena"] if saldo_r else 20
                            saldo_map_now = get_saldo_all(cursor, godina_b)
                            preostanati = saldo_map_now.get(b["vraboten_id"],{}).get("preostanati",0)
                            _isprati_odobruvanje_email(vraboten_email=b["email"].strip(),
                                ime_prezime=f"{b['ime']} {b['prezime']}",datum_od=b["datum_od"],
                                datum_do=b["datum_do"],working_days=working_days,zabeleska=b["zabeleska"] or "",
                                odobren_od="Менаџмент",vkupno_dena=vkupno,preostanati=preostanati,godina=godina_b)
                    except Exception as mail_err: print(f"[EMAIL ODOBR] Грешка: {mail_err}")
            except Exception as e: flash(f"Грешка: {e}", "danger")
        elif action == "edit" and baranje_id:
            datum_od = request.form.get("datum_od"); datum_do = request.form.get("datum_do")
            zabeleska = request.form.get("zabeleska","").strip()
            if datum_od and datum_do:
                try:
                    od = datetime.strptime(datum_od,"%Y-%m-%d").date()
                    do = datetime.strptime(datum_do,"%Y-%m-%d").date()
                    if od > do: flash('Датумот "Од" не може да биде после "До"!', "danger")
                    else:
                        cursor.execute("UPDATE baranja_odmor SET datum_od=?,datum_do=?,zabeleska=? WHERE id=?",
                            (datum_od,datum_do,zabeleska,baranje_id))
                        conn.commit(); flash("Барањето е успешно изменето!", "success")
                except Exception as e: flash(f"Грешка: {e}", "danger")
        elif action == "cancel" and baranje_id:
            try:
                cursor.execute("UPDATE baranja_odmor SET status='otkazano' WHERE id=?", (baranje_id,))
                conn.commit(); flash("Барањето е успешно откажано!", "success")
            except Exception as e: flash(f"Грешка: {e}", "danger")

    praznici = {r["datum"] for r in cursor.execute("SELECT datum FROM nerabotni_deni").fetchall()}
    baranja_raw = cursor.execute("""SELECT b.id,b.vraboten_id,b.datum_od,b.datum_do,b.status,b.zabeleska,
        b.podneseno_od,b.podneseno_na,v.ime,v.prezime FROM baranja_odmor b
        JOIN vraboteni v ON b.vraboten_id=v.id ORDER BY b.podneseno_na DESC""").fetchall()
    baranja = []
    for b in baranja_raw:
        try: start = datetime.strptime(b["datum_od"],"%Y-%m-%d").date(); end = datetime.strptime(b["datum_do"],"%Y-%m-%d").date()
        except Exception: start = end = None
        total_days = working_days = 0
        if start and end and start <= end:
            total_days = (end - start).days + 1
            cur = start
            while cur <= end:
                if cur.weekday() < 5 and cur.strftime("%Y-%m-%d") not in praznici: working_days += 1
                cur += timedelta(days=1)
        baranja.append({"id":b["id"],"vraboten_id":b["vraboten_id"],"ime":b["ime"],"prezime":b["prezime"],
            "datum_od_formatted":start.strftime("%d-%m-%Y") if start else "—",
            "datum_do_formatted":end.strftime("%d-%m-%Y") if end else "—",
            "datum_od_year":start.year if start else godina,"status":b["status"],
            "zabeleska":b["zabeleska"] or "—","podneseno_od":b["podneseno_od"] or "—",
            "podneseno_na":b["podneseno_na"] or "—","total_days":total_days,"working_days":working_days})
    saldo_map = get_saldo_all(cursor, godina)
    conn.commit(); conn.close()
    return render_template("pregled_odmori.html", baranja=baranja, saldo_map=saldo_map, godina=godina)


# ─────────────────────────────────────────────────────────────
# СЕКОЈДНЕВНИ ОТСУСТВА
# ─────────────────────────────────────────────────────────────

@odmori_bp.route("/sekojdnevni_otsustva", methods=["GET", "POST"])
@login_required
@module_required("odmori_sekojdnevni_otsustva")
def odmori_sekojdnevni_otsustva():
    conn = get_db(); cursor = conn.cursor()
    vraboteni = cursor.execute("SELECT id, ime, prezime FROM vraboteni ORDER BY prezime, ime").fetchall()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            vraboten_id = request.form.get("vraboten_id"); datum = request.form.get("datum")
            tip = request.form.get("tip"); casovi = float(request.form.get("casovi", 8.0))
            plateno = 1 if request.form.get("plateno") else 0
            zabeleska = request.form.get("zabeleska","").strip()
            if vraboten_id and datum and tip:
                try:
                    cursor.execute("""INSERT INTO sekojdnevni_otsustva
                        (vraboten_id,datum,tip,casovi,plateno,zabeleska) VALUES (?,?,?,?,?,?)""",
                        (vraboten_id,datum,tip,casovi,plateno,zabeleska))
                    conn.commit(); flash("Отсуството е успешно додадено!", "success")
                except Exception as e: flash(f"Грешка: {e}", "danger")
        elif action == "delete":
            oid = request.form.get("otsustvo_id")
            if oid:
                try:
                    cursor.execute("DELETE FROM sekojdnevni_otsustva WHERE id=?", (oid,))
                    conn.commit(); flash("Отсуството е успешно избришано!", "success")
                except Exception as e: flash(f"Грешка: {e}", "danger")
        elif action == "edit":
            oid = request.form.get("otsustvo_id")
            if oid:
                try:
                    cursor.execute("""UPDATE sekojdnevni_otsustva
                        SET vraboten_id=?,datum=?,tip=?,casovi=?,plateno=?,zabeleska=? WHERE id=?""",
                        (request.form.get("vraboten_id_edit"),request.form.get("datum_edit"),
                         request.form.get("tip_edit"),float(request.form.get("casovi_edit",8.0)),
                         1 if request.form.get("plateno_edit") else 0,
                         request.form.get("zabeleska_edit","").strip(),oid))
                    conn.commit(); flash("Отсуството е успешно ажурирано!", "success")
                except Exception as e: flash(f"Грешка: {e}", "danger")

    otsustva = cursor.execute("""SELECT o.id,o.datum,o.tip,o.casovi,o.plateno,o.zabeleska,
        v.ime,v.prezime,o.vraboten_id FROM sekojdnevni_otsustva o
        JOIN vraboteni v ON o.vraboten_id=v.id ORDER BY o.datum DESC""").fetchall()
    today = datetime.now().date(); today_str = today.strftime("%Y-%m-%d")
    week_start = today - timedelta(days=today.weekday()); week_end = week_start + timedelta(days=6)
    ws_str = week_start.strftime("%Y-%m-%d"); we_str = week_end.strftime("%Y-%m-%d")
    izvestaj = cursor.execute("""SELECT o.id,v.ime,v.prezime,o.datum,o.tip,o.zabeleska,o.casovi
        FROM sekojdnevni_otsustva o JOIN vraboteni v ON o.vraboten_id=v.id
        WHERE o.datum=? ORDER BY v.prezime,v.ime,o.tip""",(today_str,)).fetchall()
    nedelen_raw = cursor.execute("""SELECT v.ime,v.prezime,o.datum,o.tip,o.casovi,o.plateno,
        o.zabeleska,o.vraboten_id FROM sekojdnevni_otsustva o
        JOIN vraboteni v ON o.vraboten_id=v.id
        WHERE o.datum BETWEEN ? AND ? ORDER BY o.datum ASC,v.prezime,v.ime""",(ws_str,we_str)).fetchall()
    mk_days = {0:"Пон",1:"Вто",2:"Сре",3:"Чет",4:"Пет",5:"Саб",6:"Нед"}
    nedelen_po_vraboten = defaultdict(lambda:{"ime":"","prezime":"","dena":[],"vkupno_casovi":0.0})
    for r in nedelen_raw:
        vid = r["vraboten_id"]
        nedelen_po_vraboten[vid]["ime"] = r["ime"]; nedelen_po_vraboten[vid]["prezime"] = r["prezime"]
        nedelen_po_vraboten[vid]["vkupno_casovi"] += r["casovi"]
        try: d = datetime.strptime(r["datum"],"%Y-%m-%d").date(); day_label = f"{mk_days[d.weekday()]} {d.strftime('%d.%m')}"
        except Exception: day_label = r["datum"]
        nedelen_po_vraboten[vid]["dena"].append({"dan":day_label,"tip":r["tip"],"casovi":r["casovi"],"plateno":r["plateno"]})
    tip_summary = defaultdict(lambda:{"count":0,"casovi":0.0})
    for r in nedelen_raw: tip_summary[r["tip"]]["count"] += 1; tip_summary[r["tip"]]["casovi"] += r["casovi"]
    week_days_list = [{"label":f"{mk_days[i]} {(week_start+timedelta(days=i)).strftime('%d.%m')}",
        "datum":(week_start+timedelta(days=i)).strftime("%Y-%m-%d"),
        "is_today":(week_start+timedelta(days=i))==today,"is_weekend":i>=5} for i in range(7)]

    praznici      = {r["datum"] for r in cursor.execute("SELECT datum FROM nerabotni_deni").fetchall()}
    odmori_denes  = _get_odmori_for_date(cursor, today_str, praznici)
    odmori_nedela = _get_odmori_for_range(cursor, ws_str, we_str, praznici)

    conn.close()
    return render_template("sekojdnevni_otsustva.html", otsustva=otsustva, vraboteni=vraboteni,
        izvestaj=izvestaj, nedelen_raw=list(nedelen_raw), nedelen_po_vraboten=dict(nedelen_po_vraboten),
        tip_summary=dict(tip_summary), week_days_list=week_days_list,
        week_start=week_start.strftime("%d.%m.%Y"), week_end=week_end.strftime("%d.%m.%Y"),
        today=today.strftime("%d.%m.%Y"), today_str=today_str,
        odmori_denes=odmori_denes, odmori_nedela=odmori_nedela)
    
@odmori_bp.route("/nedeli")
@login_required
@module_required("odmori_sekojdnevni_otsustva")
def odmori_nedeli():
    import datetime as dt
    from collections import defaultdict

    conn    = get_db()
    cursor  = conn.cursor()

    otsustva = cursor.execute("""
        SELECT o.id, o.datum, o.tip, o.casovi, o.plateno, o.zabeleska,
               v.ime, v.prezime, o.vraboten_id
        FROM sekojdnevni_otsustva o
        JOIN vraboteni v ON o.vraboten_id = v.id
        ORDER BY o.datum DESC
    """).fetchall()

    praznici = {r["datum"] for r in cursor.execute("SELECT datum FROM nerabotni_deni").fetchall()}

    odmori_all = cursor.execute("""
        SELECT v.ime, v.prezime, b.datum_od, b.datum_do, b.zabeleska
        FROM baranja_odmor b
        JOIN vraboteni v ON b.vraboten_id = v.id
        WHERE b.status = 'approved'
        ORDER BY b.datum_od DESC
    """).fetchall()

    conn.close()

    nedeli = {}

    for o in otsustva:
        try:
            d          = dt.datetime.strptime(o["datum"], "%Y-%m-%d").date()
            week_start = d - dt.timedelta(days=d.weekday())
            week_end   = week_start + dt.timedelta(days=4)
            kn         = d.isocalendar()[1]
            godina     = d.year
            key        = f"{godina}-{kn:02d}"

            if key not in nedeli:
                nedeli[key] = {
                    "kn":       kn,
                    "godina":   godina,
                    "datum_od": week_start.strftime("%d.%m.%Y"),
                    "datum_do": week_end.strftime("%d.%m.%Y"),
                    "otsustva": [],
                    "odmori":   [],
                }
            nedeli[key]["otsustva"].append(dict(o))
        except Exception as e:
            print(f"[NEDELI] грешка отсуство: {e}")
            continue

    for o in odmori_all:
        try:
            start      = dt.datetime.strptime(o["datum_od"], "%Y-%m-%d").date()
            end        = dt.datetime.strptime(o["datum_do"], "%Y-%m-%d").date()
            cur        = start - dt.timedelta(days=start.weekday())

            while cur <= end:
                kn     = cur.isocalendar()[1]
                godina = cur.year
                key    = f"{godina}-{kn:02d}"
                week_end_d = cur + dt.timedelta(days=4)

                if key not in nedeli:
                    nedeli[key] = {
                        "kn":       kn,
                        "godina":   godina,
                        "datum_od": cur.strftime("%d.%m.%Y"),
                        "datum_do": week_end_d.strftime("%d.%m.%Y"),
                        "otsustva": [],
                        "odmori":   [],
                    }

                wd = calc_working_days(o["datum_od"], o["datum_do"], praznici)
                entry = {
                    "ime":          o["ime"],
                    "prezime":      o["prezime"],
                    "datum_od":     o["datum_od"],
                    "datum_do":     o["datum_do"],
                    "zabeleska":    o["zabeleska"] or "",
                    "working_days": wd,
                }
                if entry not in nedeli[key]["odmori"]:
                    nedeli[key]["odmori"].append(entry)

                cur += dt.timedelta(days=7)
        except Exception as e:
            print(f"[NEDELI] грешка одмор: {e}")
            continue

    nedeli_sorted = sorted(nedeli.items(), key=lambda x: x[0], reverse=True)
    selected_kn   = request.args.get("kn", None)
    selected_ned  = nedeli.get(selected_kn) if selected_kn else None

    return render_template(
        "odmori_nedeli.html",
        nedeli=nedeli_sorted,
        selected_kn=selected_kn,
        selected_ned=selected_ned,
        TIP_COLORS=TIP_COLORS,
        TIP_LABELS=TIP_LABELS,
    )