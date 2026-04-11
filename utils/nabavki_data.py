from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from utils.helpers import _format_cet
from utils.nabavki_images import ensure_archive_comments_table, ensure_comment_slika_column


STATUS_CLASS_MAP = {
    "Videno": "bg-info",
    "Naracano": "bg-warning text-dark",
    "Dostaveno": "bg-primary",
    "Zavrseno": "bg-success",
    "Prevzemeno": "bg-success",
    "Otkazano": "bg-danger",
    "креирано": "bg-secondary",
}

KNOWN_STATUS_VALUES = set(STATUS_CLASS_MAP)


def normalize_request_status(status):
    value = (status or "").strip()
    if not value:
        return "креирано"
    if value in KNOWN_STATUS_VALUES:
        return value
    # Legacy/garbled values should still render as the initial request state.
    return "креирано"


def _parse_request_date(value):
    text = (value or "").strip() if isinstance(value, str) else value
    if not text:
        return None
    if isinstance(text, datetime):
        return text.date()
    if isinstance(text, date):
        return text

    normalized = str(text).strip()
    try:
        return datetime.fromisoformat(normalized.replace("Z", "")).date()
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(normalized, fmt).date()
        except ValueError:
            continue
    return None


def _day_unit(value):
    return "ден" if abs(int(value)) == 1 else "дена"


def _build_deadline_meta(created_at, due_date):
    created_date = _parse_request_date(created_at)
    due_date_parsed = _parse_request_date(due_date)
    today = date.today()

    meta = {
        "deadline_due_display": due_date or "—",
        "deadline_total_days": None,
        "deadline_total_label": "—",
        "deadline_state_label": "Преостанато",
        "deadline_state_value": "—",
        "deadline_state_class": "text-muted",
        "deadline_is_overdue": False,
    }

    if due_date_parsed:
        meta["deadline_due_display"] = due_date_parsed.strftime("%d-%m-%Y")

    if not created_date or not due_date_parsed:
        return meta

    total_days = max((due_date_parsed - created_date).days, 0)
    remaining_days = (due_date_parsed - today).days

    meta["deadline_total_days"] = total_days
    meta["deadline_total_label"] = f"{total_days} {_day_unit(total_days)}"

    if remaining_days >= 0:
        meta["deadline_state_label"] = "Преостанато"
        meta["deadline_state_value"] = f"{remaining_days} {_day_unit(remaining_days)}"
        meta["deadline_state_class"] = "text-success" if remaining_days > 1 else "text-warning"
    else:
        overdue_days = abs(remaining_days)
        meta["deadline_state_label"] = "Надминато"
        meta["deadline_state_value"] = f"{overdue_days} {_day_unit(overdue_days)}"
        meta["deadline_state_class"] = "text-danger"
        meta["deadline_is_overdue"] = True

    return meta


def fetch_requests_with_comments(cursor, filter_type, current_user, is_nabavki_user):
    if filter_type == "my_taken" and is_nabavki_user:
        rows = cursor.execute(
            """
            SELECT *
            FROM nabavki_requests WHERE prevzemeno_od=? ORDER BY nalog_broj DESC
            """,
            (current_user,),
        ).fetchall()
        page_title = "Мои превземени барања"
    elif is_nabavki_user:
        rows = cursor.execute(
            """
            SELECT *
            FROM nabavki_requests ORDER BY nalog_broj DESC
            """
        ).fetchall()
        page_title = "Сите барања за набавки"
    else:
        rows = cursor.execute(
            """
            SELECT *
            FROM nabavki_requests WHERE username=? ORDER BY nalog_broj DESC
            """,
            (current_user,),
        ).fetchall()
        page_title = "Мои барања"

    requests_list = []
    for row in rows:
        item = dict(row)
        item["status_norm"] = normalize_request_status(item.get("status"))
        item["status_display"] = item["status_norm"].capitalize()
        item["status_class"] = STATUS_CLASS_MAP.get(item["status_norm"], "bg-secondary")
        item["datum_kreiranje_formatted"] = (
            _format_cet(item["datum_kreiranje"]) if item.get("datum_kreiranje") else "-"
        )
        item.update(_build_deadline_meta(item.get("datum_kreiranje"), item.get("datum_itnost")))
        item["days_remaining"] = item["deadline_state_value"]
        item["comments"] = fetch_comments(cursor, item["id"])
        requests_list.append(item)

    return requests_list, page_title


def get_user_lists(cursor):
    users = cursor.execute("SELECT username FROM users ORDER BY username").fetchall()
    nabavki_users = cursor.execute(
        """
        SELECT username FROM users
        WHERE user_group = 'Nabavki' OR is_admin = 1
        ORDER BY username
        """
    ).fetchall()
    return users, nabavki_users


def fetch_comments(cursor, req_id):
    ensure_comment_slika_column(cursor)
    return cursor.execute(
        """
        SELECT user, comment, timestamp, slika FROM nabavki_comments
        WHERE req_id=? ORDER BY timestamp ASC
        """,
        (req_id,),
    ).fetchall()


def get_archived_requests(cursor):
    ensure_archive_comments_table(cursor)
    archived_raw = cursor.execute(
        "SELECT * FROM nabavki_archive ORDER BY arhivirano_na DESC"
    ).fetchall()

    archived = []
    for row in archived_raw:
        item = dict(row)
        item["comments"] = cursor.execute(
            """
            SELECT user, comment, slika, timestamp
            FROM nabavki_archive_comments
            WHERE archive_req_id = ?
            ORDER BY timestamp ASC
            """,
            (item["id"],),
        ).fetchall()
        archived.append(item)

    return archived


def fetch_export_rows(cursor, status_filter=None, datum_od=None, datum_do=None, user_filter=None):
    query = "SELECT * FROM nabavki_requests WHERE 1=1"
    params = []

    if status_filter:
        query += " AND status=?"
        params.append(status_filter)
    if datum_od:
        query += " AND datum_kreiranje>=?"
        params.append(datum_od)
    if datum_do:
        query += " AND datum_kreiranje<=?"
        params.append(datum_do + " 23:59:59")
    if user_filter:
        query += " AND username=?"
        params.append(user_filter)

    query += " ORDER BY datum_kreiranje DESC"
    return cursor.execute(query, params).fetchall()


def build_excel_output(rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Набавки"
    ws.append(
        [
            "ID",
            "Корисник",
            "Наслов",
            "Количина",
            "Опис",
            "Слика",
            "Датум",
            "Статус",
            "Датум нарачка",
            "Датум прием",
            "Admin нарачал",
        ]
    )
    for row in rows:
        ws.append(
            [
                row["id"],
                row["username"],
                row["naslov"],
                row["kolicina"],
                row["opis"] or "-",
                row["slika"] or "-",
                row["datum_kreiranje"],
                row["status"],
                row["datum_naracka"] or "-",
                row["datum_priem"] or "-",
                row["admin_naracal"] or "-",
            ]
        )

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return output


def build_pdf_output(rows):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    data = [["ID", "Корисник", "Наслов", "Кол.", "Статус", "Датум"]]

    for row in rows:
        data.append(
            [
                row["id"],
                row["username"],
                row["naslov"],
                row["kolicina"],
                row["status"],
                row["datum_kreiranje"],
            ]
        )

    table = Table(data)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )
    doc.build([Paragraph("Листа на барања за набавки", styles["Heading1"]), table])
    buffer.seek(0)
    return buffer


def build_api_tbody_html(requests_list, can_manage):
    tbody_html = ""

    for req in requests_list:
        slika_cell = (
            f'<a href="/static/nabavki/{req["slika"]}" target="_blank">'
            f'<img src="/static/nabavki/{req["slika"]}" class="rounded shadow" style="max-width:90px;height:auto;"></a>'
            if req.get("slika")
            else '<span class="text-muted">Нема</span>'
        )
        status_norm = req.get("status_norm") or normalize_request_status(req.get("status"))
        status_cls = STATUS_CLASS_MAP.get(status_norm, "bg-secondary")
        status_display = req.get("status_display") or status_norm.capitalize()
        prevzemeno = (
            f'<strong class="text-success">{req["prevzemeno_od"]}</strong>'
            + (
                f'<br><small class="text-muted">{req["datum_prevzemanje"]}</small>'
                if req.get("datum_prevzemanje")
                else ""
            )
            if req.get("prevzemeno_od")
            else '<span class="text-muted">—</span>'
        )

        action_cell = '<span class="text-muted">—</span>'
        if can_manage:
            options = "".join(
                f'<li><a class="dropdown-item status-change" href="#" data-status="{status}" data-id="{req["id"]}">{status}</a></li>'
                for status in ["Videno", "Naracano", "Dostaveno", "Zavrseno", "Prevzemeno"]
            )
            action_cell = f"""
                <div class="dropdown">
                    <button class="btn btn-outline-secondary btn-lg dropdown-toggle px-4 py-2"
                            type="button" data-bs-toggle="dropdown">Смени статус</button>
                    <ul class="dropdown-menu dropdown-menu-end shadow-lg">{options}</ul>
                </div>"""

        tbody_html += f"""
            <tr class="align-middle">
                <td><strong class="text-primary fs-5">{req.get("nalog_broj", "—")}</strong></td>
                <td>{req["datum_kreiranje_formatted"]}</td>
                <td>{req.get("username", "—")}</td>
                <td>{req.get("naslov", "—")}</td>
                <td class="fw-bold">{req.get("kolicina", 0)}</td>
                <td>
                    <div class="nabavki-deadline-stack">
                        <div>
                            <small class="text-muted d-block">Итност</small>
                            <span class="fw-semibold">{req.get("deadline_due_display", "—")}</span>
                        </div>
                        <div>
                            <small class="text-muted d-block">Вкупно</small>
                            <span class="fw-semibold">{req.get("deadline_total_label", "—")}</span>
                        </div>
                        <div>
                            <small class="text-muted d-block">{req.get("deadline_state_label", "Преостанато")}</small>
                            <span class="fw-bold {req.get("deadline_state_class", "text-muted")}">{req.get("deadline_state_value", "—")}</span>
                        </div>
                    </div>
                </td>
                <td>{slika_cell}</td>
                <td><span class="badge fs-6 py-2 px-4 rounded-pill {status_cls}">{status_display}</span></td>
                <td>{prevzemeno}</td>
                <td>
                    <button type="button" class="btn btn-outline-primary btn-lg px-4 py-2"
                            data-bs-toggle="modal" data-bs-target="#detailsModal{req.get('id')}">
                        <i class="fas fa-eye me-2"></i> Детали
                    </button>
                </td>
                <td>{action_cell}</td>
            </tr>"""

    return tbody_html


def build_export_filename(prefix, extension):
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M')}.{extension}"
