import os
import json
import time
from datetime import datetime
from flask import Flask, request, redirect, render_template, session, url_for, abort, Response
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

APP_DIR = os.path.dirname(os.path.abspath(__file__))

URL_PREFIX = os.environ.get("URL_PREFIX", "").rstrip("/")
ADMIN_KEY = os.environ.get("CENA_ADMIN_KEY", "CENA-6FDB41AC")
SECRET_KEY = os.environ.get("CENA_SECRET_KEY", "G5Xw-2wQTAsRcwy9KL2-CNVtTfp7wzLv")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
if not DATABASE_URL:
    DATABASE_URL = f"sqlite:///{os.path.join(APP_DIR, 'cena.db')}"

engine = create_engine(DATABASE_URL, poolclass=NullPool, future=True)
IS_PG = DATABASE_URL.startswith("postgresql")

CORRECT_ANSWER = "Flippi"
NICKNAME_OPTIONS = ["Supermario", "Flippi", "Batman", "Bomber"]
DATE_OPTIONS = [f"2026-08-{d:02d}" for d in range(10, 21)]

STATIC_URL = f"{URL_PREFIX}/static" if URL_PREFIX else "/static"

app = Flask(__name__, static_url_path=STATIC_URL)
app.secret_key = SECRET_KEY
app.config["SESSION_COOKIE_PATH"] = URL_PREFIX or "/"
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def init_db():
    id_col = "SERIAL PRIMARY KEY" if IS_PG else "INTEGER PRIMARY KEY AUTOINCREMENT"
    with engine.begin() as c:
        c.execute(text(f"""
            CREATE TABLE IF NOT EXISTS rsvps (
                id {id_col},
                name TEXT NOT NULL,
                dates_json TEXT NOT NULL,
                email TEXT,
                created_at BIGINT NOT NULL,
                updated_at BIGINT NOT NULL,
                ip TEXT,
                user_agent TEXT
            )
        """))
        c.execute(text(f"""
            CREATE TABLE IF NOT EXISTS attempts (
                id {id_col},
                name TEXT,
                answer TEXT,
                correct INTEGER,
                created_at BIGINT NOT NULL,
                ip TEXT
            )
        """))


def date_label(iso):
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%a %d/%m").capitalize()


@app.context_processor
def inject_urls():
    return {"URL_PREFIX": URL_PREFIX}


def prefixed(path):
    return f"{URL_PREFIX}{path}"


@app.route(prefixed("/") or "/")
def home():
    session.clear()
    return render_template("index.html")


@app.route(prefixed("/quiz"), methods=["GET", "POST"])
def quiz():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            return render_template("index.html", error="Scrivi il tuo nome per continuare.")
        session["name"] = name[:80]
        return render_template("quiz.html", name=session["name"], options=NICKNAME_OPTIONS)
    if "name" not in session:
        return redirect(url_for("home"))
    return render_template("quiz.html", name=session["name"], options=NICKNAME_OPTIONS)


@app.route(prefixed("/verify"), methods=["POST"])
def verify():
    name = session.get("name")
    if not name:
        return redirect(url_for("home"))
    answer = (request.form.get("nickname") or "").strip()
    correct = answer == CORRECT_ANSWER
    ip = request.headers.get("X-Forwarded-For", request.remote_addr) or ""
    ip = ip.split(",")[0].strip()
    with engine.begin() as c:
        c.execute(
            text("INSERT INTO attempts (name, answer, correct, created_at, ip) VALUES (:n, :a, :ok, :t, :ip)"),
            {"n": name, "a": answer, "ok": 1 if correct else 0, "t": int(time.time()), "ip": ip},
        )
    if not correct:
        return render_template(
            "quiz.html",
            name=name,
            options=NICKNAME_OPTIONS,
            error="Risposta sbagliata. Riprova (o chiedi ad Ale).",
        )
    session["verified"] = True
    return redirect(url_for("dates"))


@app.route(prefixed("/dates"), methods=["GET", "POST"])
def dates():
    if not session.get("verified"):
        return redirect(url_for("home"))

    if request.method == "POST":
        chosen = request.form.getlist("dates")
        chosen = [d for d in chosen if d in DATE_OPTIONS]
        if not chosen:
            return render_template(
                "dates.html",
                name=session.get("name"),
                date_options=[(d, date_label(d)) for d in DATE_OPTIONS],
                error="Seleziona almeno una data.",
                selected=[],
            )
        session["dates"] = chosen
        return redirect(url_for("secret"))

    return render_template(
        "dates.html",
        name=session.get("name"),
        date_options=[(d, date_label(d)) for d in DATE_OPTIONS],
        selected=session.get("dates", []),
    )


@app.route(prefixed("/secret"), methods=["GET", "POST"])
def secret():
    if not session.get("verified") or "dates" not in session:
        return redirect(url_for("home"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if email and "@" not in email:
            return render_template(
                "secret.html",
                name=session.get("name"),
                dates=[date_label(d) for d in session.get("dates", [])],
                error="Email non valida. Puoi anche lasciarla vuota se preferisci.",
            )
        now = int(time.time())
        ip = request.headers.get("X-Forwarded-For", request.remote_addr) or ""
        ip = ip.split(",")[0].strip()
        with engine.begin() as c:
            c.execute(
                text("""INSERT INTO rsvps (name, dates_json, email, created_at, updated_at, ip, user_agent)
                        VALUES (:n, :d, :e, :ca, :ua_t, :ip, :ua)"""),
                {
                    "n": session.get("name"),
                    "d": json.dumps(session.get("dates", [])),
                    "e": email or None,
                    "ca": now,
                    "ua_t": now,
                    "ip": ip,
                    "ua": request.headers.get("User-Agent", "")[:200],
                },
            )
        session["submitted"] = True
        return redirect(url_for("done"))

    return render_template(
        "secret.html",
        name=session.get("name"),
        dates=[date_label(d) for d in session.get("dates", [])],
    )


@app.route(prefixed("/done"))
def done():
    if not session.get("submitted"):
        return redirect(url_for("home"))
    name = session.get("name")
    session.clear()
    return render_template("done.html", name=name)


@app.route(prefixed("/admin"))
def admin():
    key = request.args.get("key", "")
    if key != ADMIN_KEY:
        abort(403)
    with engine.begin() as c:
        rsvps = list(c.execute(text(
            "SELECT id, name, dates_json, email, created_at, ip FROM rsvps ORDER BY created_at DESC"
        )).mappings())
        attempts = list(c.execute(text(
            "SELECT name, answer, correct, created_at, ip FROM attempts ORDER BY created_at DESC LIMIT 200"
        )).mappings())

    tally = {d: 0 for d in DATE_OPTIONS}
    for r in rsvps:
        for d in json.loads(r["dates_json"]):
            if d in tally:
                tally[d] += 1

    return render_template(
        "admin.html",
        rsvps=[
            {
                "id": r["id"],
                "name": r["name"],
                "dates": [date_label(d) for d in json.loads(r["dates_json"])],
                "date_isos": json.loads(r["dates_json"]),
                "email": r["email"] or "",
                "when": datetime.fromtimestamp(r["created_at"]).strftime("%d/%m %H:%M"),
                "ip": r["ip"] or "",
            }
            for r in rsvps
        ],
        attempts=[
            {
                "name": a["name"] or "",
                "answer": a["answer"] or "",
                "correct": bool(a["correct"]),
                "when": datetime.fromtimestamp(a["created_at"]).strftime("%d/%m %H:%M"),
                "ip": a["ip"] or "",
            }
            for a in attempts
        ],
        tally=[(date_label(d), d, tally[d]) for d in DATE_OPTIONS],
        admin_key=key,
    )


@app.route(prefixed("/admin/export.csv"))
def admin_export():
    key = request.args.get("key", "")
    if key != ADMIN_KEY:
        abort(403)
    with engine.begin() as c:
        rows = list(c.execute(text(
            "SELECT id, name, email, dates_json, created_at, ip FROM rsvps ORDER BY created_at DESC"
        )).mappings())
    lines = ["id,name,email,dates,created_at,ip"]
    for r in rows:
        dates_out = "|".join(json.loads(r["dates_json"]))
        name = (r["name"] or "").replace('"', "'")
        email = (r["email"] or "").replace('"', "'")
        when = datetime.fromtimestamp(r["created_at"]).isoformat()
        lines.append(f'{r["id"]},"{name}","{email}","{dates_out}",{when},{r["ip"] or ""}')
    return Response("\n".join(lines), mimetype="text/csv")


@app.route(prefixed("/healthz"))
def healthz():
    return {"ok": True}


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8798)))
