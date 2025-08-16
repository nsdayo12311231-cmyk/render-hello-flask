from flask import Flask, render_template, request, redirect, url_for
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from datetime import datetime

app = Flask(__name__)

# = Google Sheets 接続 =
# 環境変数 SPREADSHEET_ID を使います（Render で設定）
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
# サービスアカウント JSON は Render の Secret Files 経由で /etc/secrets/gsheets.json に置く想定
CREDENTIALS_PATH = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_PATH, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SPREADSHEET_ID).sheet1  # 1枚目のシートを使用

# シートのヘッダー想定: title | content | due_date
def get_all_tasks():
    records = sheet.get_all_records()
    # 並び替え（期日が空は一番後ろ）
    def keyfn(r):
        return r.get("due_date") or "9999-12-31"
    return sorted(records, key=keyfn)

@app.route("/")
def index():
    tasks = get_all_tasks()
    return render_template("index.html", tasks=tasks)

@app.route("/add", methods=["POST"])
def add():
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    due = request.form.get("due_date", "").strip()
    if not title or not content or not due:
        return redirect(url_for("index"))
    sheet.append_row([title, content, due])
    return redirect(url_for("index"))

@app.route("/edit/<int:index>", methods=["GET"])
def edit(index):
    # 表示用：1行目ヘッダなので +2 で行番号計算
    row = sheet.row_values(index + 2)
    # ヘッダ: title | content | due_date を前提
    task = {"title": row[0] if len(row) > 0 else "",
            "content": row[1] if len(row) > 1 else "",
            "due_date": row[2] if len(row) > 2 else ""}
    return render_template("edit.html", task=task, index=index)

@app.route("/update/<int:index>", methods=["POST"])
def update(index):
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    due = request.form.get("due_date", "").strip()
    # B2 から始まるわけではなく、A列1-based。index0 の1件目は2行目なので +2
    rownum = index + 2
    sheet.update(f"A{rownum}:C{rownum}", [[title, content, due]])
    return redirect(url_for("index"))

@app.route("/delete/<int:index>", methods=["POST"])
def delete(index):
    rownum = index + 2
    sheet.delete_rows(rownum)
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
