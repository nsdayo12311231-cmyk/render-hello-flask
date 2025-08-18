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

# === ここから下を app.py の既存コードの「importsの下あたり」に追記してください ===
import requests

def safe_parse_date(s: str):
    from datetime import datetime
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None

def list_due_tasks(rows, days_ahead=1):
    """
    rows_to_dicts(rows) 済みの todo 配列を受け取り、
    今日～days_ahead 日先までが期限のタスクを抽出して返す
    """
    from datetime import date, timedelta
    today = date.today()
    last = today + timedelta(days_ahead)
    due_list = []
    for t in rows_to_dicts(rows):
        d = safe_parse_date(t.get("due", ""))
        if d and today <= d <= last:
            due_list.append(t)
    return due_list

def slack_notify(text: str) -> bool:
    url = os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return False
    try:
        r = requests.post(url, json={"text": text}, timeout=10)
        return r.ok
    except Exception:
        return False



app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret")

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# Slack通知（リマインド）
@app.route("/notify")
def notify():
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return "SLACK_WEBHOOK_URL not set", 500

    ws = get_ws()
    rows = ws.get_all_values()
    tasks = rows_to_dicts(rows)
    today = date.today()

    messages = []
    for task in tasks:
        if task.get("due"):
            due_date = parse_ymd_safe(task["due"])
            if due_date:
                days_left = (due_date - today).days
                if days_left == 1:  # 期限前日
                    tags = task.get("tags", "")
                    tag_display = f" (タグ: {', '.join(tags) if isinstance(tags, list) else tags})" if tags else ""
                    messages.append(f"⚠️ 明日が期限のタスク: {task['title']}{tag_display}")

    if messages:
        payload = {"text": "\n".join(messages)}
        requests.post(webhook_url, json=payload)
        return "通知を送信しました"
    return "通知するタスクはありません"

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
    today = date.today()
    
    # 各タスクにstatusを計算して追加
    for todo in todos:
        todo["status"] = due_status(todo.get("due", ""))
        
        # 日付をMM/DD表示にし、期限切れフラグを追加
        if todo.get("due"):
            due_date = parse_ymd_safe(todo["due"])
            if due_date:
                todo["due_display"] = due_date.strftime("%m/%d")
                todo["is_overdue"] = due_date < today
            else:
                todo["due_display"] = ""
                todo["is_overdue"] = False
        else:
            todo["due_display"] = ""
            todo["is_overdue"] = False
    
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

def _post_to_slack(text: str) -> bool:
    """Slack Incoming Webhook にポストする簡易関数"""
    if not SLACK_WEBHOOK_URL:
        # Webhook未設定なら何もしない（失敗扱いにしない）
        return False
    try:
        res = requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
        return res.ok
    except Exception:
        return False

def _safe_parse_date(s: str):
    """'YYYY-MM-DD' を date に。失敗時は None。"""
    from datetime import datetime as _dt, date as _date
    try:
        return _dt.strptime((s or "").strip(), "%Y-%m-%d").date()
    except Exception:
        return None

def notify_upcoming_tasks():
    """
    スプレッドシートから期限を読み取り、
    - 期限切れ（overdue）
    - 今日（due today）
    - 明日（due tomorrow）
    をSlackにまとめて通知します。
    """
    from datetime import date, timedelta
    ws = get_ws()
    rows = ws.get_all_values()
    todos = rows_to_dicts(rows)

    today = date.today()
    tomorrow = today + timedelta(days=1)

    overdue = []
    due_today = []
    due_tomorrow = []

    for t in todos:
        d = _safe_parse_date(t.get("due", ""))
        if not d:
            continue
        line = f"- {t.get('title','(no title)')}（期日: {t.get('due','-')} / タグ: {t.get('tags','-')}）"
        if d < today:
            overdue.append(line)
        elif d == today:
            due_today.append(line)
        elif d == tomorrow:
            due_tomorrow.append(line)

    if not any([overdue, due_today, due_tomorrow]):
        _post_to_slack("📋 リマインド対象のタスクはありません。")
        return

    msg_lines = ["📣 TODOリマインド"]
    if overdue:
        msg_lines.append("\n⚠️ 期限切れ")
        msg_lines.extend(overdue)
    if due_today:
        msg_lines.append("\n🟡 今日締切")
        msg_lines.extend(due_today)
    if due_tomorrow:
        msg_lines.append("\n🟢 明日締切")
        msg_lines.extend(due_tomorrow)

    _post_to_slack("\n".join(msg_lines))

# Flask CLI コマンド: `flask --app app notify` で実行可能にする
import click
@app.cli.command("notify")
def notify_cmd():
    """Slackへ期限リマインドを送る"""
    notify_upcoming_tasks()
    click.echo("Sent reminders to Slack (if any).")

if __name__ == "__main__":
    from notify import notify_upcoming_tasks
    notify_upcoming_tasks()
