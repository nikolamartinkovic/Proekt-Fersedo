from datetime import datetime
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
    "креирано": "bg-secondary",
}


def fetch_requests_with_comments(cursor, filter_type, current_user, is_nabavki_user):
    if filter_type == "my_taken" and is_nabavki_user:
        rows = cursor.execute(
            """
            SELECT *, julianday(datum_itnost) - julianday(datum_kreiranje) AS days_diff
            FROM nabavki_requests WHERE prevzemeno_od=? ORDER BY nalog_broj DESC
            """,
            (current_user,),
        ).fetchall()
        page_title = "Мои превземени барања"
    elif is_nabavki_user:
        rows = cursor.execute(
            """
            SELECT *, julianday(datum_itnost) - julianday(datum_kreiranje) AS days_diff
            FROM nabavki_requests ORDER BY nalog_broj DESC
            """
        ).fetchall()
        page_title = "Сите барања за набавки"
    else:
        rows = cursor.execute(
            """
            SELECT *, julianday(datum_itnost) - julianday(datum_kreiranje) AS days_diff
            FROM nabavki_requests WHERE username=? ORDER BY nalog_broj DESC
            """,
            (current_user,),
        ).fetchall()
        page_title = "Мои барања"

    requests_list = []
    for row in rows:
        item = dict(row)
        item["datum_kreiranje_formatted"] = (
            _format_cet(item["datum_kreiranje"]) if item.get("datum_kreiranje") else "-"
        )
        diff = item.get("days_diff")
        item["days_remaining"] = (
            f"{int(diff)} денови"
            if diff is not None and diff >= 0
            else ("Истечен рок!" if diff is not None else "Чека нарачување")
        )
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
        status_cls = STATUS_CLASS_MAP.get(req.get("status", "креирано"), "bg-secondary")
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
                <td>{req.get("datum_itnost", "—")}</td>
                <td><span class="fw-bold text-success">{req["days_remaining"]}</span></td>
                <td>{slika_cell}</td>
                <td><span class="badge fs-6 py-2 px-4 rounded-pill {status_cls}">{req.get("status", "креирано").title()}</span></td>
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
