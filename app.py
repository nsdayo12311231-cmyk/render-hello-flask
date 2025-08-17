import os
import uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
import gspread
from google.oauth2 import service_account

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

SHEET_ID = os.environ.get("SHEET_ID")
CREDS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")  # /etc/secrets/creds.json

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_ws():
    if not (SHEET_ID and CREDS_PATH):
        raise RuntimeError("SHEET_ID または GOOGLE_APPLICATION_CREDENTIALS が未設定です。")
    creds = service_account.Credentials.from_service_account_file(CREDS_PATH, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    ws = sh.sheet1  # 1枚目のシート
    # ヘッダーなければ作る
    headers = ws.row_values(1)
    target = ["id", "title", "content", "due"]
    if headers[:4] != target:
        ws.update("A1:D1", [target])
    return ws

def rows_to_dicts(rows):
    keys = ["id", "title", "content", "due"]
    out = []
    for r in rows:
        if len(r) < 1 or r[0] in ("", "id"):
            continue
        item = {k: (r[i] if i < len(r) else "") for i, k in enumerate(keys)}
        out.append(item)
    # 期日順に表示（空は最後）
    def due_key(x):
        try:
            return datetime.fromisoformat(x["due"])
        except Exception:
            return datetime.max
    return sorted(out, key=due_key)

@app.route("/", methods=["GET"])
def index():
    ws = get_ws()
    rows = ws.get_all_values()
    todos = rows_to_dicts(rows[1:])  # ヘッダー除外
    return render_template("index.html", todos=todos)

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
