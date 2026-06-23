import base64
import csv
import hashlib
import io
import json
import os
import re
import secrets
import smtplib
import sqlite3
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps

from .countries import (
    COUNTRIES,
    CODE_TO_ASSET,
    NAME_BY_CODE,
    code_from_flag,
    flag_from_code,
)

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = os.path.dirname(__file__)

DTO_FIELDS = [
    "id",
    "carrier",
    "plan",
    "phoneNumber",
    "countryCode",
    "countryName",
    "flag",
    "cardBackgroundAssetName",
    "cardColorHex",
    "cardBackgroundImageData",
    "carrierAppIconURLString",
    "carrierAppStoreURLString",
    "carrierAppName",
    "activationDate",
    "expiryDate",
    "price",
    "currencyCode",
    "cyclePaymentMinorUnits",
    "currentBalanceMinorUnits",
    "websiteURL",
    "currentBalance",
    "transactionNotes",
    "customPrompt",
    "tags",
    "orderIndex",
    "smdpAddress",
    "activationCode",
    "confirmationCode",
    "eid",
    "createdAt",
    "updatedAt",
    "isLongTerm",
    "renewDays",
    "renewalUnit",
    "renewalIntervalValue",
]

DTO_TO_COL = {
    "id": "id",
    "carrier": "carrier",
    "plan": "plan",
    "phoneNumber": "phone_number",
    "countryCode": "country_code",
    "countryName": "country_name",
    "flag": "flag",
    "cardBackgroundAssetName": "card_background_asset_name",
    "cardColorHex": "card_color_hex",
    "cardBackgroundImageData": "card_background_image_data",
    "carrierAppIconURLString": "carrier_app_icon_url_string",
    "carrierAppStoreURLString": "carrier_app_store_url_string",
    "carrierAppName": "carrier_app_name",
    "activationDate": "activation_date",
    "expiryDate": "expiry_date",
    "price": "price",
    "currencyCode": "currency_code",
    "cyclePaymentMinorUnits": "cycle_payment_minor_units",
    "currentBalanceMinorUnits": "current_balance_minor_units",
    "websiteURL": "website_url",
    "currentBalance": "current_balance",
    "transactionNotes": "transaction_notes",
    "customPrompt": "custom_prompt",
    "orderIndex": "order_index",
    "smdpAddress": "smdp_address",
    "activationCode": "activation_code",
    "confirmationCode": "confirmation_code",
    "eid": "eid",
    "createdAt": "created_at",
    "updatedAt": "updated_at",
    "isLongTerm": "is_long_term",
    "renewDays": "renew_days",
    "renewalUnit": "renewal_unit",
    "renewalIntervalValue": "renewal_interval_value",
}

OPTIONAL_FIELDS = {
    "cardBackgroundAssetName",
    "cardColorHex",
    "cardBackgroundImageData",
    "carrierAppIconURLString",
    "carrierAppStoreURLString",
    "carrierAppName",
    "currencyCode",
    "cyclePaymentMinorUnits",
    "currentBalanceMinorUnits",
    "websiteURL",
    "currentBalance",
    "transactionNotes",
    "customPrompt",
    "tags",
    "orderIndex",
    "confirmationCode",
    "updatedAt",
    "renewalUnit",
    "renewalIntervalValue",
}


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            if request.path.startswith("/api/"):
                return api_fail("未登录", "UNAUTHORIZED", 401)
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    app.config["DATABASE"] = os.environ.get("DATABASE") or os.path.join(BASE_DIR, "..", "data", "simhub.sqlite")

    @app.before_request
    def before_request():
        init_db()
        g.user = current_user()
        public_endpoints = {"setup", "login", "login_code", "static", "api_status", "manifest", "service_worker"}
        if user_count() == 0 and request.endpoint not in public_endpoints:
            if request.path.startswith("/api/"):
                return api_fail("请先创建管理员", "SETUP_REQUIRED", 403)
            return redirect(url_for("setup"))

    @app.context_processor
    def inject_helpers():
        return {
            "csrf_token": csrf_token,
            "date_input": date_input,
            "days_left": days_left,
            "due_badge": due_badge,
            "price_number": price_number,
        }

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if user_count() > 0:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            validate_csrf()
            username = request.form.get("username", "").strip() or "admin"
            password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")
            if len(password) < 8:
                flash("密码至少需要 8 位。", "error")
            elif password != confirm:
                flash("两次输入的密码不一致。", "error")
            else:
                get_db().execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, hash_password(password)),
                )
                get_db().commit()
                flash("管理员已创建，请登录。", "success")
                return redirect(url_for("login"))
        return render_template("setup.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            validate_csrf()
            ip = client_ip()
            remaining = login_lock_remaining(ip)
            if remaining > 0:
                flash(f"尝试次数过多，请 {remaining // 60 + 1} 分钟后再试。", "error")
                return render_template("login.html")
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if user and check_password_hash(user["password_hash"], password):
                clear_login_fails(ip)
                settings_row = get_settings()
                two_fa = settings_row and settings_row["twofa_enabled"] and smtp_configured()
                email = smtp_config()["recipient"] if two_fa else None
                if two_fa and email:
                    code = f"{secrets.randbelow(1000000):06d}"
                    try:
                        send_login_code(email, code)
                    except Exception:
                        flash("验证码邮件发送失败，请检查 SMTP 配置。", "error")
                        return render_template("login.html")
                    session.clear()
                    session["csrf_token"] = secrets.token_urlsafe(32)
                    session["pending_login"] = {
                        "uid": user["id"],
                        "code_hash": hash_password(code),
                        "expires": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                        "email": mask_email(email),
                        "tries": 0,
                    }
                    flash("验证码已发送到你的邮箱。", "success")
                    return redirect(url_for("login_code"))
                session.clear()
                session["user_id"] = user["id"]
                session["csrf_token"] = secrets.token_urlsafe(32)
                flash("登录成功。", "success")
                return redirect(url_for("dashboard"))
            record_login_fail(ip)
            flash("用户名或密码错误。", "error")
        return render_template("login.html")

    @app.route("/login/code", methods=["GET", "POST"])
    def login_code():
        if g.user:
            return redirect(url_for("dashboard"))
        pending = session.get("pending_login")
        if not pending:
            return redirect(url_for("login"))
        if datetime.now(timezone.utc) > datetime.fromisoformat(pending["expires"]):
            session.pop("pending_login", None)
            flash("验证码已过期，请重新登录。", "error")
            return redirect(url_for("login"))
        if request.method == "POST":
            validate_csrf()
            code = request.form.get("code", "").strip()
            if pending["tries"] >= 5:
                session.pop("pending_login", None)
                flash("尝试次数过多，请重新登录。", "error")
                return redirect(url_for("login"))
            if check_password_hash(pending["code_hash"], code):
                uid = pending["uid"]
                session.clear()
                session["user_id"] = uid
                session["csrf_token"] = secrets.token_urlsafe(32)
                flash("登录成功。", "success")
                return redirect(url_for("dashboard"))
            pending["tries"] += 1
            session["pending_login"] = pending
            flash("验证码错误。", "error")
        return render_template("login_code.html", email=pending.get("email", ""))

    @app.route("/logout", methods=["POST"])
    @login_required
    def logout():
        validate_csrf()
        session.clear()
        flash("已退出登录。", "success")
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        try:
            run_due_reminders()
        except Exception:
            pass
        return Response(render_spa(), mimetype="text/html; charset=utf-8")

    @app.route("/cards/new", methods=["GET", "POST"])
    @login_required
    def new_card():
        if request.method == "POST":
            validate_csrf()
            dto, errors = form_dto()
            if not errors:
                dto["id"] = str(uuid.uuid4())
                dto["orderIndex"] = next_order_index()
                insert_card(dto)
                log_activity(dto["id"], "create", "创建卡片")
                get_db().commit()
                flash("卡片已添加。", "success")
                return redirect(url_for("dashboard"))
            for error in errors:
                flash(error, "error")
        return render_template("card_form.html", card=default_dto())

    @app.route("/cards/<card_id>/edit", methods=["GET", "POST"])
    @login_required
    def edit_card(card_id):
        card = get_card(card_id)
        if request.method == "POST":
            validate_csrf()
            dto, errors = form_dto(existing=card)
            if not errors:
                dto["id"] = card_id
                update_card(card_id, dto)
                log_activity(card_id, "edit", "更新卡片资料")
                get_db().commit()
                flash("卡片已更新。", "success")
                return redirect(url_for("dashboard"))
            for error in errors:
                flash(error, "error")
        return render_template("card_form.html", card=card)

    @app.route("/cards/<card_id>/renew", methods=["POST"])
    @login_required
    def renew_card(card_id):
        validate_csrf()
        card = get_card(card_id)
        renew_days = max(int(card.get("renewDays") or 30), 1)
        start = date.today()
        expiry = start + timedelta(days=renew_days)
        updated = dict(card)
        updated["activationDate"] = iso_datetime(start)
        updated["expiryDate"] = iso_datetime(expiry)
        updated["updatedAt"] = now_iso()
        updated["renewalUnit"] = updated.get("renewalUnit") or "days"
        updated["renewalIntervalValue"] = updated.get("renewalIntervalValue") or renew_days
        update_card(card_id, updated)
        log_activity(card_id, "renew", f"完成续期，顺延 {renew_days} 天")
        get_db().commit()
        flash("已按周期顺延到期日。", "success")
        return redirect(url_for("dashboard"))

    @app.route("/cards/<card_id>/delete", methods=["POST"])
    @login_required
    def delete_card_route(card_id):
        validate_csrf()
        get_card(card_id)
        get_db().execute("DELETE FROM cards WHERE id = ?", (card_id,))
        get_db().commit()
        flash("卡片已删除。", "success")
        return redirect(url_for("dashboard"))

    @app.route("/settings/password", methods=["GET", "POST"])
    @login_required
    def change_password():
        if request.method == "POST":
            validate_csrf()
            old_password = request.form.get("old_password", "")
            password = request.form.get("password", "")
            confirm = request.form.get("confirm", "")
            user = get_db().execute("SELECT * FROM users WHERE id = ?", (g.user["id"],)).fetchone()
            if not check_password_hash(user["password_hash"], old_password):
                flash("当前密码不正确。", "error")
            elif len(password) < 8:
                flash("新密码至少需要 8 位。", "error")
            elif password != confirm:
                flash("两次输入的新密码不一致。", "error")
            else:
                get_db().execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (hash_password(password), g.user["id"]),
                )
                get_db().commit()
                flash("密码已更新。", "success")
                return redirect(url_for("dashboard"))
        return render_template("change_password.html")

    @app.route("/export.csv")
    @login_required
    def export_csv():
        cards = load_cards({})
        fields = [
            "carrier",
            "plan",
            "phoneNumber",
            "countryName",
            "expiryDate",
            "price",
            "currencyCode",
            "currentBalance",
            "tags",
            "smdpAddress",
            "activationCode",
            "eid",
        ]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(fields)
        for card in cards:
            writer.writerow([", ".join(card[field]) if field == "tags" else card.get(field, "") for field in fields])
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=simhub-cards.csv"},
        )

    @app.route("/export.json")
    @login_required
    def export_json_page():
        return export_cards_response(load_cards({}))

    @app.route("/api/status")
    def api_status():
        cards = load_cards({}) if user_count() else []
        updated = max((parse_iso(c.get("updatedAt")) or datetime.fromtimestamp(0, tz=timezone.utc) for c in cards), default=datetime.fromtimestamp(0, tz=timezone.utc))
        return api_ok(
            {
                "deviceName": os.environ.get("SIMHUB_DEVICE_NAME", "SimHub Keeper Linux"),
                "connectedDevices": 1 if g.user else 0,
                "dataVersion": updated.timestamp(),
                "cardCount": len(cards),
            }
        )

    @app.route("/api/cards", methods=["GET", "POST"])
    @login_required
    def api_cards():
        if request.method == "GET":
            return api_ok(load_cards({}))
        dto = normalize_dto(request.get_json(silent=True) or {})
        dto["id"] = str(uuid.uuid4())
        dto["orderIndex"] = next_order_index()
        insert_card(dto)
        log_activity(dto["id"], "create", "新建卡片", label=dto.get("carrier") or "未命名")
        get_db().commit()
        return api_ok(dto, 201)

    @app.route("/api/cards/<card_id>", methods=["GET", "PUT", "DELETE"])
    @login_required
    def api_card(card_id):
        card = get_card(card_id)
        if request.method == "GET":
            return api_ok(card)
        if request.method == "DELETE":
            get_db().execute("DELETE FROM cards WHERE id = ?", (card_id,))
            log_activity(card_id, "delete", "删除卡片", label=card.get("carrier") or "未命名")
            get_db().commit()
            return api_ok({"deleted": True})

        dto = normalize_dto(request.get_json(silent=True) or {}, existing=card)
        dto["id"] = card_id
        update_card(card_id, dto)
        log_activity(card_id, "edit", "编辑卡片", label=dto.get("carrier") or "未命名")
        get_db().commit()
        return api_ok(get_card(card_id))

    @app.route("/api/cards/batch-update", methods=["POST"])
    @login_required
    def api_batch_update():
        body = request.get_json(silent=True) or {}
        ids = [item for item in body.get("ids", []) if isinstance(item, str)]
        action = body.get("action", "")
        if action == "delete":
            deleted = 0
            for card_id in set(ids):
                try:
                    label = get_card(card_id).get("carrier") or "未命名"
                except Exception:
                    label = ""
                cur = get_db().execute("DELETE FROM cards WHERE id = ?", (card_id,))
                if cur.rowcount:
                    log_activity(card_id, "delete", "批量删除", label=label)
                deleted += cur.rowcount
            get_db().commit()
            return api_ok({"deleted": deleted})
        if action == "addTags":
            tags = normalize_tags(body.get("tags", []))
            updated = 0
            for card_id in set(ids):
                try:
                    card = get_card(card_id)
                except Exception:
                    continue
                card["tags"] = normalize_tags(card.get("tags", []) + tags)
                update_card(card_id, card)
                log_activity(card_id, "edit", "批量打标签：" + "、".join(tags), label=card.get("carrier") or "未命名")
                updated += 1
            get_db().commit()
            return api_ok({"updated": updated})
        return api_fail("不支持的批量操作", "BAD_REQUEST", 400)

    @app.route("/api/export")
    @login_required
    def api_export():
        return export_cards_response(load_cards({}))

    @app.route("/api/import", methods=["POST"])
    @login_required
    def api_import():
        body = request.get_json(silent=True) or {}
        raw_cards = body.get("cards", [])
        if not isinstance(raw_cards, list):
            return api_fail("导入 payload 必须是卡片数组", "BAD_REQUEST", 400)
        dtos = [normalize_dto(item) for item in raw_cards if isinstance(item, dict)]
        if body.get("mode") != "commit":
            return api_ok({"count": len(dtos), "cards": dtos})

        imported = 0
        skipped = 0
        for dto in dtos:
            if dto.get("id") and card_exists(dto["id"]):
                skipped += 1
                continue
            dto["id"] = dto.get("id") or str(uuid.uuid4())
            if duplicate_card(dto):
                skipped += 1
                continue
            dto["orderIndex"] = next_order_index() + imported
            insert_card(dto)
            imported += 1
        if imported:
            log_activity("", "import", f"导入 {imported} 张卡片（跳过 {skipped}）", label="导入")
        get_db().commit()
        return api_ok({"imported": imported, "skipped": skipped})

    @app.route("/api/activity")
    @login_required
    def api_activity():
        rows = get_db().execute(
            "SELECT card_id, card_label, action, note, created_at "
            "FROM activity_log ORDER BY id DESC LIMIT 50"
        ).fetchall()
        return api_ok(
            [
                {
                    "cardId": r["card_id"],
                    "label": r["card_label"],
                    "action": r["action"],
                    "note": r["note"],
                    "createdAt": r["created_at"],
                }
                for r in rows
            ]
        )

    @app.route("/manifest.webmanifest")
    def manifest():
        data = {
            "name": "SIMHUB Web",
            "short_name": "SIMHUB",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "background_color": "#f2f2f7",
            "theme_color": "#0a84ff",
            "icons": [
                {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
            ],
        }
        return Response(json.dumps(data), mimetype="application/manifest+json")

    @app.route("/sw.js")
    def service_worker():
        sw = """
const CACHE='simhub-v1';
const ASSETS=['/static/styles.css','/static/icon-192.png','/static/icon-512.png'];
self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS).catch(()=>{})).then(()=>self.skipWaiting()));});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));});
self.addEventListener('fetch',e=>{
  const req=e.request; if(req.method!=='GET')return;
  const url=new URL(req.url);
  if(url.pathname.startsWith('/static/')){
    e.respondWith(caches.match(req).then(r=>r||fetch(req).then(resp=>{const cp=resp.clone();caches.open(CACHE).then(c=>c.put(req,cp));return resp;})));
    return;
  }
  e.respondWith(fetch(req).catch(()=>caches.match(req)));
});
"""
        resp = Response(sw, mimetype="application/javascript")
        resp.headers["Service-Worker-Allowed"] = "/"
        return resp

    @app.route("/api/countries")
    @login_required
    def api_countries():
        out = []
        for c in COUNTRIES:
            item = dict(c)
            item["bgUrl"] = url_for("static", filename=c["bgFile"]) if c.get("bgFile") else ""
            out.append(item)
        return api_ok(out)

    @app.route("/api/appsearch")
    @login_required
    def api_appsearch():
        term = request.args.get("term", "").strip()
        country = (request.args.get("country", "US") or "US").upper()
        if not term:
            return api_ok([])
        query = urllib.parse.urlencode(
            {
                "term": term,
                "media": "software",
                "entity": "software",
                "limit": "20",
                "country": country,
            }
        )
        url = "https://itunes.apple.com/search?" + query
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "simhub-keeper-web"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return api_fail("App Store 搜索失败，请稍后重试", "APPSEARCH_FAILED", 502)
        results = []
        for item in payload.get("results", []):
            results.append(
                {
                    "name": item.get("trackName", ""),
                    "icon": item.get("artworkUrl512") or item.get("artworkUrl100") or "",
                    "url": item.get("trackViewUrl", ""),
                    "seller": item.get("sellerName", ""),
                }
            )
        return api_ok(results)

    @app.route("/api/password", methods=["POST"])
    @login_required
    def api_password():
        body = request.get_json(silent=True) or {}
        current = body.get("current", "")
        new_password = body.get("new", "")
        row = get_db().execute(
            "SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)
        ).fetchone()
        if not row or not check_password_hash(row["password_hash"], current):
            return api_fail("当前密码不正确", "BAD_PASSWORD", 400)
        if len(new_password) < 8:
            return api_fail("新密码至少需要 8 位", "WEAK_PASSWORD", 400)
        get_db().execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), g.user["id"]),
        )
        get_db().commit()
        return api_ok({"updated": True})

    @app.route("/api/smtp")
    @login_required
    def api_smtp_get():
        row = get_settings()
        return api_ok(
            {
                "host": row["smtp_host"],
                "port": row["smtp_port"],
                "username": row["smtp_username"],
                "hasPassword": bool(row["smtp_password"]),
                "recipient": row["recipient"],
                "twofaEnabled": bool(row["twofa_enabled"]),
                "reminderEnabled": bool(row["reminder_enabled"]),
                "reminderDaysBefore": row["reminder_days_before"],
                "ready": smtp_configured(),
            }
        )

    @app.route("/api/smtp", methods=["POST"])
    @login_required
    def api_smtp_save():
        body = request.get_json(silent=True) or {}
        host = (body.get("host") or "").strip()
        username = (body.get("username") or "").strip()
        recipient = (body.get("recipient") or "").strip()
        try:
            port = int(body.get("port") or 465)
        except (TypeError, ValueError):
            return api_fail("端口必须是数字", "BAD_PORT", 400)
        if username and not valid_email(username):
            return api_fail("发信邮箱格式不正确", "BAD_EMAIL", 400)
        if recipient and not valid_email(recipient):
            return api_fail("收件邮箱格式不正确", "BAD_EMAIL", 400)
        row = get_settings()
        # 密码留空表示不修改；传入新值则加密保存
        password = body.get("password")
        if password is None or password == "":
            enc = row["smtp_password"]
        else:
            enc = encrypt_secret(password.strip())
        get_db().execute(
            """UPDATE settings SET smtp_host=?, smtp_port=?, smtp_username=?, smtp_password=?,
               recipient=?, twofa_enabled=?, reminder_enabled=?, reminder_days_before=? WHERE id=1""",
            (
                host,
                port,
                username,
                enc,
                recipient,
                1 if body.get("twofaEnabled") else 0,
                1 if body.get("reminderEnabled") else 0,
                max(int(body.get("reminderDaysBefore") or 3), 0),
            ),
        )
        get_db().commit()
        return api_ok({"ready": smtp_configured()})

    @app.route("/api/smtp/test", methods=["POST"])
    @login_required
    def api_smtp_test():
        cfg = smtp_config()
        target = cfg["recipient"] or cfg["username"]
        if not target:
            return api_fail("请先填写发信邮箱", "NO_RECIPIENT", 400)
        try:
            send_email(
                target,
                "SIMHUB Web 测试邮件",
                "这是一封来自 SIMHUB Web 的测试邮件。能收到说明 SMTP 配置正确。",
            )
        except Exception as exc:
            return api_fail(f"发送失败：{exc}", "SEND_FAILED", 502)
        return api_ok({"sent": True, "to": mask_email(target)})

    @app.teardown_appcontext
    def close_db(_error):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return api_fail("未找到资源", "NOT_FOUND", 404)
        return render_template("404.html"), 404

    return app


app = create_app()


_SPA_PATH = os.path.join(BASE_DIR, "templates", "spa.html")
_spa_cache = {}


def render_spa():
    """读取单页应用模板并注入当前会话的 CSRF token。"""
    mtime = os.path.getmtime(_SPA_PATH)
    if _spa_cache.get("mtime") != mtime:
        with open(_SPA_PATH, encoding="utf-8") as fh:
            _spa_cache["html"] = fh.read()
        _spa_cache["mtime"] = mtime
    return _spa_cache["html"].replace("__CSRF_TOKEN__", csrf_token())


def get_db():
    if "db" not in g:
        db_path = app.config["DATABASE"]
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


def init_db():
    if getattr(g, "_db_initialized", False):
        return
    with app.open_resource("schema.sql") as fh:
        get_db().executescript(fh.read().decode("utf-8"))
    # 轻量迁移：为旧数据库补上 users.email 列
    columns = {row["name"] for row in get_db().execute("PRAGMA table_info(users)")}
    if "email" not in columns:
        get_db().execute("ALTER TABLE users ADD COLUMN email TEXT")
    # 迁移 activity_log：去掉会随删卡级联清空的外键，加 card_label 留存卡名
    acols = {row["name"] for row in get_db().execute("PRAGMA table_info(activity_log)")}
    if acols and "card_label" not in acols:
        get_db().executescript(
            """
            CREATE TABLE activity_log_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT, card_label TEXT, action TEXT NOT NULL, note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO activity_log_new (id, card_id, action, note, created_at)
                SELECT id, card_id, action, note, created_at FROM activity_log;
            DROP TABLE activity_log;
            ALTER TABLE activity_log_new RENAME TO activity_log;
            """
        )
    get_db().commit()
    g._db_initialized = True


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return get_db().execute("SELECT id, username, email FROM users WHERE id = ?", (user_id,)).fetchone()


def user_count():
    return get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0]


def hash_password(password):
    return generate_password_hash(password, method="pbkdf2:sha256", salt_length=16)


def csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf():
    token = request.form.get("csrf_token")
    if not token or not secrets.compare_digest(token, csrf_token()):
        abort(400, "Invalid CSRF token")


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# --- 登录限流（内存级，防暴力破解）---
LOGIN_MAX_FAILS = 5
LOGIN_WINDOW = 900  # 15 分钟
_login_fails = {}


def client_ip():
    """取真实客户端 IP（在 Caddy/nginx 反代后用 X-Forwarded-For 首段）。"""
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"


def login_lock_remaining(ip):
    """返回该 IP 还需冷却的秒数；0 表示未锁定。"""
    import time

    now = time.time()
    fails = [t for t in _login_fails.get(ip, []) if now - t < LOGIN_WINDOW]
    _login_fails[ip] = fails
    if len(fails) >= LOGIN_MAX_FAILS:
        return int(LOGIN_WINDOW - (now - fails[0]))
    return 0


def record_login_fail(ip):
    import time

    _login_fails.setdefault(ip, []).append(time.time())


def clear_login_fails(ip):
    _login_fails.pop(ip, None)


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(value):
    return bool(EMAIL_RE.match(value or ""))


def mask_email(email):
    """把邮箱打码用于提示，例如 ab***@gmail.com。"""
    try:
        local, domain = email.split("@", 1)
    except ValueError:
        return email
    if len(local) <= 2:
        masked = local[0] + "*"
    else:
        masked = local[:2] + "*" * max(1, len(local) - 2)
    return f"{masked}@{domain}"


def _keystream(length, salt):
    """基于 SECRET_KEY 派生的伪随机字节流，用于对授权码做对称加密。"""
    key = app.config["SECRET_KEY"].encode()
    out = b""
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(key + salt + counter.to_bytes(4, "big")).digest()
        counter += 1
    return out[:length]


def encrypt_secret(plaintext):
    """用 SECRET_KEY 加密授权码后存库（避免在 SQLite 里明文存储）。"""
    if not plaintext:
        return ""
    data = plaintext.encode()
    salt = secrets.token_bytes(8)
    ks = _keystream(len(data), salt)
    cipher = bytes(a ^ b for a, b in zip(data, ks))
    return base64.b64encode(salt + cipher).decode()


def decrypt_secret(token):
    if not token:
        return ""
    try:
        raw = base64.b64decode(token)
        salt, cipher = raw[:8], raw[8:]
        ks = _keystream(len(cipher), salt)
        return bytes(a ^ b for a, b in zip(cipher, ks)).decode()
    except Exception:
        return ""


def get_settings():
    return get_db().execute("SELECT * FROM settings WHERE id = 1").fetchone()


def smtp_config():
    """合并数据库配置（优先）与环境变量（兜底），返回可用的 SMTP 参数。"""
    row = get_settings()
    host = (row["smtp_host"] if row else "") or os.environ.get("SMTP_HOST", "")
    username = (row["smtp_username"] if row else "") or os.environ.get("SMTP_USERNAME", "")
    password = decrypt_secret(row["smtp_password"]) if row and row["smtp_password"] else os.environ.get("SMTP_PASSWORD", "")
    port = (row["smtp_port"] if row and row["smtp_port"] else None) or int(os.environ.get("SMTP_PORT") or 465)
    recipient = (row["recipient"] if row else "") or username
    return {
        "host": host,
        "port": int(port),
        "username": username,
        "password": password,
        "sender": username or os.environ.get("SMTP_FROM", ""),
        "recipient": recipient,
    }


def smtp_configured():
    cfg = smtp_config()
    return bool(cfg["host"] and cfg["username"] and cfg["password"])


def send_email(to_addr, subject, body):
    """用当前 SMTP 配置发送一封邮件。465 走隐式 SSL，其余走 STARTTLS。"""
    cfg = smtp_config()
    if not (cfg["host"] and cfg["username"] and cfg["password"]):
        raise RuntimeError("SMTP 未配置")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["sender"] or cfg["username"]
    msg["To"] = to_addr
    msg.set_content(body)
    if cfg["port"] == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=15, context=context) as server:
            server.login(cfg["username"], cfg["password"])
            server.send_message(msg)
    else:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as server:
            server.ehlo()
            if server.has_extn("starttls"):
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            server.login(cfg["username"], cfg["password"])
            server.send_message(msg)


def send_login_code(email, code):
    send_email(
        email,
        "SIMHUB Web 登录验证码",
        f"你的 SIMHUB Web 登录验证码是：{code}\n\n"
        "验证码 5 分钟内有效。如果不是你本人在登录，请忽略本邮件并尽快修改密码。",
    )


def run_due_reminders():
    """每天最多跑一次：扫描临近到期的卡片，给每张未发过的卡片寄一封提醒。"""
    row = get_settings()
    if not row or not row["reminder_enabled"] or not smtp_configured():
        return
    today = date.today().isoformat()
    if row["last_reminder_date"] == today:
        return
    get_db().execute("UPDATE settings SET last_reminder_date = ? WHERE id = 1", (today,))
    get_db().commit()
    cfg = smtp_config()
    recipient = cfg["recipient"]
    if not recipient:
        return
    days_before = max(int(row["reminder_days_before"] or 3), 0)
    for card in load_cards({}):
        if card.get("isLongTerm"):
            continue
        left = days_left(card)
        if left is None or left < 0 or left > days_before:
            continue
        already = get_db().execute(
            "SELECT 1 FROM reminder_log WHERE card_id = ? AND sent_date = ?",
            (card["id"], today),
        ).fetchone()
        if already:
            continue
        name = card.get("carrier") or "未命名卡片"
        expiry = (card.get("expiryDate") or "")[:10]
        try:
            send_email(
                recipient,
                f"SIMHUB 到期提醒：{name} 还有 {left} 天",
                f"卡片「{name}」（{card.get('countryName','')} {card.get('plan','')}）"
                f"将于 {expiry} 到期，剩余 {left} 天，请及时续期保号。",
            )
        except Exception:
            continue
        get_db().execute(
            "INSERT OR IGNORE INTO reminder_log (card_id, sent_date) VALUES (?, ?)",
            (card["id"], today),
        )
    get_db().commit()


def parse_iso(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        text += "T00:00:00Z"
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_datetime(value, fallback=None):
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif isinstance(value, datetime):
        value = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        value = parse_iso(value) or fallback or datetime.now(timezone.utc)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def date_input(value):
    parsed = parse_iso(value)
    return parsed.date().isoformat() if parsed else ""


def days_left(card):
    parsed = parse_iso(card.get("expiryDate"))
    if not parsed:
        return None
    return (parsed.date() - date.today()).days


def due_badge(card):
    if card.get("isLongTerm"):
        return {"key": "long", "label": "长期保号"}
    days = days_left(card)
    if days is None:
        return {"key": "unknown", "label": "未设置"}
    if days < 0:
        return {"key": "overdue", "label": f"过期 {abs(days)} 天"}
    if days <= 7:
        return {"key": "urgent", "label": f"{days} 天内"}
    if days <= 30:
        return {"key": "soon", "label": f"{days} 天后"}
    return {"key": "ok", "label": f"{days} 天后"}


def normalize_tags(value):
    if isinstance(value, str):
        raw = re.split(r"[,，;；\n]", value)
    elif isinstance(value, list):
        raw = value
    else:
        raw = []
    seen = set()
    tags = []
    for item in raw:
        tag = str(item).strip()
        key = tag.lower()
        if tag and key not in seen:
            seen.add(key)
            tags.append(tag)
    return tags


def default_dto():
    now = datetime.now(timezone.utc)
    expiry = now + timedelta(days=30)
    return normalize_dto(
        {
            "carrier": "",
            "plan": "",
            "phoneNumber": "",
            "countryCode": "",
            "countryName": "",
            "flag": "🌐",
            "activationDate": iso_datetime(now),
            "expiryDate": iso_datetime(expiry),
            "price": "",
            "currencyCode": "USD",
            "tags": [],
            "renewDays": 30,
            "renewalUnit": "days",
            "renewalIntervalValue": 30,
        }
    )


def normalize_dto(data, existing=None):
    base = dict(existing or default_dto_raw())
    base.update(data or {})

    activation = iso_datetime(base.get("activationDate"))
    expiry_fallback = (parse_iso(activation) or datetime.now(timezone.utc)) + timedelta(days=30)
    expiry = iso_datetime(base.get("expiryDate"), fallback=expiry_fallback)
    renew_days = parse_int(base.get("renewDays"), inferred_days(activation, expiry))

    dto = {
        "id": str(base.get("id") or ""),
        "carrier": str(base.get("carrier") or "").strip(),
        "plan": str(base.get("plan") or "").strip(),
        "phoneNumber": str(base.get("phoneNumber") or "").strip(),
        "countryCode": str(base.get("countryCode") or "").strip().upper(),
        "countryName": str(base.get("countryName") or "").strip(),
        "flag": str(base.get("flag") or "🌐").strip() or "🌐",
        "cardBackgroundAssetName": blank_none(base.get("cardBackgroundAssetName")),
        "cardColorHex": blank_none(base.get("cardColorHex")),
        "cardBackgroundImageData": blank_none(base.get("cardBackgroundImageData")),
        "carrierAppIconURLString": blank_none(base.get("carrierAppIconURLString")),
        "carrierAppStoreURLString": blank_none(base.get("carrierAppStoreURLString")),
        "carrierAppName": blank_none(base.get("carrierAppName")),
        "activationDate": activation,
        "expiryDate": expiry,
        "price": str(base.get("price") or "").strip(),
        "currencyCode": blank_none(str(base.get("currencyCode") or "").strip().upper()),
        "cyclePaymentMinorUnits": parse_optional_int(base.get("cyclePaymentMinorUnits")),
        "currentBalanceMinorUnits": parse_optional_int(base.get("currentBalanceMinorUnits")),
        "websiteURL": blank_none(base.get("websiteURL")),
        "currentBalance": blank_none(base.get("currentBalance")),
        "transactionNotes": blank_none(base.get("transactionNotes")),
        "customPrompt": blank_none(base.get("customPrompt")),
        "tags": normalize_tags(base.get("tags")),
        "orderIndex": parse_int(base.get("orderIndex"), 0),
        "smdpAddress": str(base.get("smdpAddress") or "").strip(),
        "activationCode": str(base.get("activationCode") or "").strip(),
        "confirmationCode": blank_none(base.get("confirmationCode")),
        "eid": str(base.get("eid") or "").strip(),
        "createdAt": iso_datetime(base.get("createdAt")),
        "updatedAt": iso_datetime(base.get("updatedAt") or now_iso()),
        "isLongTerm": parse_bool(base.get("isLongTerm")),
        "renewDays": renew_days,
        "renewalUnit": blank_none(base.get("renewalUnit")) or "days",
        "renewalIntervalValue": parse_optional_int(base.get("renewalIntervalValue")) or renew_days,
    }
    fill_country_assets(dto)
    return dto


def fill_country_assets(dto):
    """JSON 兼容：按国家代码 ↔ 国旗 ↔ 名称 ↔ 卡片背景互相补全。"""
    code = dto.get("countryCode") or ""
    flag = dto.get("flag") or ""
    if not code and flag and flag != "🌐":
        code = code_from_flag(flag)
        if code:
            dto["countryCode"] = code
    if code:
        if not dto.get("flag") or dto["flag"] == "🌐":
            dto["flag"] = flag_from_code(code)
        if not dto.get("countryName") and code in NAME_BY_CODE:
            dto["countryName"] = NAME_BY_CODE[code]
        if not dto.get("cardBackgroundAssetName") and code in CODE_TO_ASSET:
            dto["cardBackgroundAssetName"] = CODE_TO_ASSET[code]
    return dto


def default_dto_raw():
    now = now_iso()
    expiry = iso_datetime(datetime.now(timezone.utc) + timedelta(days=30))
    return {
        "id": "",
        "carrier": "",
        "plan": "",
        "phoneNumber": "",
        "countryCode": "",
        "countryName": "",
        "flag": "🌐",
        "activationDate": now,
        "expiryDate": expiry,
        "price": "",
        "currencyCode": "USD",
        "tags": [],
        "orderIndex": 0,
        "smdpAddress": "",
        "activationCode": "",
        "eid": "",
        "createdAt": now,
        "updatedAt": now,
        "isLongTerm": False,
        "renewDays": 30,
        "renewalUnit": "days",
        "renewalIntervalValue": 30,
    }


def form_dto(existing=None):
    tags = request.form.get("tags", "")
    data = {
        "carrier": request.form.get("carrier", ""),
        "plan": request.form.get("plan", ""),
        "phoneNumber": request.form.get("phoneNumber", ""),
        "countryCode": request.form.get("countryCode", ""),
        "countryName": request.form.get("countryName", ""),
        "flag": request.form.get("flag", "🌐"),
        "carrierAppIconURLString": request.form.get("carrierAppIconURLString", ""),
        "carrierAppStoreURLString": request.form.get("carrierAppStoreURLString", ""),
        "carrierAppName": request.form.get("carrierAppName", ""),
        "activationDate": request.form.get("activationDate", ""),
        "expiryDate": request.form.get("expiryDate", ""),
        "price": request.form.get("price", ""),
        "currencyCode": request.form.get("currencyCode", ""),
        "cyclePaymentMinorUnits": request.form.get("cyclePaymentMinorUnits", ""),
        "currentBalanceMinorUnits": request.form.get("currentBalanceMinorUnits", ""),
        "websiteURL": request.form.get("websiteURL", ""),
        "currentBalance": request.form.get("currentBalance", ""),
        "transactionNotes": request.form.get("transactionNotes", ""),
        "customPrompt": request.form.get("customPrompt", ""),
        "tags": tags,
        "smdpAddress": request.form.get("smdpAddress", ""),
        "activationCode": request.form.get("activationCode", ""),
        "confirmationCode": request.form.get("confirmationCode", ""),
        "eid": request.form.get("eid", ""),
        "isLongTerm": request.form.get("isLongTerm") == "on",
        "renewDays": request.form.get("renewDays", ""),
        "renewalUnit": request.form.get("renewalUnit", "days"),
        "renewalIntervalValue": request.form.get("renewalIntervalValue", ""),
    }
    dto = normalize_dto(data, existing=existing)
    errors = []
    if not dto["carrier"]:
        errors.append("运营商名称不能为空。")
    digits = "".join(ch for ch in dto["phoneNumber"] if ch.isdigit())
    if dto["phoneNumber"] and len(digits) < 4:
        errors.append("电话号码至少需要 4 位数字。")
    return dto, errors


def row_to_dto(row):
    dto = {}
    for key in DTO_FIELDS:
        if key == "tags":
            try:
                dto[key] = json.loads(row["tags_json"] or "[]")
            except json.JSONDecodeError:
                dto[key] = []
            continue
        column = DTO_TO_COL.get(key)
        value = row[column] if column else None
        if key == "isLongTerm":
            value = bool(value)
        dto[key] = value
    return dto


def dto_values(dto):
    return [
        dto["id"],
        dto["carrier"],
        dto["plan"],
        dto["phoneNumber"],
        dto["countryCode"],
        dto["countryName"],
        dto["flag"],
        dto.get("cardBackgroundAssetName"),
        dto.get("cardColorHex"),
        dto.get("cardBackgroundImageData"),
        dto.get("carrierAppIconURLString"),
        dto.get("carrierAppStoreURLString"),
        dto.get("carrierAppName"),
        dto["activationDate"],
        dto["expiryDate"],
        dto["price"],
        dto.get("currencyCode"),
        dto.get("cyclePaymentMinorUnits"),
        dto.get("currentBalanceMinorUnits"),
        dto.get("websiteURL"),
        dto.get("currentBalance"),
        dto.get("transactionNotes"),
        dto.get("customPrompt"),
        json.dumps(dto.get("tags") or [], ensure_ascii=False),
        dto.get("orderIndex") or 0,
        dto["smdpAddress"],
        dto["activationCode"],
        dto.get("confirmationCode"),
        dto["eid"],
        dto["createdAt"],
        dto["updatedAt"],
        1 if dto.get("isLongTerm") else 0,
        dto.get("renewDays") or 30,
        dto.get("renewalUnit"),
        dto.get("renewalIntervalValue"),
    ]


def insert_card(dto):
    get_db().execute(
        """
        INSERT INTO cards (
            id, carrier, plan, phone_number, country_code, country_name, flag,
            card_background_asset_name, card_color_hex, card_background_image_data,
            carrier_app_icon_url_string, carrier_app_store_url_string, carrier_app_name,
            activation_date, expiry_date, price, currency_code, cycle_payment_minor_units,
            current_balance_minor_units, website_url, current_balance, transaction_notes,
            custom_prompt, tags_json, order_index, smdp_address, activation_code,
            confirmation_code, eid, created_at, updated_at, is_long_term, renew_days,
            renewal_unit, renewal_interval_value
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        dto_values(dto),
    )


def update_card(card_id, dto):
    dto["updatedAt"] = now_iso()
    values = dto_values(dto)[1:] + [card_id]
    get_db().execute(
        """
        UPDATE cards
           SET carrier = ?, plan = ?, phone_number = ?, country_code = ?, country_name = ?, flag = ?,
               card_background_asset_name = ?, card_color_hex = ?, card_background_image_data = ?,
               carrier_app_icon_url_string = ?, carrier_app_store_url_string = ?, carrier_app_name = ?,
               activation_date = ?, expiry_date = ?, price = ?, currency_code = ?, cycle_payment_minor_units = ?,
               current_balance_minor_units = ?, website_url = ?, current_balance = ?, transaction_notes = ?,
               custom_prompt = ?, tags_json = ?, order_index = ?, smdp_address = ?, activation_code = ?,
               confirmation_code = ?, eid = ?, created_at = ?, updated_at = ?, is_long_term = ?,
               renew_days = ?, renewal_unit = ?, renewal_interval_value = ?
         WHERE id = ?
        """,
        values,
    )


def get_card(card_id):
    row = get_db().execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    if not row:
        abort(404)
    return row_to_dto(row)


def load_cards(filters):
    where = []
    args = []
    q = filters.get("q")
    if q:
        where.append(
            "(carrier LIKE ? OR plan LIKE ? OR phone_number LIKE ? OR country_name LIKE ? OR eid LIKE ? OR smdp_address LIKE ?)"
        )
        like = f"%{q}%"
        args.extend([like, like, like, like, like, like])
    country = filters.get("country")
    if country:
        where.append("country_name = ?")
        args.append(country)

    sql = "SELECT * FROM cards"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY order_index ASC, expiry_date ASC"
    cards = [row_to_dto(row) for row in get_db().execute(sql, args).fetchall()]

    due = filters.get("due")
    if due:
        cards = [card for card in cards if due_badge(card)["key"] == due]
    tag = filters.get("tag")
    if tag:
        cards = [card for card in cards if tag in card.get("tags", [])]
    return cards


def next_order_index():
    return (get_db().execute("SELECT MAX(order_index) FROM cards").fetchone()[0] or -1) + 1


def card_exists(card_id):
    return bool(get_db().execute("SELECT 1 FROM cards WHERE id = ?", (card_id,)).fetchone())


def duplicate_card(dto):
    phone = dto.get("phoneNumber", "").strip()
    eid = dto.get("eid", "").strip()
    activation = dto.get("activationCode", "").strip()
    smdp = dto.get("smdpAddress", "").strip()
    if phone:
        if get_db().execute("SELECT 1 FROM cards WHERE phone_number = ?", (phone,)).fetchone():
            return True
    if eid:
        if get_db().execute("SELECT 1 FROM cards WHERE eid = ?", (eid,)).fetchone():
            return True
    if activation and smdp:
        if get_db().execute(
            "SELECT 1 FROM cards WHERE activation_code = ? AND smdp_address = ?",
            (activation, smdp),
        ).fetchone():
            return True
    return False


def calculate_stats(cards):
    badges = [due_badge(card) for card in cards]
    return {
        "total": len(cards),
        "overdue": sum(1 for item in badges if item["key"] == "overdue"),
        "urgent": sum(1 for item in badges if item["key"] == "urgent"),
        "soon": sum(1 for item in badges if item["key"] == "soon"),
        "long": sum(1 for item in badges if item["key"] == "long"),
        "monthly_fee": sum(price_number(card.get("price")) for card in cards),
        "countries": len({card.get("countryName") for card in cards if card.get("countryName")}),
    }


def price_number(value):
    if not value:
        return 0.0
    match = re.search(r"-?\d+(?:[.,]\d+)?", str(value).replace(",", "."))
    return float(match.group(0)) if match else 0.0


def parse_int(value, default):
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return default


def parse_optional_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return str(value).lower() in {"1", "true", "yes", "on"}


def blank_none(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def inferred_days(start_iso, end_iso):
    start = parse_iso(start_iso)
    end = parse_iso(end_iso)
    if not start or not end:
        return 30
    return max((end.date() - start.date()).days, 1)


def api_envelope(success, data=None, message=None, code=None):
    return {"success": success, "data": data, "message": message, "code": code}


def api_ok(data, status=200):
    return jsonify(api_envelope(True, data, None, None)), status


def api_fail(message, code, status):
    return jsonify(api_envelope(False, None, message, code)), status


def export_cards_response(cards):
    body = json.dumps(cards, ensure_ascii=False, indent=2, sort_keys=True)
    return Response(
        body,
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=simhub-export.json"},
    )


def log_activity(card_id, action, note, label=""):
    get_db().execute(
        "INSERT INTO activity_log (card_id, card_label, action, note) VALUES (?, ?, ?, ?)",
        (card_id or "", label or "", action, note),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=True)
