import os

import pandas as pd
from openpyxl import Workbook

from utils.config import PARTS_EXCEL
from utils.db import get_db


def save_part_to_excel(part_number, slika_filename):
    try:
        if not os.path.exists(PARTS_EXCEL):
            wb = Workbook()
            ws = wb.active
            ws.title = "Sheet1"
            ws.append(["PartNumber", "Slika"])
            wb.save(PARTS_EXCEL)

        df = pd.read_excel(PARTS_EXCEL, engine="openpyxl")
        mask = df["PartNumber"].astype(str) == str(part_number)
        if mask.any():
            df.loc[mask, "Slika"] = slika_filename
        else:
            df = pd.concat(
                [df, pd.DataFrame([[part_number, slika_filename]], columns=["PartNumber", "Slika"])],
                ignore_index=True,
            )
        df.to_excel(PARTS_EXCEL, index=False, engine="openpyxl")
        return True
    except Exception as e:
        print(f"[EXCEL] Error saving part: {e}")
        return False


def get_part_info(part_number):
    conn = get_db()
    row = conn.execute(
        "SELECT slika, ime FROM parts WHERE TRIM(part_number) = TRIM(?)",
        (part_number,),
    ).fetchone()
    conn.close()
    if row and row["slika"]:
        return {"ime": row["ime"], "slika": f"/static/parts/{row['slika']}"}
    return None
