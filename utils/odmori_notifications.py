from collections import defaultdict
from datetime import datetime, timedelta

from flask import current_app

from utils.db import get_db
from utils.odmori_helpers import (
    _get_manager_emails,
    _get_odmori_for_date,
    _get_odmori_for_range,
    _isprati_email_do_menadzeri,
    log_email_event,
)

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
        return datetime.strptime(d_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    except Exception:
        return d_str




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
    print(f"[OTSUSTVA DNEVNI] Почнува — {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    try:
        app = current_app._get_current_object()
        with app.app_context():
            manager_emails = _get_manager_emails()
            if not manager_emails:
                print("[OTSUSTVA DNEVNI] Нема менаџер emails. Прескокнување.")
                result = {"success": False, "message": "\u041d\u0435\u043c\u0430 \u0430\u043a\u0442\u0438\u0432\u043d\u0438 \u043c\u0435\u043d\u0430\u045f\u0435\u0440 email \u0430\u0434\u0440\u0435\u0441\u0438."}
                log_email_event("dneven", False, "Дневен извештај за отсуства", [], result["message"])
                return result

            conn      = get_db()
            cursor    = conn.cursor()
            today_str = datetime.now().strftime("%Y-%m-%d")
            today_fmt = datetime.now().strftime("%d-%m-%Y")
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
            result = _isprati_email_do_menadzeri(manager_emails, subject, html, "[OTSUSTVA DNEVNI]")
            log_email_event("dneven", result.get("success"), subject, manager_emails, result.get("message", ""))
            return result

    except Exception as e:
        print(f"[OTSUSTVA DNEVNI] Грешка: {e}")
        import traceback; traceback.print_exc()
        log_email_event("dneven", False, "Дневен извештај за отсуства", [], str(e))
        return {"success": False, "message": str(e)}


# ─────────────────────────────────────────────────────────────
# НЕДЕЛЕН ИЗВЕШТАЈ
# ─────────────────────────────────────────────────────────────

def isprati_nedelen_izvestaj_otsustva():
    print(f"[OTSUSTVA NEDELEN] Почнува — {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    try:
        app = current_app._get_current_object()
        with app.app_context():
            manager_emails = _get_manager_emails()
            if not manager_emails:
                print("[OTSUSTVA NEDELEN] Нема менаџер emails. Прескокнување.")
                result = {"success": False, "message": "\u041d\u0435\u043c\u0430 \u0430\u043a\u0442\u0438\u0432\u043d\u0438 \u043c\u0435\u043d\u0430\u045f\u0435\u0440 email \u0430\u0434\u0440\u0435\u0441\u0438."}
                log_email_event("nedelen", False, "Неделен извештај за отсуства", [], result["message"])
                return result

            conn       = get_db()
            cursor     = conn.cursor()
            today      = datetime.now().date()
            week_start = today - timedelta(days=today.weekday())
            week_end   = week_start + timedelta(days=4)
            ws_str     = week_start.strftime("%Y-%m-%d")
            we_str     = week_end.strftime("%Y-%m-%d")
            ws_fmt     = week_start.strftime("%d-%m-%Y")
            we_fmt     = week_end.strftime("%d-%m-%Y")
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
                d_fmt   = d.strftime("%d-%m-%Y")
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
            Петок {datetime.now().strftime('%d-%m-%Y')}
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
            result = _isprati_email_do_menadzeri(manager_emails, subject, html, "[OTSUSTVA NEDELEN]")
            log_email_event("nedelen", result.get("success"), subject, manager_emails, result.get("message", ""))
            return result
    except Exception as e:
        print(f"[OTSUSTVA NEDELEN] Р“СЂРµС€РєР°: {e}")
        import traceback; traceback.print_exc()
        log_email_event("nedelen", False, "Неделен извештај за отсуства", [], str(e))
        return {"success": False, "message": str(e)}
