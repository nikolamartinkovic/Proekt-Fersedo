import os
import time
import json
import base64
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

from flask import (
    Blueprint, render_template, request, flash, redirect, url_for,
    send_from_directory, session
)
from werkzeug.utils import secure_filename
from utils.db import get_db
from utils.decorators import login_required, user_has_module
from groq import Groq

sostanoci_bp = Blueprint('sostanoci', __name__, url_prefix='/sostanoci')

# --- CONFIG ---
UPLOAD_FOLDER = os.path.join("static", "sostanoci_audio")
ALLOWED_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.ogg', '.webm'}
MAX_FILE_SIZE = 400 * 1024 * 1024  # 400 MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)



# --- TABLE INIT ---
def init_sostanoci_table():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sostanoci (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                naslov        TEXT NOT NULL,
                datum         TEXT NOT NULL,
                ucesnici      TEXT,
                audio_file    TEXT,
                transkripcija TEXT,
                rezime        TEXT,
                glavni_tocki  TEXT,
                odluki        TEXT,
                zadaci        TEXT,
                username      TEXT NOT NULL,
                timestamp     TEXT NOT NULL
            )
        """)
        existing = [
            row["name"] for row in conn.execute("PRAGMA table_info(sostanoci)")
        ]
        if "odluki" not in existing:
            conn.execute("ALTER TABLE sostanoci ADD COLUMN odluki TEXT")
        if "zadaci" not in existing:
            conn.execute("ALTER TABLE sostanoci ADD COLUMN zadaci TEXT")
        conn.commit()

init_sostanoci_table()


@sostanoci_bp.before_request
def ensure_sostanoci_access():
    if "user" not in session:
        return None
    if user_has_module("sostanoci"):
        return None
    flash("Немате дозвола за пристап до модулот Состаноци.", "danger")
    return redirect(url_for("auth.index"))

# --- HELPERS ---
def allowed_file(filename):
    return '.' in filename and os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


def clean_json_response(text):
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
    return text


def save_audio_file(audio_source, naslov):
    if hasattr(audio_source, 'read'):
        audio_source.seek(0, 2)
        size = audio_source.tell()
        audio_source.seek(0)
        if size > MAX_FILE_SIZE:
            raise ValueError("Fajlot e pogolem od 400MB")
        ext = os.path.splitext(audio_source.filename)[1].lower()
        filename = f"sostanok_{int(time.time())}_{secure_filename(naslov[:30])}{ext}"
        path = os.path.join(UPLOAD_FOLDER, filename)
        audio_source.save(path)
    else:
        filename = f"sostanok_{int(time.time())}_{secure_filename(naslov[:30])}.webm"
        path = os.path.join(UPLOAD_FOLDER, filename)
        header, data = audio_source.split(",", 1)
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))

    return filename, path


def ai_process_audio(audio_path):
    from pathlib import Path
    import subprocess
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")

    try:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY не е пронајден во .env фајлот!")

        groq_client = Groq(api_key=api_key)

        print(f"[AUDIO] Processing file: {audio_path}")
        print(f"[AUDIO] File size: {os.path.getsize(audio_path)} bytes")

        MAX_BYTES = 23 * 1024 * 1024  # 23 MB

        # ── Сечење со ffmpeg ако е поголем од 23MB ───────────────
        def get_duration_seconds(path):
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", path],
                capture_output=True, text=True
            )
            return float(result.stdout.strip())

        def split_audio(path, chunk_seconds=600):
            """Сечи на парчиња од 10 мин со ffmpeg"""
            ext = os.path.splitext(path)[1].lower() or ".webm"
            duration = get_duration_seconds(path)
            chunks = []
            start = 0
            i = 0
            while start < duration:
                chunk_path = path.replace(ext, f"_chunk{i}{ext}")
                subprocess.run([
                    "ffmpeg", "-y", "-i", path,
                    "-ss", str(start),
                    "-t", str(chunk_seconds),
                    "-c", "copy",
                    chunk_path
                ], capture_output=True)
                chunks.append(chunk_path)
                start += chunk_seconds
                i += 1
            return chunks

        file_size = os.path.getsize(audio_path)
        if file_size <= MAX_BYTES:
            chunks = [audio_path]
            print(f"[AUDIO] Фајлот е мал, без сечење")
        else:
            print(f"[AUDIO] Фајлот е голем ({file_size} bytes), сечам...")
            chunks = split_audio(audio_path)
            print(f"[AUDIO] Сечен на {len(chunks)} чанкови")

        # ── Транскрипција ─────────────────────────────────────────
        ext = os.path.splitext(audio_path)[1].lower().replace(".", "") or "webm"
        full_transcript = ""
        for i, chunk_path in enumerate(chunks):
            print(f"[WHISPER] Транскрибирам чанк {i+1}/{len(chunks)}...")
            with open(chunk_path, "rb") as af:
                transcript = groq_client.audio.transcriptions.create(
                    model="whisper-large-v3",
                    file=(os.path.basename(chunk_path), af, f"audio/{ext}"),
                    response_format="text",
                    language="mk"
                )
            full_transcript += transcript.strip() + " "

            # Избриши привремени чанкови
            if chunk_path != audio_path and os.path.exists(chunk_path):
                os.remove(chunk_path)

        text = full_transcript.strip()
        print(f"[WHISPER] Транскрипција: {len(text)} карактери")

        if not text:
            raise ValueError("Транскрипцијата е празна")

        # ── Резиме преку LLaMA ────────────────────────────────────
        prompt = f"""
Ti si profesionalen asistent vo proizvodna kompanija Fersedo.
Napravi rezime na makedonski jazik od sledniov transkribirani sostanok.

{text[:15000]}

Vrati SAMO validen JSON bez markdown, bez objasnuvanje:

{{
  "kratko_rezime": "Kratek opis vo 2-4 rechenici na makedonski",
  "glavni_tocki": ["Glavna tocka 1", "Glavna tocka 2"],
  "odluki": ["Odluka 1", "Odluka 2"],
  "zadaci": ["Zadaca 1 - odgovorno lice i rok"]
}}
"""
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=1200
        )

        print(f"[LLaMA] Response: {response.choices[0].message.content}")
        raw = clean_json_response(response.choices[0].message.content)
        ai = json.loads(raw)

        return {
            "transkripcija": text,
            "rezime":        ai.get("kratko_rezime", "Nema rezime"),
            "glavni_tocki":  "\n".join(f"- {t}" for t in ai.get("glavni_tocki", [])),
            "odluki":        "\n".join(f"- {o}" for o in ai.get("odluki", [])),
            "zadaci":        "\n".join(f"- {z}" for z in ai.get("zadaci", [])),
        }

    except Exception as e:
        print(f"[AI ERROR] {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            "transkripcija": "Greshka pri obrabotka",
            "rezime":        f"Neuspeshna obrabotka: {str(e)}",
            "glavni_tocki":  "- Nema podatoci",
            "odluki":        "- Nema podatoci",
            "zadaci":        "- Nema podatoci",
        }


# --- ROUTES ---

@sostanoci_bp.route("/")
@login_required
def lista():
    with get_db() as conn:
        sostanoci = conn.execute("""
            SELECT id, naslov, datum, ucesnici, rezime, username, timestamp
            FROM sostanoci
            ORDER BY timestamp DESC
        """).fetchall()
    return render_template("sostanoci_lista.html", sostanoci=sostanoci)


@sostanoci_bp.route("/nov", methods=["GET", "POST"])
@login_required
def nov_sostanok():
    if request.method == "POST":
        naslov   = request.form.get("naslov", "").strip()
        ucesnici = request.form.get("ucesnici", "").strip()
        audio    = request.files.get("audio")
        recorded = request.form.get("recorded_audio", "").strip()

        if not naslov:
            flash("Vnesi naslov na sostanokot!", "danger")
            return redirect(url_for("sostanoci.nov_sostanok"))

        audio_source = None
        if audio and audio.filename and allowed_file(audio.filename):
            audio_source = audio
        elif recorded and recorded.startswith("data:audio"):
            audio_source = recorded

        if not audio_source:
            flash("Prikachi audio fajl ili snimi preku mikrofon.", "danger")
            return redirect(url_for("sostanoci.nov_sostanok"))

        try:
            audio_filename, audio_path = save_audio_file(audio_source, naslov)
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("sostanoci.nov_sostanok"))

        ai = ai_process_audio(audio_path)

        with get_db() as conn:
            conn.execute("""
                INSERT INTO sostanoci
                (naslov, datum, ucesnici, audio_file, transkripcija,
                 rezime, glavni_tocki, odluki, zadaci, username, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                naslov,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                ucesnici,
                audio_filename,
                ai["transkripcija"],
                ai["rezime"],
                ai["glavni_tocki"],
                ai["odluki"],
                ai["zadaci"],
                session["user"],
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            conn.commit()

        flash("Sostanokot e uspeshno snimen i AI go rezimira!", "success")
        return redirect(url_for("sostanoci.lista"))

    return render_template("sostanoci_nov.html")


@sostanoci_bp.route("/<int:id>")
@login_required
def detalji(id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sostanoci WHERE id=?", (id,)).fetchone()
    if not row:
        flash("Sostanokot ne postoi!", "danger")
        return redirect(url_for("sostanoci.lista"))
    return render_template("sostanoci_detalji.html", s=dict(row))


@sostanoci_bp.route("/<int:id>/delete", methods=["POST"])
@login_required
def delete(id):
    with get_db() as conn:
        row = conn.execute("SELECT audio_file FROM sostanoci WHERE id=?", (id,)).fetchone()
        if row and row["audio_file"]:
            path = os.path.join(UPLOAD_FOLDER, row["audio_file"])
            if os.path.exists(path):
                os.remove(path)
        conn.execute("DELETE FROM sostanoci WHERE id=?", (id,))
        conn.commit()
    flash("Sostanokot e izbrisan.", "info")
    return redirect(url_for("sostanoci.lista"))


@sostanoci_bp.route("/audio/<filename>")
@login_required
def serve_audio(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)
