import os
import uuid
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash
from google.oauth2 import service_account
import gspread

def due_status(due_text: str) -> str:
    """
    'YYYY-MM-DD' 形式の文字列から状態を返す:
    - 期限超過: 'overdue'
    - 今日: 'due_today'
    - 未来: 'upcoming'
    - 入力なし/不正: 'no_due'
    """
    if not due_text:
        return "no_due"
    try:
        d = datetime.strptime(due_text, "%Y-%m-%d").date()
    except Exception:
        return "no_due"
    today = date.today()
    if d < today:
        return "overdue"
    if d == today:
        return "due_today"
    return "upcoming"

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
    keys = ["id", "title", "content", "due", "tags", "reminder"]
    data = []
    for r in rows[1:]:
        if len(r) < 1 or r[0] in ("", "id"):
            continue
        # 列数が足りなければ空文字でパディング
        if len(r) < len(keys):
            r = r + [""] * (len(keys) - len(r))
        data.append(dict(zip(keys, r[:len(keys)])))
    return data

def parse_ymd(s: str):
    """'YYYY-MM-DD' を date に。空/不正は None。"""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

# 1) 安全な日付パーサ
def parse_ymd_safe(s: str | None):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None



@app.route("/", methods=["GET"])
def index():
    ws = get_ws()
    rows = ws.get_all_values()
    todos = rows_to_dicts(rows)  # ヘッダー除外
    
    # 各タスクにstatusを計算して追加
    for todo in todos:
        todo["status"] = due_status(todo.get("due", ""))
    
    return render_template("index.html", todos=todos)

@app.route("/tasks")
def tasks():
    ws = get_ws()
    rows = ws.get_all_values()  # ヘッダー行＋データ行
    # 想定ヘッダー: id, title, content, due, tags, reminder
    data = []
    for r in rows[1:]:
        if not r or len(r) == 0:
            continue
        # 足りない列があっても落ちないように安全に読む
        rid   = (r[0] if len(r) > 0 else "").strip()
        title = (r[1] if len(r) > 1 else "").strip()
        cont  = (r[2] if len(r) > 2 else "").strip()
        due_s = (r[3] if len(r) > 3 else "").strip()
        tags  = (r[4] if len(r) > 4 else "").strip()
        reminder = (r[5] if len(r) > 5 else "").strip()
        
        d = parse_ymd_safe(due_s)
        
        # タグをリストに変換
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        
        data.append({
            "id": rid,
            "title": title,
            "content": cont,
            "due_raw": due_s,
            "due_date": d,
            "status": due_status(due_s),  # due_status関数を使用
            "tags": tag_list,
            "reminder": reminder,
        })

    return render_template("tasks.html", tasks=data, today=date.today())

@app.route("/add", methods=["POST"])
def add():
    ws = get_ws()
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    due = request.form.get("due", "").strip()              # "YYYY-MM-DD"
    tags = request.form.get("tags", "").strip()            # "仕事, 個人" のようなカンマ区切り文字列
    reminder = request.form.get("reminder", "").strip()    # "2025-08-18T09:30" のような datetime-local 値
    
    if not title:
        flash("タイトルは必須です")
        return redirect(url_for("index"))
    
    new_id = str(uuid.uuid4())[:8] + "-" + uuid.uuid4().hex[:4]  # 既存の生成規則に合わせてOK
    ws.append_row([new_id, title, content, due, tags, reminder], value_input_option="USER_ENTERED")
    
    # Slack通知がある場合は、メッセージに due と tags も含めて送信
    # 例: f"[追加] {title} / 期日:{due or '-'} / タグ:{tags or '-'}"
    # TODO: 実際のSlack通知処理をここに実装
    
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
                "tags": r[4] if len(r) > 4 else "",
                "reminder": r[5] if len(r) > 5 else "",
            }
            break
    if target_row_idx is None:
        flash("対象が見つかりませんでした")
        return redirect(url_for("index"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        due = request.form.get("due", "").strip()
        tags = request.form.get("tags", "").strip()
        reminder = request.form.get("reminder", "").strip()
        
        if not title:
            flash("タイトルは必須です")
            return redirect(url_for("edit", todo_id=todo_id))
        
        ws.update(f"A{target_row_idx}:F{target_row_idx}", [[todo_id, title, content, due, tags, reminder]])
        flash("更新しました")
        return redirect(url_for("index"))

    return render_template("edit.html", todo=current)
