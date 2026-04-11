from datetime import date, datetime, timedelta

from utils.db import get_db
from utils.odrzuvanje_notifications import notify_new_order


AKTIVNI_STATUSI = ("креиран", "доделен", "во тек", "чека дел")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def _next_sequence(cursor, prefix):
    cursor.execute(
        """
        INSERT INTO odrzuvanje_sequences(name, last_num)
        VALUES (?, 0)
        ON CONFLICT(name) DO NOTHING
        """,
        (prefix,),
    )
    cursor.execute(
        "UPDATE odrzuvanje_sequences SET last_num = last_num + 1 WHERE name = ?",
        (prefix,),
    )
    row = cursor.execute(
        "SELECT last_num FROM odrzuvanje_sequences WHERE name = ?",
        (prefix,),
    ).fetchone()
    return f"{prefix.upper()}-{int(row['last_num']):04d}"


def _sync_machine_status(cursor, masina_id):
    rows = cursor.execute(
        """
        SELECT prioritet, tip
        FROM odrzuvanje_nalozi
        WHERE masina_id = ? AND status IN (?, ?, ?, ?)
        """,
        (masina_id, *AKTIVNI_STATUSI),
    ).fetchall()
    status = "работи"
    if rows:
        status = "сервис"
        if any((row.get("prioritet") == "критичен") or (row.get("tip") == "итно") for row in rows):
            status = "стопирана"
    cursor.execute(
        "UPDATE odrzuvanje_masini SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now(), masina_id),
    )


def _compute_next_date(plan_row, today):
    base = today
    raw = (plan_row.get("sledno_izvrsuvanje") or "").strip()
    if raw:
        try:
            base = datetime.strptime(raw, "%Y-%m-%d").date()
        except Exception:
            base = today

    interval_days = _safe_int(plan_row.get("interval_dena"), 0) or 30
    next_date = base + timedelta(days=interval_days)
    while next_date <= today:
        next_date += timedelta(days=interval_days)
    return next_date


def auto_create_due_maintenance_orders():
    conn = get_db()
    cursor = conn.cursor()
    today = date.today()
    now_ts = _now()

    due_plans = cursor.execute(
        """
        SELECT p.*, m.naziv AS masina_naziv, m.kod AS masina_kod
        FROM odrzuvanje_planovi p
        JOIN odrzuvanje_masini m ON m.id = p.masina_id
        WHERE p.aktivno = 1
          AND COALESCE(p.auto_kreiraj_nalog, 1) = 1
          AND p.sledno_izvrsuvanje IS NOT NULL
          AND p.sledno_izvrsuvanje <= ?
        ORDER BY p.sledno_izvrsuvanje ASC, p.id ASC
        """,
        (today.isoformat(),),
    ).fetchall()

    created_order_ids = []
    skipped_open_order = 0

    for plan in due_plans:
        existing_open = cursor.execute(
            """
            SELECT id
            FROM odrzuvanje_nalozi
            WHERE plan_id = ?
              AND status IN (?, ?, ?, ?)
            ORDER BY id DESC
            LIMIT 1
            """,
            (plan["id"], *AKTIVNI_STATUSI),
        ).fetchone()
        if existing_open:
            skipped_open_order += 1
            continue

        broj = _next_sequence(cursor, "NAL")
        assigned_to = (plan.get("odgovoren") or "").strip()
        order_status = "доделен" if assigned_to else "креиран"
        order_title = f"Планско одржување: {plan['naziv']}"
        defect_desc = f"Автоматски креиран налог од планот „{plan['naziv']}“."

        cursor.execute(
            """
            INSERT INTO odrzuvanje_nalozi
            (broj, masina_id, tip, prioritet, status, naslov, opis_defekt, simptom,
             prijavil, dodeleno_na, created_by, created_at, updated_at, plan_id, auto_kreirano, resenie)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                broj,
                plan["masina_id"],
                plan.get("tip") or "превентивно",
                "среден",
                order_status,
                order_title,
                defect_desc,
                "Плански сервис",
                "system-auto",
                assigned_to,
                "system-auto",
                now_ts,
                now_ts,
                plan["id"],
                1,
                "",
            ),
        )
        order_id = cursor.lastrowid
        created_order_ids.append(order_id)

        cursor.execute(
            """
            INSERT INTO odrzuvanje_nalog_aktivnosti (nalog_id, tip, poraka, created_by)
            VALUES (?, ?, ?, ?)
            """,
            (
                order_id,
                "plan",
                f"Налогот е автоматски креиран од планот „{plan['naziv']}“.",
                "system-auto",
            ),
        )

        next_date = _compute_next_date(plan, today)
        cursor.execute(
            """
            UPDATE odrzuvanje_planovi
            SET posledno_izvrseno = ?, sledno_izvrsuvanje = ?
            WHERE id = ?
            """,
            (today.isoformat(), next_date.isoformat(), plan["id"]),
        )
        cursor.execute(
            """
            UPDATE odrzuvanje_masini
            SET sledna_proverka_na = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_date.isoformat(), now_ts, plan["masina_id"]),
        )
        _sync_machine_status(cursor, plan["masina_id"])

    conn.commit()
    conn.close()

    notifications_sent = 0
    for order_id in created_order_ids:
        try:
            notify_new_order(order_id)
            notifications_sent += 1
        except Exception as exc:
            print(f"[ODRZUVANJE AUTO PLAN] Notification error for order {order_id}: {exc}")

    return {
        "due_plans": len(due_plans),
        "created_orders": len(created_order_ids),
        "skipped_open_order": skipped_open_order,
        "notified_orders": notifications_sent,
    }
