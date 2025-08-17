import os
import uuid
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash
from google.oauth2 import service_account
import gspread

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

SHEET_ID = os.environ.get("SHEET_ID")
CREDS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")  # /etc/secrets/creds.json

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_ws():
    if not (SHEET_ID and CREDS_PATH):
        raise RuntimeError("SHEET_IDまたは GOOGLE_APPLICATION_CREDENTIALS が未設定です。")
    creds = service_account.Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    return sh.sheet1

def rows_to_dicts(rows):
    keys = ["id", "title", "content", "due"]
    data = []
    for r in rows[1:]:
        if len(r) < 1 or r[0] in ("", "id"):
            continue
        data.append(dict(zip(keys, r)))
    return data

def get_due_status_class(due_str):
    """期限の状態に基づいてCSSクラスを返す"""
    if not due_str:
        return "upcoming"
    
    try:
        due_date = datetime.strptime(due_str, "%Y-%m-%d").date()
        today = date.today()
        
        if due_date < today:
            return "overdue"
        elif due_date == today:
            return "due-today"
        else:
            return "upcoming"
    except ValueError:
        return "upcoming"

# ▼ ここから追記（既存の import より下ならどこでもOK）
def _parse_ymd(s: str):
    """'YYYY-MM-DD' を date に変換。空なら None。"""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def due_status(d):
    """期日ステータス: overdue / due_today / upcoming / no_due"""
    if not d:
        return "no_due"
    today = date.today()
    if d < today:
        return "overdue"
    if d == today:
        return "due_today"
    return "upcoming"

@app.route("/", methods=["GET"])
def index():
    ws = get_ws()
    rows = ws.get_all_values()
    todos = rows_to_dicts(rows)  # ヘッダー除外
    return render_template("index.html", todos=todos)

@app.route("/tasks")
def tasks():
    ws = get_ws()
    rows = ws.get_all_values()  # ヘッダー行＋データ行
    # 想定ヘッダー: id, title, content, due, (任意で tags も後で追加予定)
    data = []
    for r in rows[1:]:
        if not r or len(r) == 0:
            continue
        # 足りない列があっても落ちないように安全に読む
        rid   = (r[0] if len(r) > 0 else "").strip()
        title = (r[1] if len(r) > 1 else "").strip()
        cont  = (r[2] if len(r) > 2 else "").strip()
        due_s = (r[3] if len(r) > 3 else "").strip()
        d     = _parse_ymd(due_s)
        data.append({
            "id": rid,
            "title": title,
            "content": cont,
            "due_raw": due_s,
            "due_date": d,
            "status": due_status(d),
        })

    return render_template("tasks.html", tasks=data, today=date.today())

@app.route("/add", methods=["POST"])
def add():
    ws = get_ws()
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    due = request.form.get("due", "").strip()  # 例: 2025-08-31
    if not title:
        flash("タイトルは必須です")
        return redirect(url_for("index"))
    todo_id = str(uuid.uuid4())
    ws.append_row([todo_id, title, content, due])
    flash("追加しました")
    return redirect(url_for("index"))

@app.route("/edit/<todo_id>", methods=["GET", "POST"])
def edit(todo_id):
    ws = get_ws()
    rows = ws.get_all_values()
    # 対象行を探す（2行目以降）
    target_row_idx = None
    current = None
    for i, r in enumerate(rows[1:], start=2):
        if len(r) > 0 and r[0] == todo_id:
            target_row_idx = i
            current = {
                "id": r[0],
                "title": r[1] if len(r) > 1 else "",
                "content": r[2] if len(r) > 2 else "",
                "due": r[3] if len(r) > 3 else "",
            }
            break
    if target_row_idx is None:
        flash("対象が見つかりませんでした")
        return redirect(url_for("index"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        due = request.form.get("due", "").strip()
        if not title:
            flash("タイトルは必須です")
            return redirect(url_for("edit", todo_id=todo_id))
        ws.update(f"A{target_row_idx}:D{target_row_idx}", [[todo_id, title, content, due]])
        flash("更新しました")
        return redirect(url_for("index"))

    return render_template("edit.html", todo=current)
