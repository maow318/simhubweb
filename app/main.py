import base64
import csv
import hmac
import hashlib
import ipaddress
import io
import json
import os
import re
import secrets
import smtplib
import socket
import sqlite3
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps

from cryptography.fernet import Fernet, InvalidToken

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


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


PLACEHOLDER_SECRET_PREFIXES = (
    "change-this",
    "changeme",
    "please-change",
    "replace-me",
    "your-",
    "example",
)
ENCRYPTED_PREFIX = "enc:v1:"
CARD_SECRET_FIELDS = {"smdpAddress", "activationCode", "confirmationCode", "eid"}
MAX_CONTENT_LENGTH = env_int("MAX_CONTENT_LENGTH", 8 * 1024 * 1024)
MAX_IMPORT_CARDS = env_int("MAX_IMPORT_CARDS", 1000)
MAX_BACKGROUND_IMAGE_CHARS = env_int("MAX_BACKGROUND_IMAGE_CHARS", 1_500_000)
CARD_TEXT_LIMITS = {
    "id": 128,
    "carrier": 160,
    "plan": 200,
    "category": 80,
    "phoneNumber": 80,
    "countryCode": 8,
    "countryName": 120,
    "flag": 16,
    "cardBackgroundAssetName": 120,
    "cardColorHex": 32,
    "cardBackgroundImageData": MAX_BACKGROUND_IMAGE_CHARS,
    "carrierAppIconURLString": 600,
    "carrierAppStoreURLString": 600,
    "carrierAppName": 180,
    "activationDate": 80,
    "expiryDate": 80,
    "price": 120,
    "currencyCode": 12,
    "websiteURL": 600,
    "currentBalance": 120,
    "transactionNotes": 4000,
    "customPrompt": 4000,
    "smdpAddress": 300,
    "activationCode": 500,
    "confirmationCode": 300,
    "eid": 80,
    "createdAt": 80,
    "updatedAt": 80,
    "operationDate": 80,
    "operationNote": 1000,
    "renewalUnit": 40,
}

DTO_FIELDS = [
    "id",
    "carrier",
    "plan",
    "category",
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
    "reminderMode",
    "reminderDaysBefore",
    "operationReminderEnabled",
    "operationDate",
    "operationDaysBeforeExpiry",
    "operationNote",
    "renewDays",
    "renewalUnit",
    "renewalIntervalValue",
]

DTO_TO_COL = {
    "id": "id",
    "carrier": "carrier",
    "plan": "plan",
    "category": "category",
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
    "reminderMode": "reminder_mode",
    "reminderDaysBefore": "reminder_days_before",
    "operationReminderEnabled": "operation_reminder_enabled",
    "operationDate": "operation_date",
    "operationDaysBeforeExpiry": "operation_days_before_expiry",
    "operationNote": "operation_note",
    "renewDays": "renew_days",
    "renewalUnit": "renewal_unit",
    "renewalIntervalValue": "renewal_interval_value",
}

OPTIONAL_FIELDS = {
    "cardBackgroundAssetName",
    "cardColorHex",
    "cardBackgroundImageData",
    "category",
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
    "reminderMode",
    "reminderDaysBefore",
    "operationDate",
    "operationDaysBeforeExpiry",
    "operationNote",
    "renewalUnit",
    "renewalIntervalValue",
}


def production_mode_enabled():
    return (
        env_bool("SIMHUB_PRODUCTION", False)
        or env_bool("SESSION_COOKIE_SECURE", False)
        or env_bool("ENABLE_HSTS", False)
    )


def secret_is_weak(value):
    text = str(value or "").strip()
    lowered = text.lower()
    if len(text) < 32:
        return True
    if any(lowered.startswith(prefix) for prefix in PLACEHOLDER_SECRET_PREFIXES):
        return True
    if len(set(text)) < 8:
        return True
    return False


def require_strong_secret(name, value):
    if secret_is_weak(value):
        raise RuntimeError(f"{name} 必须在生产环境设置为固定、随机、至少 32 字符的强密钥")


def public_base_url_from_env():
    value = (os.environ.get("PUBLIC_BASE_URL") or "").strip()
    domain = (os.environ.get("SIMHUB_DOMAIN") or "").strip()
    if not value and domain and production_mode_enabled():
        value = "https://" + domain
    if not value:
        return ""
    value = value.rstrip("/")
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise RuntimeError("PUBLIC_BASE_URL 必须是 http(s):// 开头的完整公网地址")
    return value


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
    production = production_mode_enabled()
    secret_key = (os.environ.get("SECRET_KEY") or "").strip()
    data_encryption_key = (os.environ.get("DATA_ENCRYPTION_KEY") or "").strip()
    if production:
        require_strong_secret("SECRET_KEY", secret_key)
        require_strong_secret("DATA_ENCRYPTION_KEY", data_encryption_key)
    if not secret_key:
        secret_key = secrets.token_urlsafe(48)
    if not data_encryption_key:
        data_encryption_key = secret_key
    app.config["SECRET_KEY"] = secret_key
    app.config["DATA_ENCRYPTION_KEY"] = data_encryption_key
    app.config["DATABASE"] = os.environ.get("DATABASE") or os.path.join(BASE_DIR, "..", "data", "simhub.sqlite")
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    app.config["SESSION_COOKIE_SECURE"] = env_bool("SESSION_COOKIE_SECURE", False)
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=env_int("SESSION_DAYS", 7))
    app.config["ENABLE_HSTS"] = env_bool("ENABLE_HSTS", False)
    app.config["SIMHUB_PRODUCTION"] = production
    app.config["PUBLIC_BASE_URL"] = public_base_url_from_env()
    # 仅当部署在可信反代后（由它覆盖 X-Forwarded-For）时才信任转发头取客户端 IP
    app.config["TRUST_PROXY"] = (os.environ.get("TRUST_PROXY", "") or "").lower() in ("1", "true", "yes", "on")

    @app.after_request
    def add_security_headers(response):
        nonce = getattr(g, "csp_nonce", "")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(self), geolocation=(), microphone=(), payment=(), usb=(), serial=(), bluetooth=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https://*.mzstatic.com; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "media-src 'self' blob:; "
            "worker-src 'self'; "
            "frame-src 'none'; "
            "object-src 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "frame-ancestors 'self'",
        )
        if app.config.get("ENABLE_HSTS"):
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.before_request
    def before_request():
        g.csp_nonce = secrets.token_urlsafe(16)
        init_db()
        g.user = current_user()
        public_endpoints = {
            "setup", "login", "login_code", "static", "api_status", "manifest", "service_worker",
            "telegram_webhook",
        }
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
            "csp_nonce": csp_nonce,
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
                method = (settings_row["twofa_method"] if settings_row else "email") or "email"
                channel_ok = tg_configured() if method == "telegram" else smtp_configured()
                two_fa = bool(settings_row and settings_row["twofa_enabled"] and channel_ok)
                if two_fa:
                    code = f"{secrets.randbelow(1000000):06d}"
                    try:
                        if method == "telegram":
                            tg_send(f"SIMHUB 登录验证码：{code}\n5 分钟内有效。非本人操作请忽略。")
                            target = "Telegram"
                        else:
                            send_login_code(smtp_config()["recipient"], code)
                            target = mask_email(smtp_config()["recipient"])
                    except Exception:
                        flash("验证码发送失败，请检查验证方式配置。", "error")
                        return render_template("login.html")
                    session.clear()
                    session["csrf_token"] = secrets.token_urlsafe(32)
                    session["pending_login"] = {
                        "uid": user["id"],
                        "code_hash": hash_password(code),
                        "expires": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
                        "email": target,
                        "tries": 0,
                    }
                    flash(f"验证码已发送到 {target}。", "success")
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
        # 到期提醒在首页访问时顺带触发（无后台调度时的兜底）。
        # 不再静默吞异常——失败会记进日志，便于排查；建议另配 cron 定时触发（见 README）。
        try:
            run_due_reminders()
        except Exception:
            app.logger.exception("run_due_reminders failed on dashboard visit")
        return Response(render_spa(), mimetype="text/html; charset=utf-8")

    @app.route("/simhub")
    @app.route("/simhub/")
    def legacy_simhub():
        return redirect(url_for("dashboard"))

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
        renew_days = max(parse_int(card.get("renewDays"), 30), 1)
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
            "category",
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
        device_name = os.environ.get("SIMHUB_DEVICE_NAME", "SimHub Keeper Linux")
        # 未登录时不泄露真实卡片数量与数据版本
        if not g.user:
            return api_ok({"deviceName": device_name, "connectedDevices": 0})
        cards = load_cards({})
        updated = max((parse_iso(c.get("updatedAt")) or datetime.fromtimestamp(0, tz=timezone.utc) for c in cards), default=datetime.fromtimestamp(0, tz=timezone.utc))
        return api_ok(
            {
                "deviceName": device_name,
                "connectedDevices": 1,
                "dataVersion": updated.timestamp(),
                "cardCount": len(cards),
            }
        )

    @app.route("/api/docs")
    @login_required
    def api_docs():
        return api_ok(
            {
                "name": "SIMHUB Web API",
                "version": "1",
                "auth": {
                    "type": "session",
                    "csrfHeader": "X-CSRF-Token",
                    "notes": "登录后由 SPA 自动携带 CSRF；所有写操作需要 application/json。",
                },
                "resources": [
                    {
                        "name": "Cards",
                        "fields": DTO_FIELDS,
                        "endpoints": [
                            {"method": "GET", "path": "/api/cards", "description": "列出全部卡片"},
                            {"method": "POST", "path": "/api/cards", "description": "新建卡片"},
                            {"method": "GET", "path": "/api/cards/<id>", "description": "读取单张卡片"},
                            {"method": "PUT", "path": "/api/cards/<id>", "description": "更新单张卡片"},
                            {"method": "DELETE", "path": "/api/cards/<id>", "description": "删除单张卡片"},
                            {"method": "POST", "path": "/api/cards/batch-update", "description": "批量删除或批量打标签"},
                        ],
                    },
                    {
                        "name": "Import / Export",
                        "endpoints": [
                            {"method": "GET", "path": "/api/export", "description": "导出兼容 App 的 JSON"},
                            {"method": "POST", "path": "/api/import", "description": "预览或提交导入 JSON"},
                            {"method": "POST", "path": "/api/lpa/parse", "description": "解析 LPA 字符串"},
                        ],
                    },
                    {
                        "name": "Notifications",
                        "endpoints": [
                            {"method": "GET", "path": "/api/reminders/status", "description": "查看后台提醒扫描状态"},
                            {"method": "POST", "path": "/api/reminders/scan", "description": "立即扫描并发送匹配提醒"},
                            {"method": "GET/POST", "path": "/api/smtp", "description": "邮件与登录二次验证配置"},
                            {"method": "GET/POST", "path": "/api/tg", "description": "Telegram 通知配置"},
                            {"method": "GET/POST", "path": "/api/webhook", "description": "Webhook 通知配置"},
                        ],
                    },
                ],
            }
        )

    @app.route("/api/cards", methods=["GET", "POST"])
    @login_required
    def api_cards():
        if request.method == "GET":
            return api_ok(load_cards({}))
        err = api_guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        limit_error = validate_card_field_limits([body])
        if limit_error:
            return api_fail(limit_error, "FIELD_TOO_LARGE", 413)
        dto = normalize_dto(body)
        if not dto.get("carrier"):
            return api_fail("运营商名称不能为空", "CARRIER_REQUIRED", 400)
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
            err = api_guard(need_json=False)
            if err:
                return err
            get_db().execute("DELETE FROM cards WHERE id = ?", (card_id,))
            log_activity(card_id, "delete", "删除卡片", label=card.get("carrier") or "未命名")
            get_db().commit()
            return api_ok({"deleted": True})

        err = api_guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        limit_error = validate_card_field_limits([body])
        if limit_error:
            return api_fail(limit_error, "FIELD_TOO_LARGE", 413)
        client_seen = body.get("updatedAt")
        if client_seen and card.get("updatedAt"):
            client_seen_at = parse_iso(client_seen)
            server_seen_at = parse_iso(card.get("updatedAt"))
            if not client_seen_at or not server_seen_at or client_seen_at != server_seen_at:
                return api_fail("卡片已被其他页面修改，请刷新后重试", "CONFLICT", 409)
        dto = normalize_dto(body, existing=card)
        if not dto.get("carrier"):
            return api_fail("运营商名称不能为空", "CARRIER_REQUIRED", 400)
        dto["id"] = card_id
        update_card(card_id, dto)
        log_activity(card_id, "edit", "编辑卡片", label=dto.get("carrier") or "未命名")
        get_db().commit()
        return api_ok(get_card(card_id))

    @app.route("/api/cards/batch-update", methods=["POST"])
    @login_required
    def api_batch_update():
        err = api_guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        raw_ids = body.get("ids", [])
        if not isinstance(raw_ids, list):
            return api_fail("ids 必须是数组", "BAD_REQUEST", 400)
        ids = [item for item in raw_ids if isinstance(item, str)]
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
            if not tags:
                return api_fail("标签不能为空", "BAD_REQUEST", 400)
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

    @app.route("/api/lpa/parse", methods=["POST"])
    @login_required
    def api_lpa_parse():
        err = api_guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        result = parse_lpa_payload(body.get("value") or body.get("lpa") or "")
        if not result:
            return api_fail("LPA 格式不正确，应类似 LPA:1$smdp.example.com$MATCHINGID；只有 SM-DP+ 时也支持 LPA:1$smdp.example.com$", "BAD_LPA", 400)
        return api_ok(result)

    @app.route("/api/export")
    @login_required
    def api_export():
        return export_cards_response(load_cards({}))

    @app.route("/api/import", methods=["POST"])
    @login_required
    def api_import():
        err = api_guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        raw_cards = body.get("cards", [])
        if not isinstance(raw_cards, list):
            return api_fail("导入 payload 必须是卡片数组", "BAD_REQUEST", 400)
        if len(raw_cards) > MAX_IMPORT_CARDS:
            return api_fail(f"一次最多导入 {MAX_IMPORT_CARDS} 张卡片", "TOO_MANY_CARDS", 413)
        limit_error = validate_card_field_limits(raw_cards)
        if limit_error:
            return api_fail(limit_error, "FIELD_TOO_LARGE", 413)
        dtos = [normalize_dto(item) for item in raw_cards if isinstance(item, dict)]
        if body.get("mode") != "commit":
            return api_ok(import_preview(raw_cards, dtos))

        imported = 0
        skipped = 0
        for dto in dtos:
            if not dto.get("carrier"):
                skipped += 1
                continue
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

    @app.route("/api/activity", methods=["DELETE"])
    @login_required
    def api_activity_clear():
        err = api_guard(need_json=False)
        if err:
            return err
        cur = get_db().execute("DELETE FROM activity_log")
        get_db().commit()
        return api_ok({"cleared": max(cur.rowcount, 0)})

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
                    "icon": safe_app_icon_url(item.get("artworkUrl512") or item.get("artworkUrl100") or "") or "",
                    "url": safe_optional_http_url(item.get("trackViewUrl", "")) or "",
                    "seller": item.get("sellerName", ""),
                }
            )
        return api_ok(results)

    @app.route("/api/account")
    @login_required
    def api_account_get():
        return api_ok({"username": g.user["username"]})

    @app.route("/api/account", methods=["POST"])
    @login_required
    def api_account_save():
        err = api_guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        username = text_field(body, "username")
        current = text_field(body, "current", strip=False)
        if username is None or current is None:
            return api_fail("账户字段必须是字符串", "BAD_BODY", 400)
        if not valid_username(username):
            return api_fail("用户名需为 1-32 位，且不能包含空白字符", "BAD_USERNAME", 400)
        row = get_db().execute(
            "SELECT id, password_hash FROM users WHERE id = ?", (g.user["id"],)
        ).fetchone()
        if not row or not check_password_hash(row["password_hash"], current):
            return api_fail("当前密码不正确", "BAD_PASSWORD", 400)
        taken = get_db().execute(
            "SELECT 1 FROM users WHERE username = ? AND id <> ?",
            (username, g.user["id"]),
        ).fetchone()
        if taken:
            return api_fail("这个用户名已被占用", "USERNAME_TAKEN", 409)
        try:
            get_db().execute(
                "UPDATE users SET username = ? WHERE id = ?",
                (username, g.user["id"]),
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            return api_fail("这个用户名已被占用", "USERNAME_TAKEN", 409)
        return api_ok({"username": username})

    @app.route("/api/password", methods=["POST"])
    @login_required
    def api_password():
        err = api_guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        current = text_field(body, "current", strip=False)
        new_password = text_field(body, "new", strip=False)
        if current is None or new_password is None:
            return api_fail("密码字段必须是字符串", "BAD_BODY", 400)
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
                "port": parse_port(row["smtp_port"], 465) or 465,
                "username": row["smtp_username"],
                "hasPassword": bool(row["smtp_password"]),
                "recipient": row["recipient"],
                "twofaEnabled": bool(row["twofa_enabled"]),
                "twofaMethod": row["twofa_method"] or "email",
                "reminderEnabled": bool(row["reminder_enabled"]),
                "reminderDaysBefore": row["reminder_days_before"],
                "ready": smtp_configured(),
                "tgReady": tg_configured(),
            }
        )

    @app.route("/api/smtp", methods=["POST"])
    @login_required
    def api_smtp_save():
        err = api_guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        host = text_field(body, "host")
        username = text_field(body, "username")
        recipient = text_field(body, "recipient")
        method_in = text_field(body, "twofaMethod", "email")
        password = optional_text_field(body, "password")
        if None in (host, username, recipient, method_in) or password is None:
            return api_fail("SMTP 配置字段格式不正确", "BAD_BODY", 400)
        port = parse_port(body.get("port"), 465)
        if port is None:
            return api_fail("端口必须是 1-65535 的数字", "BAD_PORT", 400)
        if username and not valid_email(username):
            return api_fail("发信邮箱格式不正确", "BAD_EMAIL", 400)
        if recipient and not valid_email(recipient):
            return api_fail("收件邮箱格式不正确", "BAD_EMAIL", 400)
        reminder_days = parse_nonnegative_int_field(body.get("reminderDaysBefore"), 3)
        if reminder_days is None:
            return api_fail("提前提醒天数必须是数字", "BAD_DAYS", 400)
        row = get_settings()
        # 密码留空表示不修改；传入新值则加密保存
        if password is None or password == "":
            enc = row["smtp_password"]
        else:
            enc = encrypt_secret(password)
        method = "telegram" if method_in == "telegram" else "email"
        get_db().execute(
            """UPDATE settings SET smtp_host=?, smtp_port=?, smtp_username=?, smtp_password=?,
               recipient=?, twofa_enabled=?, twofa_method=?, reminder_enabled=?, reminder_days_before=? WHERE id=1""",
            (
                host,
                port,
                username,
                enc,
                recipient,
                1 if parse_bool(body.get("twofaEnabled")) else 0,
                method,
                1 if parse_bool(body.get("reminderEnabled")) else 0,
                reminder_days,
            ),
        )
        get_db().commit()
        return api_ok({"ready": smtp_configured()})

    @app.route("/api/smtp/test", methods=["POST"])
    @login_required
    def api_smtp_test():
        err = api_guard(need_json=False)
        if err:
            return err
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

    @app.route("/api/tg")
    @login_required
    def api_tg_get():
        row = get_settings()
        return api_ok(
            {
                "enabled": bool(row["tg_enabled"]),
                "hasToken": bool(row["tg_token"]),
                "chatId": row["tg_chat_id"],
                "reminderEnabled": bool(row["tg_reminder_enabled"]),
                "daysBefore": row["tg_days_before"],
                "ready": tg_configured(),
                "webhookSet": bool(row["tg_chat_id"] and row["tg_token"]),
            }
        )

    @app.route("/api/tg", methods=["POST"])
    @login_required
    def api_tg_save():
        err = api_guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        row = get_settings()
        reminder_days = parse_nonnegative_int_field(body.get("daysBefore"), 3)
        if reminder_days is None:
            return api_fail("提前提醒天数必须是数字", "BAD_DAYS", 400)
        token_in = optional_text_field(body, "token")
        chat_id = text_field(body, "chatId")
        if token_in is None or chat_id is None:
            return api_fail("Telegram 配置字段格式不正确", "BAD_BODY", 400)
        enc = row["tg_token"] if token_in == "" else encrypt_secret(token_in)
        get_db().execute(
            """UPDATE settings SET tg_enabled=?, tg_token=?, tg_chat_id=?,
               tg_reminder_enabled=?, tg_days_before=? WHERE id=1""",
            (
                1 if parse_bool(body.get("enabled")) else 0,
                enc,
                chat_id,
                1 if parse_bool(body.get("reminderEnabled")) else 0,
                reminder_days,
            ),
        )
        get_db().commit()
        # 配置就绪则自动注册 webhook（用于交互式命令）
        if tg_configured():
            try:
                set_telegram_webhook()
            except Exception:
                pass
        return api_ok({"ready": tg_configured()})

    @app.route("/api/tg/chatid", methods=["POST"])
    @login_required
    def api_tg_chatid():
        err = api_guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        token = optional_text_field(body, "token")
        if token is None:
            return api_fail("Bot Token 必须是字符串", "BAD_BODY", 400)
        if not token:
            row = get_settings()
            token = decrypt_secret(row["tg_token"]) if row["tg_token"] else ""
        if not token:
            return api_fail("请先填写 Bot Token", "NO_TOKEN", 400)
        try:
            chat = tg_get_chat_id(token)
        except Exception as exc:
            return api_fail(f"获取失败：{exc}", "FETCH_FAILED", 502)
        if not chat:
            return api_fail("没拿到 Chat ID，请先在 Telegram 给你的 Bot 发一条消息再试", "NO_CHAT", 404)
        return api_ok({"chatId": chat})

    @app.route("/api/tg/test", methods=["POST"])
    @login_required
    def api_tg_test():
        err = api_guard(need_json=False)
        if err:
            return err
        try:
            tg_send("✅ 这是一条来自 SIMHUB Web 的测试消息，收到说明配置正确。")
        except Exception as exc:
            return api_fail(f"发送失败：{exc}", "SEND_FAILED", 502)
        return api_ok({"sent": True})

    @app.route("/api/reminders/status")
    @login_required
    def api_reminders_status():
        row = get_settings()
        return api_ok(
            {
                "lastScanAt": row["last_reminder_scan_at"],
                "lastReminderDate": row["last_reminder_date"],
                "scanned": row["last_reminder_scanned"],
                "matched": row["last_reminder_matched"],
                "sent": row["last_reminder_sent"],
                "failed": row["last_reminder_failed"],
                "scanIntervalSeconds": parse_int(os.environ.get("REMINDER_SCAN_INTERVAL_SECONDS"), 3600),
                "noPageRequired": True,
                "channels": {
                    "email": {
                        "enabled": bool(row["reminder_enabled"]),
                        "ready": smtp_configured(),
                        "daysBefore": row["reminder_days_before"],
                    },
                    "telegram": {
                        "enabled": bool(row["tg_enabled"] and row["tg_reminder_enabled"]),
                        "ready": tg_configured(),
                        "daysBefore": row["tg_days_before"],
                    },
                    "webhook": {
                        "enabled": bool(row["webhook_enabled"]),
                        "ready": webhook_configured(),
                        "daysBefore": row["webhook_days_before"],
                    },
                },
                "history": reminder_history(20),
            }
        )

    @app.route("/api/reminders/history")
    @login_required
    def api_reminders_history():
        return api_ok(reminder_history(parse_int(request.args.get("limit"), 50)))

    @app.route("/api/reminders/history", methods=["DELETE"])
    @login_required
    def api_reminders_history_clear():
        err = api_guard(need_json=False)
        if err:
            return err
        cur = get_db().execute("DELETE FROM reminder_attempt_log")
        get_db().commit()
        return api_ok({"cleared": max(cur.rowcount, 0)})

    @app.route("/api/reminders/scan", methods=["POST"])
    @login_required
    def api_reminders_scan():
        err = api_guard(need_json=False)
        if err:
            return err
        stats = run_due_reminders()
        return api_ok({"stats": stats, "history": reminder_history(20)})

    @app.route("/api/webhook")
    @login_required
    def api_webhook_get():
        row = get_settings()
        return api_ok(
            {
                "enabled": bool(row["webhook_enabled"]),
                "url": row["webhook_url"],
                "method": normalize_webhook_method(row["webhook_method"]),
                "headers": row["webhook_headers"],
                "payload": row["webhook_payload"] or DEFAULT_WEBHOOK_PAYLOAD,
                "daysBefore": row["webhook_days_before"],
                "ready": webhook_configured(),
            }
        )

    @app.route("/api/webhook", methods=["POST"])
    @login_required
    def api_webhook_save():
        err = api_guard()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        url = text_field(body, "url")
        method = text_field(body, "method", "POST")
        headers = text_field(body, "headers", "", strip=False)
        payload = text_field(body, "payload", DEFAULT_WEBHOOK_PAYLOAD, strip=False)
        if None in (url, method, headers, payload):
            return api_fail("Webhook 配置字段格式不正确", "BAD_BODY", 400)
        method = normalize_webhook_method(method)
        if not method:
            return api_fail("Webhook method 仅支持 POST / PUT / PATCH", "BAD_METHOD", 400)
        if parse_bool(body.get("enabled")) and not url:
            return api_fail("启用 Webhook 前请填写 URL", "NO_URL", 400)
        if url:
            try:
                validate_webhook_url(url, resolve=False)
            except ValueError as exc:
                return api_fail(str(exc), "BAD_URL", 400)
        try:
            parse_webhook_headers(headers)
        except ValueError as exc:
            return api_fail(str(exc), "BAD_HEADERS", 400)
        days = parse_nonnegative_int_field(body.get("daysBefore"), 3)
        if days is None:
            return api_fail("提前提醒天数必须是数字", "BAD_DAYS", 400)
        get_db().execute(
            """UPDATE settings SET webhook_enabled=?, webhook_url=?, webhook_method=?,
               webhook_headers=?, webhook_payload=?, webhook_days_before=? WHERE id=1""",
            (
                1 if parse_bool(body.get("enabled")) else 0,
                url,
                method,
                headers,
                payload or DEFAULT_WEBHOOK_PAYLOAD,
                days,
            ),
        )
        get_db().commit()
        return api_ok({"ready": webhook_configured()})

    @app.route("/api/webhook/test", methods=["POST"])
    @login_required
    def api_webhook_test():
        err = api_guard(need_json=False)
        if err:
            return err
        sample = {
            "event_type": "test",
            "subject": "SIMHUB Webhook 测试",
            "text": "这是一条来自 SIMHUB Web 的 Webhook 测试消息。",
            "card": {"carrier": "SIMHUB 测试卡", "countryName": "", "plan": "", "phoneNumber": "", "expiryDate": ""},
            "days_left": "",
            "operation_date": "",
            "operation_note": "",
        }
        try:
            send_webhook(sample)
        except Exception as exc:
            return api_fail(f"发送失败：{exc}", "SEND_FAILED", 502)
        return api_ok({"sent": True})

    @app.route("/api/telegram/webhook", methods=["POST"])
    def telegram_webhook():
        # 校验密钥头，拒绝非 Telegram 来源
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != telegram_webhook_secret():
            return ("", 403)
        update = request.get_json(silent=True) or {}
        msg = update.get("message") or update.get("edited_message") or {}
        chat = msg.get("chat") or {}
        raw_text = msg.get("text") or ""
        text = raw_text.strip() if isinstance(raw_text, str) else ""
        cfg = tg_config()
        # 只响应配置的 Chat ID
        if not cfg["chat_id"] or str(chat.get("id")) != str(cfg["chat_id"]):
            return ("", 200)
        try:
            reply = handle_tg_command(text)
            if reply:
                tg_send(reply, chat_id=str(chat.get("id")))
        except Exception:
            pass
        return ("", 200)

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

    @app.errorhandler(413)
    def payload_too_large(_error):
        if request.path.startswith("/api/"):
            return api_fail("请求体过大，请压缩文件或减少导入数量", "PAYLOAD_TOO_LARGE", 413)
        return "请求体过大", 413

    @app.cli.command("send-reminders")
    def send_reminders_cmd():
        """扫描并发送到期提醒，供 cron 等定时任务调用，不依赖有人打开网页。
        用法：flask --app app.main send-reminders"""
        init_db()
        stats = run_due_reminders()
        print(
            "reminders scan done: scanned={scanned} matched={matched} sent={sent} failed={failed}".format(
                **stats
            )
        )

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
    return (
        _spa_cache["html"]
        .replace("__CSRF_TOKEN__", csrf_token())
        .replace("__CSP_NONCE__", csp_nonce())
    )


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
    # 迁移 settings：补 Telegram / 2FA 方式相关列
    scols = {row["name"] for row in get_db().execute("PRAGMA table_info(settings)")}
    _add = [
        ("twofa_method", "TEXT NOT NULL DEFAULT 'email'"),
        ("tg_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("tg_token", "TEXT NOT NULL DEFAULT ''"),
        ("tg_chat_id", "TEXT NOT NULL DEFAULT ''"),
        ("tg_reminder_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("tg_days_before", "INTEGER NOT NULL DEFAULT 3"),
        ("webhook_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("webhook_url", "TEXT NOT NULL DEFAULT ''"),
        ("webhook_method", "TEXT NOT NULL DEFAULT 'POST'"),
        ("webhook_headers", "TEXT NOT NULL DEFAULT ''"),
        ("webhook_payload", "TEXT NOT NULL DEFAULT ''"),
        ("webhook_days_before", "INTEGER NOT NULL DEFAULT 3"),
        ("last_reminder_scan_at", "TEXT NOT NULL DEFAULT ''"),
        ("last_reminder_scanned", "INTEGER NOT NULL DEFAULT 0"),
        ("last_reminder_matched", "INTEGER NOT NULL DEFAULT 0"),
        ("last_reminder_sent", "INTEGER NOT NULL DEFAULT 0"),
        ("last_reminder_failed", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for col, decl in _add:
        if col not in scols:
            get_db().execute(f"ALTER TABLE settings ADD COLUMN {col} {decl}")
    get_db().execute(
        "UPDATE settings SET webhook_payload = ? WHERE id = 1 AND webhook_payload = ''",
        (DEFAULT_WEBHOOK_PAYLOAD,),
    )
    # 迁移 cards：补单卡特别提醒字段。default 跟随全局，off 关闭，custom 使用单卡天数。
    card_cols = {row["name"] for row in get_db().execute("PRAGMA table_info(cards)")}
    card_add = [
        ("category", "TEXT NOT NULL DEFAULT ''"),
        ("reminder_mode", "TEXT NOT NULL DEFAULT 'default'"),
        ("reminder_days_before", "INTEGER"),
        ("operation_reminder_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ("operation_date", "TEXT"),
        ("operation_days_before_expiry", "INTEGER"),
        ("operation_note", "TEXT"),
    ]
    for col, decl in card_add:
        if col not in card_cols:
            get_db().execute(f"ALTER TABLE cards ADD COLUMN {col} {decl}")
    # 迁移 reminder_log：去重键加入 event_type + channel（区分提醒类型 / 渠道）
    rcols = {row["name"] for row in get_db().execute("PRAGMA table_info(reminder_log)")}
    if rcols and ("channel" not in rcols or "event_type" not in rcols):
        event_expr = "event_type" if "event_type" in rcols else "'expiry'"
        channel_expr = "channel" if "channel" in rcols else "'email'"
        get_db().executescript(
            f"""
            CREATE TABLE reminder_log_new (card_id TEXT NOT NULL, sent_date TEXT NOT NULL,
                event_type TEXT NOT NULL DEFAULT 'expiry', channel TEXT NOT NULL DEFAULT 'email',
                PRIMARY KEY (card_id, event_type, sent_date, channel));
            INSERT OR IGNORE INTO reminder_log_new (card_id, event_type, sent_date, channel)
                SELECT card_id, {event_expr}, sent_date, {channel_expr} FROM reminder_log;
            DROP TABLE reminder_log;
            ALTER TABLE reminder_log_new RENAME TO reminder_log;
            """
        )
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
    migrate_bad_card_ids()
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


def csp_nonce():
    return getattr(g, "csp_nonce", "")


def csrf_is_valid():
    """CSRF token 可来自表单字段 csrf_token 或请求头 X-CSRF-Token。"""
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    return bool(token) and secrets.compare_digest(token, csrf_token())


def validate_csrf():
    if not csrf_is_valid():
        abort(400, "Invalid CSRF token")


def api_guard(need_json=True):
    """会修改状态的 JSON API 统一防护：校验 CSRF，并按需校验请求体是 JSON 对象。
    返回错误响应（应直接 return）或 None（通过）。"""
    if not csrf_is_valid():
        return api_fail("CSRF 校验失败", "CSRF", 403)
    if need_json:
        if not request.is_json:
            return api_fail("需要 application/json 请求体", "NOT_JSON", 415)
        if not isinstance(request.get_json(silent=True), dict):
            return api_fail("请求体必须是 JSON 对象", "BAD_BODY", 400)
    return None


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


# --- 登录限流（内存级，防暴力破解）---
LOGIN_MAX_FAILS = 5
LOGIN_WINDOW = 900  # 15 分钟
_login_fails = {}


def client_ip():
    """取客户端 IP。默认用 request.remote_addr；只有显式开启 TRUST_PROXY
    （部署在会覆盖 X-Forwarded-For 的可信反代后）时，才采用转发头首段，
    避免裸 Flask 下被伪造的 X-Forwarded-For 绕过登录限流。"""
    if app.config.get("TRUST_PROXY"):
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


def valid_username(value):
    return bool(value) and 1 <= len(value) <= 32 and not any(ch.isspace() for ch in value)


def validate_card_field_limits(items):
    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            continue
        for key, limit in CARD_TEXT_LIMITS.items():
            value = item.get(key)
            if value is None or not isinstance(value, str):
                continue
            if len(value) > limit:
                return f"第 {index} 张卡片的 {key} 字段过长，最多 {limit} 个字符"
    return ""


def safe_https_url(value, allowed_host_suffixes=None):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = urllib.parse.urlparse(text)
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    host = parsed.hostname.lower().strip(".")
    if allowed_host_suffixes:
        ok = any(host == suffix or host.endswith("." + suffix) for suffix in allowed_host_suffixes)
        if not ok:
            return None
    return text


def safe_optional_http_url(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = urllib.parse.urlparse(text)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    return text


def safe_app_icon_url(value):
    return safe_https_url(value, {"mzstatic.com"})


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


def _secret_key_material():
    key = app.config.get("DATA_ENCRYPTION_KEY") or app.config["SECRET_KEY"]
    return hashlib.sha256(("simhub-secret:" + key).encode()).digest()


def _fernet_key():
    key = app.config.get("DATA_ENCRYPTION_KEY") or app.config["SECRET_KEY"]
    return base64.urlsafe_b64encode(hashlib.sha256(("simhub-fernet:" + key).encode()).digest())


def _fernet():
    cached = app.config.get("_FERNET")
    if cached is None:
        cached = Fernet(_fernet_key())
        app.config["_FERNET"] = cached
    return cached


def _legacy_secret_key_material():
    return app.config["SECRET_KEY"].encode()


def _keystream(length, salt, key=None):
    """旧版 v2 密文读取兜底；新写入已改用 Fernet。"""
    key = key or _secret_key_material()
    out = b""
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(key + salt + counter.to_bytes(4, "big")).digest()
        counter += 1
    return out[:length]


def encrypt_secret(plaintext):
    """用 DATA_ENCRYPTION_KEY 派生 Fernet 密钥后加密敏感值。"""
    if not plaintext:
        return ""
    token = _fernet().encrypt(str(plaintext).encode("utf-8")).decode("ascii")
    return ENCRYPTED_PREFIX + token


def decrypt_secret(token):
    if not token:
        return ""
    try:
        text = str(token)
        if text.startswith(ENCRYPTED_PREFIX):
            payload = text[len(ENCRYPTED_PREFIX):].encode("ascii")
            return _fernet().decrypt(payload).decode("utf-8")
        if text.startswith("v2:"):
            raw = base64.b64decode(text[3:])
            if len(raw) < 48:
                return ""
            salt, mac, cipher = raw[:16], raw[16:48], raw[48:]
            key = _secret_key_material()
            expected = hmac.new(key, salt + cipher, hashlib.sha256).digest()
            if not hmac.compare_digest(mac, expected):
                return ""
            ks = _keystream(len(cipher), salt, key)
            return bytes(a ^ b for a, b in zip(cipher, ks)).decode()
        raw = base64.b64decode(text)
        salt, cipher = raw[:8], raw[8:]
        ks = _keystream(len(cipher), salt, _legacy_secret_key_material())
        return bytes(a ^ b for a, b in zip(cipher, ks)).decode()
    except (InvalidToken, ValueError, TypeError, UnicodeDecodeError, base64.binascii.Error):
        return ""


def encrypt_card_secret(value):
    return encrypt_secret(value) if value else ""


def decrypt_card_secret(value):
    text = str(value or "")
    if text.startswith(ENCRYPTED_PREFIX) or text.startswith("v2:"):
        return decrypt_secret(text)
    return text


def get_settings():
    return get_db().execute("SELECT * FROM settings WHERE id = 1").fetchone()


def smtp_config():
    """合并数据库配置（优先）与环境变量（兜底），返回可用的 SMTP 参数。"""
    row = get_settings()
    host = (row["smtp_host"] if row else "") or os.environ.get("SMTP_HOST", "")
    username = (row["smtp_username"] if row else "") or os.environ.get("SMTP_USERNAME", "")
    password = decrypt_secret(row["smtp_password"]) if row and row["smtp_password"] else os.environ.get("SMTP_PASSWORD", "")
    port = parse_port((row["smtp_port"] if row and row["smtp_port"] else None) or os.environ.get("SMTP_PORT"), 465) or 465
    recipient = (row["recipient"] if row else "") or username
    return {
        "host": host,
        "port": port,
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


def tg_config():
    row = get_settings()
    token = decrypt_secret(row["tg_token"]) if row and row["tg_token"] else ""
    return {
        "token": token,
        "chat_id": (row["tg_chat_id"] if row else "") or "",
    }


def tg_configured():
    cfg = tg_config()
    return bool(cfg["token"] and cfg["chat_id"])


def tg_send(text, chat_id=None):
    """通过 Telegram Bot API 发送一条消息。"""
    cfg = tg_config()
    token = cfg["token"]
    chat = chat_id or cfg["chat_id"]
    if not (token and chat):
        raise RuntimeError("Telegram 未配置")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat, "text": text, "disable_web_page_preview": True}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(body.get("description") or "Telegram 发送失败")


def telegram_webhook_secret():
    return hashlib.sha256((app.config["SECRET_KEY"] + ":tgwebhook").encode()).hexdigest()[:40]


def set_telegram_webhook():
    """把 webhook 指到本站，用于接收 Telegram 命令。"""
    cfg = tg_config()
    if not cfg["token"]:
        return
    base_url = app.config.get("PUBLIC_BASE_URL") or ""
    if not base_url:
        proto = request.headers.get("X-Forwarded-Proto") or request.scheme
        host = request.headers.get("X-Forwarded-Host") or request.host
        base_url = f"{proto}://{host}"
    url = base_url.rstrip("/") + "/api/telegram/webhook"
    api = f"https://api.telegram.org/bot{cfg['token']}/setWebhook"
    payload = json.dumps(
        {"url": url, "secret_token": telegram_webhook_secret(), "allowed_updates": ["message"]}
    ).encode()
    req = urllib.request.Request(api, data=payload, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()


def handle_tg_command(text):
    """解析 Telegram 命令（支持中文），返回回复文本。"""
    t = (text or "").strip()
    low = t.lower()
    cmd = low.lstrip("/").split("@")[0]

    def fmt_left(card):
        d = days_left(card)
        if d is None:
            return ""
        return f"已过期 {-d} 天" if d < 0 else f"剩 {d} 天"

    if t in ("", "/start", "/help", "帮助", "help", "menu", "菜单"):
        return (
            "SIMHUB 机器人命令：\n"
            "• /list 或「列表」「卡片」— 全部卡片\n"
            "• /expiring 或「快到期」「到期」— 临近到期的卡片\n"
            "• /card 名称 或「查 名称」— 查看某张卡详情"
        )
    cards = load_cards({})
    if cmd in ("list", "cards") or t in ("列表", "卡片", "全部", "所有卡片"):
        if not cards:
            return "暂无卡片。"
        lines = [
            f"{c.get('flag','🌐')} {c.get('carrier') or '未命名'} · {c.get('countryName','')} · {(c.get('expiryDate') or '')[:10]}（{fmt_left(c)}）"
            for c in cards
        ]
        return "共 %d 张卡片：\n" % len(cards) + "\n".join(lines[:50])
    if cmd in ("expiring", "due") or t in ("快到期", "到期", "提醒", "即将到期"):
        soon = [c for c in cards if (days_left(c) is not None and 0 <= days_left(c) <= 30 and not c.get("isLongTerm"))]
        soon.sort(key=lambda c: days_left(c))
        if not soon:
            return "30 天内没有即将到期的卡片。"
        lines = [f"{c.get('flag','🌐')} {c.get('carrier') or '未命名'} · {(c.get('expiryDate') or '')[:10]}（{fmt_left(c)}）" for c in soon]
        return "即将到期：\n" + "\n".join(lines[:50])
    # 查某张卡：/card 名称 或 查 名称
    keyword = ""
    if cmd.startswith("card"):
        keyword = t.split(None, 1)[1].strip() if len(t.split(None, 1)) > 1 else ""
    elif t.startswith("查"):
        keyword = t[1:].strip()
    if keyword:
        kw = keyword.lower()
        match = [c for c in cards if kw in (c.get("carrier") or "").lower() or kw in (c.get("countryName") or "").lower()]
        if not match:
            return f"没找到包含「{keyword}」的卡片。"
        c = match[0]
        parts = [
            f"{c.get('flag','🌐')} {c.get('carrier') or '未命名'}",
            f"国家/地区：{c.get('countryName','')}",
            f"套餐：{c.get('plan','')}" if c.get("plan") else "",
            f"号码：{c.get('phoneNumber','')}" if c.get("phoneNumber") else "",
            f"到期：{(c.get('expiryDate') or '')[:10]}（{fmt_left(c)}）",
            f"SM-DP+：{c.get('smdpAddress','')}" if c.get("smdpAddress") else "",
            f"激活码：{c.get('activationCode','')}" if c.get("activationCode") else "",
            f"EID：{c.get('eid','')}" if c.get("eid") else "",
            f"标签：{'、'.join(c.get('tags') or [])}" if c.get("tags") else "",
        ]
        return "\n".join(p for p in parts if p)
    return "未识别的命令。发送「帮助」查看可用命令。"


def tg_get_chat_id(token):
    """从 getUpdates 取最近一次和 Bot 对话的 chat.id。"""
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    req = urllib.request.Request(url, headers={"User-Agent": "simhub"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if not body.get("ok"):
        raise RuntimeError(body.get("description") or "getUpdates 失败")
    for upd in reversed(body.get("result", [])):
        msg = upd.get("message") or upd.get("edited_message") or {}
        chat = msg.get("chat") or {}
        if chat.get("id") is not None:
            return str(chat["id"])
    return ""


def enabled_reminder_channels(row):
    channels = []
    if row["reminder_enabled"] and smtp_configured():
        channels.append({"key": "email", "days": parse_int(row["reminder_days_before"], 3)})
    if row["tg_enabled"] and row["tg_reminder_enabled"] and tg_configured():
        channels.append({"key": "telegram", "days": parse_int(row["tg_days_before"], 3)})
    if row["webhook_enabled"] and webhook_configured():
        channels.append({"key": "webhook", "days": parse_int(row["webhook_days_before"], 3)})
    return channels


def expiry_reminder_event(card, left):
    name = card.get("carrier") or "未命名卡片"
    expiry = (card.get("expiryDate") or "")[:10]
    text = (
        f"SIMHUB 到期提醒：卡片「{name}」（{card.get('countryName','')} {card.get('plan','')}）"
        f"将于 {expiry} 到期，剩余 {left} 天，请及时续期保号。"
    )
    return {
        "event_type": "expiry",
        "subject": f"SIMHUB 到期提醒：{name} 还有 {left} 天",
        "text": text,
        "card": card,
        "days_left": left,
        "operation_date": "",
        "operation_note": "",
    }


def operation_target_date(card):
    if not card.get("operationReminderEnabled"):
        return None
    explicit = parse_iso(card.get("operationDate"))
    if explicit:
        return explicit.date()
    days_before = parse_optional_nonnegative_int(card.get("operationDaysBeforeExpiry"))
    expiry = parse_iso(card.get("expiryDate"))
    if days_before is None or not expiry:
        return None
    return expiry.date() - timedelta(days=days_before)


def operation_reminder_event(card):
    target = operation_target_date(card)
    if not target or target != date.today():
        return None
    name = card.get("carrier") or "未命名卡片"
    expiry = (card.get("expiryDate") or "")[:10]
    left = days_left(card)
    note = card.get("operationNote") or "请处理这张 SIM 卡的保号事项"
    parts = [
        f"SIMHUB 操作提醒：卡片「{name}」今天需要处理。",
        f"事项：{note}",
    ]
    if expiry:
        parts.append(f"到期日期：{expiry}")
    if left is not None:
        parts.append(f"剩余天数：{left} 天")
    return {
        "event_type": "operation",
        "subject": f"SIMHUB 操作提醒：{name}",
        "text": "\n".join(parts),
        "card": card,
        "days_left": "" if left is None else left,
        "operation_date": target.isoformat(),
        "operation_note": note,
    }


def reminder_already_sent(card_id, event_type, sent_date, channel):
    return get_db().execute(
        "SELECT 1 FROM reminder_log WHERE card_id = ? AND event_type = ? AND sent_date = ? AND channel = ?",
        (card_id, event_type, sent_date, channel),
    ).fetchone()


def log_reminder_sent(card_id, event_type, sent_date, channel):
    get_db().execute(
        "INSERT OR IGNORE INTO reminder_log (card_id, event_type, sent_date, channel) VALUES (?, ?, ?, ?)",
        (card_id, event_type, sent_date, channel),
    )


def log_reminder_attempt(card, event_type, sent_date, channel, status, error=""):
    get_db().execute(
        """INSERT INTO reminder_attempt_log
           (card_id, card_label, event_type, channel, status, error, sent_date, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            card.get("id"),
            card.get("carrier") or "未命名卡片",
            event_type,
            channel,
            status,
            truncate_text(error, 500) if error else "",
            sent_date,
            now_iso(),
        ),
    )


def reminder_history(limit=50):
    limit = min(max(parse_int(limit, 50), 1), 200)
    rows = get_db().execute(
        """SELECT card_id, card_label, event_type, channel, status, error, sent_date, created_at
           FROM reminder_attempt_log ORDER BY id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [
        {
            "cardId": r["card_id"],
            "cardLabel": r["card_label"],
            "eventType": r["event_type"],
            "channel": r["channel"],
            "status": r["status"],
            "error": r["error"],
            "sentDate": r["sent_date"],
            "createdAt": r["created_at"],
        }
        for r in rows
    ]


def send_reminder_event(channel, event, recipient):
    if channel == "email":
        send_email(recipient, event["subject"], event["text"])
    elif channel == "telegram":
        tg_send(event["text"])
    elif channel == "webhook":
        send_webhook(event)
    else:
        raise RuntimeError("未知提醒渠道")


def record_reminder_scan(stats):
    get_db().execute(
        """UPDATE settings SET last_reminder_date=?, last_reminder_scan_at=?,
           last_reminder_scanned=?, last_reminder_matched=?, last_reminder_sent=?,
           last_reminder_failed=? WHERE id=1""",
        (
            date.today().isoformat(),
            now_iso(),
            stats["scanned"],
            stats["matched"],
            stats["sent"],
            stats["failed"],
        ),
    )


def run_due_reminders():
    """扫描临近到期卡片和操作提醒，按启用渠道各自提醒，每卡每事件每渠道每天一次。"""
    stats = {"scanned": 0, "matched": 0, "sent": 0, "failed": 0}
    row = get_settings()
    if not row:
        return stats
    today = date.today().isoformat()
    channels = enabled_reminder_channels(row)
    recipient = smtp_config()["recipient"] if any(c["key"] == "email" for c in channels) else ""

    for card in load_cards({}):
        stats["scanned"] += 1
        if not channels:
            continue
        events = []
        left = days_left(card)
        if not card.get("isLongTerm") and left is not None and left >= 0:
            events.append(("expiry", expiry_reminder_event(card, left)))
        operation_event = operation_reminder_event(card)
        if operation_event:
            events.append(("operation", operation_event))

        for kind, event in events:
            for channel in channels:
                channel_key = channel["key"]
                if kind == "expiry":
                    window = reminder_window_for_card(card, channel["days"])
                    if window is None or left > window:
                        continue
                stats["matched"] += 1
                if reminder_already_sent(card["id"], event["event_type"], today, channel_key):
                    continue
                try:
                    send_reminder_event(channel_key, event, recipient)
                except Exception as exc:
                    stats["failed"] += 1
                    log_reminder_attempt(card, event["event_type"], today, channel_key, "failed", error_text(exc))
                    continue
                log_reminder_sent(card["id"], event["event_type"], today, channel_key)
                log_reminder_attempt(card, event["event_type"], today, channel_key, "success")
                stats["sent"] += 1
    record_reminder_scan(stats)
    get_db().commit()
    return stats


def reminder_window_for_card(card, default_window):
    mode = normalize_reminder_mode(card.get("reminderMode"))
    if mode == "off":
        return None
    if mode == "custom":
        days = parse_optional_nonnegative_int(card.get("reminderDaysBefore"))
        return days if days is not None else default_window
    return default_window


def normalize_webhook_method(value):
    method = str(value or "POST").strip().upper()
    return method if method in {"POST", "PUT", "PATCH"} else ""


def webhook_config():
    row = get_settings()
    return {
        "enabled": bool(row and row["webhook_enabled"]),
        "url": (row["webhook_url"] if row else "") or "",
        "method": normalize_webhook_method(row["webhook_method"] if row else "POST") or "POST",
        "headers": (row["webhook_headers"] if row else "") or "",
        "payload": (row["webhook_payload"] if row else "") or DEFAULT_WEBHOOK_PAYLOAD,
    }


def webhook_configured():
    cfg = webhook_config()
    return bool(cfg["url"])


def validate_webhook_url(value, resolve=True):
    text = str(value or "").strip()
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Webhook URL 仅支持 http / https")
    host = parsed.hostname
    if not host:
        raise ValueError("Webhook URL 缺少主机名")
    lowered = host.lower().strip(".")
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".localhost"):
        raise ValueError("Webhook URL 不能指向 localhost")
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        ip = None
    if ip is not None:
        reject_private_webhook_ip(ip)
    if resolve:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ValueError(f"Webhook URL 解析失败：{exc}") from exc
        checked = set()
        for info in infos:
            addr = info[4][0]
            if addr in checked:
                continue
            checked.add(addr)
            reject_private_webhook_ip(ipaddress.ip_address(addr))
    return text


def reject_private_webhook_ip(ip):
    if ip == ipaddress.ip_address("169.254.169.254") or not ip.is_global:
        raise ValueError("Webhook URL 不能指向本机、内网、链路本地或保留地址")


def parse_webhook_headers(raw):
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("Webhook Headers 必须是 JSON 对象") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Webhook Headers 必须是 JSON 对象")
    headers = {}
    for key, value in parsed.items():
        name = str(key).strip()
        if not name or "\n" in name or "\r" in name or ":" in name:
            raise ValueError("Webhook Header 名称不合法")
        if name.lower() in {"host", "content-length"}:
            raise ValueError("Webhook Header 不允许设置 Host 或 Content-Length")
        headers[name] = str(value)
    return headers


class NoWebhookRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def webhook_template_value(value):
    return json.dumps("" if value is None else str(value), ensure_ascii=False)[1:-1]


def render_webhook_payload(template, event):
    card = event.get("card") or {}
    context = {
        "event_type": event.get("event_type", ""),
        "event_label": "操作提醒" if event.get("event_type") == "operation" else "到期提醒",
        "card_name": card.get("carrier") or "未命名卡片",
        "country": card.get("countryName") or "",
        "plan": card.get("plan") or "",
        "expiry_date": (card.get("expiryDate") or "")[:10],
        "days_left": event.get("days_left", ""),
        "phone_number": card.get("phoneNumber") or "",
        "operation_date": event.get("operation_date", ""),
        "operation_note": event.get("operation_note", ""),
        "message": event.get("text", ""),
    }
    payload = template or DEFAULT_WEBHOOK_PAYLOAD
    for key, value in context.items():
        payload = payload.replace("{{" + key + "}}", webhook_template_value(value))
    return payload


def send_webhook(event):
    cfg = webhook_config()
    url = validate_webhook_url(cfg["url"], resolve=True)
    headers = parse_webhook_headers(cfg["headers"])
    headers.setdefault("Content-Type", "application/json; charset=utf-8")
    payload = render_webhook_payload(cfg["payload"], event).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers=headers, method=cfg["method"])
    opener = urllib.request.build_opener(NoWebhookRedirect)
    try:
        with opener.open(req, timeout=15) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"Webhook HTTP {resp.status}")
            resp.read(1024)
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise RuntimeError("Webhook 不允许跳转") from exc
        raise RuntimeError(f"Webhook HTTP {exc.code}") from exc


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
            "category": "",
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
            "reminderMode": "default",
            "reminderDaysBefore": None,
            "operationReminderEnabled": False,
            "operationDate": None,
            "operationDaysBeforeExpiry": None,
            "operationNote": "",
            "renewalUnit": "days",
            "renewalIntervalValue": 30,
        }
    )


_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# 这些值即使符合字符集，作为 JS 对象 key 也会命中 Object 原型链，
# 导致前端 cardEls[id] 读到原型上的函数而非 undefined / DOM，后续 querySelector 崩溃。
_RESERVED_IDS = {
    "__proto__", "prototype", "constructor", "toString", "toLocaleString",
    "valueOf", "hasOwnProperty", "isPrototypeOf", "propertyIsEnumerable",
    "__defineGetter__", "__defineSetter__", "__lookupGetter__", "__lookupSetter__",
}


def safe_card_id(value):
    """只接受安全格式的卡片 ID（字母/数字/下划线/连字符），并拒绝原型保留字。
    非法 ID（注入串或 __proto__ 等保留 key）一律丢弃，交由调用方重新生成 UUID，
    避免被前端拼进 DOM / 选择器（XSS）或污染对象原型链（列表崩溃）。"""
    text = str(value or "").strip()
    if not _SAFE_ID_RE.match(text) or text in _RESERVED_IDS:
        return ""
    return text


_legacy_ids_done = False


def migrate_bad_card_ids():
    """一次性清理旧库里的非法卡片 ID（含 / 引号 __proto__ 等）：改成新 UUID，
    并同步 activity_log / reminder_log 的引用。每进程只跑一次。"""
    global _legacy_ids_done
    if _legacy_ids_done:
        return
    _legacy_ids_done = True
    db = get_db()
    for row in db.execute("SELECT id FROM cards").fetchall():
        old = row["id"]
        if safe_card_id(old) == old:
            continue
        new = str(uuid.uuid4())
        db.execute("UPDATE cards SET id = ? WHERE id = ?", (new, old))
        db.execute("UPDATE activity_log SET card_id = ? WHERE card_id = ?", (new, old))
        db.execute("UPDATE reminder_log SET card_id = ? WHERE card_id = ?", (new, old))
        db.execute("UPDATE reminder_attempt_log SET card_id = ? WHERE card_id = ?", (new, old))


def normalize_dto(data, existing=None):
    base = dict(existing or default_dto_raw())
    base.update(data or {})

    activation = iso_datetime(base.get("activationDate"))
    expiry_fallback = (parse_iso(activation) or datetime.now(timezone.utc)) + timedelta(days=30)
    expiry = iso_datetime(base.get("expiryDate"), fallback=expiry_fallback)
    renew_days = parse_int(base.get("renewDays"), inferred_days(activation, expiry))
    reminder_mode = normalize_reminder_mode(base.get("reminderMode"))
    reminder_days = parse_optional_nonnegative_int(base.get("reminderDaysBefore"))
    if reminder_mode == "custom" and reminder_days is None:
        reminder_days = 3
    if reminder_mode != "custom":
        reminder_days = None
    operation_date_raw = blank_none(base.get("operationDate"))
    operation_date = iso_datetime(operation_date_raw) if operation_date_raw and parse_iso(operation_date_raw) else None
    operation_days = parse_optional_nonnegative_int(base.get("operationDaysBeforeExpiry"))
    if parse_bool(base.get("operationReminderEnabled")) and not operation_date and operation_days is None:
        operation_days = 1

    dto = {
        "id": safe_card_id(base.get("id")),
        "carrier": str(base.get("carrier") or "").strip(),
        "plan": str(base.get("plan") or "").strip(),
        "category": str(base.get("category") or "").strip(),
        "phoneNumber": str(base.get("phoneNumber") or "").strip(),
        "countryCode": str(base.get("countryCode") or "").strip().upper(),
        "countryName": str(base.get("countryName") or "").strip(),
        "flag": str(base.get("flag") or "🌐").strip() or "🌐",
        "cardBackgroundAssetName": blank_none(base.get("cardBackgroundAssetName")),
        "cardColorHex": blank_none(base.get("cardColorHex")),
        "cardBackgroundImageData": blank_none(base.get("cardBackgroundImageData")),
        "carrierAppIconURLString": safe_app_icon_url(base.get("carrierAppIconURLString")),
        "carrierAppStoreURLString": safe_optional_http_url(base.get("carrierAppStoreURLString")),
        "carrierAppName": blank_none(base.get("carrierAppName")),
        "activationDate": activation,
        "expiryDate": expiry,
        "price": str(base.get("price") or "").strip(),
        "currencyCode": blank_none(str(base.get("currencyCode") or "").strip().upper()),
        "cyclePaymentMinorUnits": parse_optional_int(base.get("cyclePaymentMinorUnits")),
        "currentBalanceMinorUnits": parse_optional_int(base.get("currentBalanceMinorUnits")),
        "websiteURL": safe_optional_http_url(base.get("websiteURL")),
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
        "reminderMode": reminder_mode,
        "reminderDaysBefore": reminder_days,
        "operationReminderEnabled": parse_bool(base.get("operationReminderEnabled")),
        "operationDate": operation_date,
        "operationDaysBeforeExpiry": operation_days,
        "operationNote": blank_none(base.get("operationNote")),
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
        "category": "",
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
        "reminderMode": "default",
        "reminderDaysBefore": None,
        "operationReminderEnabled": False,
        "operationDate": None,
        "operationDaysBeforeExpiry": None,
        "operationNote": "",
        "renewDays": 30,
        "renewalUnit": "days",
        "renewalIntervalValue": 30,
    }


def form_dto(existing=None):
    tags = request.form.get("tags", "")
    data = {
        "carrier": request.form.get("carrier", ""),
        "plan": request.form.get("plan", ""),
        "category": request.form.get("category", ""),
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
        "reminderMode": request.form.get("reminderMode", "default"),
        "reminderDaysBefore": request.form.get("reminderDaysBefore", ""),
        "operationReminderEnabled": request.form.get("operationReminderEnabled") == "on",
        "operationDate": request.form.get("operationDate", ""),
        "operationDaysBeforeExpiry": request.form.get("operationDaysBeforeExpiry", ""),
        "operationNote": request.form.get("operationNote", ""),
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
                parsed = json.loads(row["tags_json"] or "[]")
            except json.JSONDecodeError:
                parsed = []
            dto[key] = parsed if isinstance(parsed, list) else []
            continue
        column = DTO_TO_COL.get(key)
        value = row[column] if column else None
        if key in CARD_SECRET_FIELDS:
            value = decrypt_card_secret(value)
        if key in {"isLongTerm", "operationReminderEnabled"}:
            value = bool(value)
        dto[key] = value
    return dto


def dto_values(dto):
    return [
        dto["id"],
        dto["carrier"],
        dto["plan"],
        dto.get("category"),
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
        encrypt_card_secret(dto["smdpAddress"]),
        encrypt_card_secret(dto["activationCode"]),
        encrypt_card_secret(dto.get("confirmationCode")),
        encrypt_card_secret(dto["eid"]),
        dto["createdAt"],
        dto["updatedAt"],
        1 if dto.get("isLongTerm") else 0,
        dto.get("reminderMode") or "default",
        dto.get("reminderDaysBefore"),
        1 if dto.get("operationReminderEnabled") else 0,
        dto.get("operationDate"),
        dto.get("operationDaysBeforeExpiry"),
        dto.get("operationNote"),
        dto.get("renewDays") or 30,
        dto.get("renewalUnit"),
        dto.get("renewalIntervalValue"),
    ]


def insert_card(dto):
    get_db().execute(
        """
        INSERT INTO cards (
            id, carrier, plan, category, phone_number, country_code, country_name, flag,
            card_background_asset_name, card_color_hex, card_background_image_data,
            carrier_app_icon_url_string, carrier_app_store_url_string, carrier_app_name,
            activation_date, expiry_date, price, currency_code, cycle_payment_minor_units,
            current_balance_minor_units, website_url, current_balance, transaction_notes,
            custom_prompt, tags_json, order_index, smdp_address, activation_code,
            confirmation_code, eid, created_at, updated_at, is_long_term, reminder_mode,
            reminder_days_before, operation_reminder_enabled, operation_date,
            operation_days_before_expiry, operation_note, renew_days, renewal_unit,
            renewal_interval_value
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        dto_values(dto),
    )


def update_card(card_id, dto):
    dto["updatedAt"] = now_iso()
    values = dto_values(dto)[1:] + [card_id]
    get_db().execute(
        """
        UPDATE cards
           SET carrier = ?, plan = ?, category = ?, phone_number = ?, country_code = ?, country_name = ?, flag = ?,
               card_background_asset_name = ?, card_color_hex = ?, card_background_image_data = ?,
               carrier_app_icon_url_string = ?, carrier_app_store_url_string = ?, carrier_app_name = ?,
               activation_date = ?, expiry_date = ?, price = ?, currency_code = ?, cycle_payment_minor_units = ?,
               current_balance_minor_units = ?, website_url = ?, current_balance = ?, transaction_notes = ?,
               custom_prompt = ?, tags_json = ?, order_index = ?, smdp_address = ?, activation_code = ?,
               confirmation_code = ?, eid = ?, created_at = ?, updated_at = ?, is_long_term = ?,
               reminder_mode = ?, reminder_days_before = ?, operation_reminder_enabled = ?,
               operation_date = ?, operation_days_before_expiry = ?, operation_note = ?,
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
    q = (filters.get("q") or "").strip()
    country = filters.get("country")
    if country:
        where.append("country_name = ?")
        args.append(country)

    sql = "SELECT * FROM cards"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY order_index ASC, expiry_date ASC"
    cards = [row_to_dto(row) for row in get_db().execute(sql, args).fetchall()]

    if q:
        needle = q.casefold()

        def matches(card):
            fields = [
                card.get("carrier"),
                card.get("plan"),
                card.get("category"),
                card.get("phoneNumber"),
                card.get("countryName"),
                card.get("eid"),
                card.get("smdpAddress"),
                card.get("activationCode"),
            ]
            return any(needle in str(item or "").casefold() for item in fields)

        cards = [card for card in cards if matches(card)]
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
    return bool(duplicate_reason(dto))


def duplicate_reason(dto, existing_cards=None):
    if dto.get("id") and card_exists(dto["id"]):
        return "id"
    phone = dto.get("phoneNumber", "").strip()
    eid = dto.get("eid", "").strip()
    activation = dto.get("activationCode", "").strip()
    smdp = dto.get("smdpAddress", "").strip()
    cards = existing_cards if existing_cards is not None else load_cards({})
    for card in cards:
        if phone and str(card.get("phoneNumber") or "").strip() == phone:
            return "phoneNumber"
        if eid and str(card.get("eid") or "").strip() == eid:
            return "eid"
        if (
            activation
            and smdp
            and str(card.get("activationCode") or "").strip() == activation
            and str(card.get("smdpAddress") or "").strip() == smdp
        ):
            return "activation"
    return ""


IOS_COMPAT_FIELDS = [
    "id", "carrier", "plan", "phoneNumber", "countryCode", "countryName", "flag",
    "category",
    "cardBackgroundAssetName", "cardColorHex", "cardBackgroundImageData",
    "carrierAppIconURLString", "carrierAppStoreURLString", "carrierAppName",
    "activationDate", "expiryDate", "price", "currencyCode", "cyclePaymentMinorUnits",
    "currentBalanceMinorUnits", "websiteURL", "currentBalance", "transactionNotes",
    "customPrompt", "tags", "orderIndex", "smdpAddress", "activationCode",
    "confirmationCode", "eid", "createdAt", "updatedAt", "isLongTerm", "renewDays",
    "renewalUnit", "renewalIntervalValue",
]


def import_preview(raw_cards, dtos):
    recognized = set()
    unknown = set()
    for item in raw_cards:
        if not isinstance(item, dict):
            continue
        for key in item:
            if key in IOS_COMPAT_FIELDS or key in DTO_FIELDS:
                recognized.add(key)
            else:
                unknown.add(key)

    rows = []
    can_import = 0
    missing_carrier = 0
    duplicate_counts = {}
    lpa_count = 0
    money_count = 0
    icon_count = 0
    existing_cards = load_cards({})
    for dto in dtos:
        reason = ""
        if not dto.get("carrier"):
            reason = "missingCarrier"
            missing_carrier += 1
        else:
            reason = duplicate_reason(dto, existing_cards)
            if reason:
                duplicate_counts[reason] = duplicate_counts.get(reason, 0) + 1
        if not reason:
            can_import += 1
        if dto.get("smdpAddress") and dto.get("activationCode"):
            lpa_count += 1
        if dto.get("cyclePaymentMinorUnits") is not None or dto.get("currentBalanceMinorUnits") is not None:
            money_count += 1
        if dto.get("carrierAppIconURLString") or dto.get("carrierAppName"):
            icon_count += 1
        if len(rows) < 20:
            rows.append(
                {
                    "carrier": dto.get("carrier") or "未命名",
                    "country": dto.get("countryName") or dto.get("countryCode") or "",
                    "flag": dto.get("flag") or "🌐",
                    "plan": dto.get("plan") or "",
                    "expiryDate": dto.get("expiryDate") or "",
                    "status": reason or "ready",
                    "hasLPA": bool(dto.get("smdpAddress") and dto.get("activationCode")),
                }
            )
    return {
        "count": len(dtos),
        "cards": dtos,
        "summary": {
            "ready": can_import,
            "missingCarrier": missing_carrier,
            "duplicates": duplicate_counts,
            "withLPA": lpa_count,
            "withMoney": money_count,
            "withCarrierIcon": icon_count,
        },
        "fields": {
            "recognized": sorted(recognized),
            "unknown": sorted(unknown),
            "missingCommon": [field for field in IOS_COMPAT_FIELDS if field not in recognized],
        },
        "rows": rows,
    }


LPA_TEXT_TRANSLATION = str.maketrans({
    "：": ":",
    "＄": "$",
    "﹩": "$",
    "＃": "#",
    "？": "?",
    "＆": "&",
})


def parse_lpa_payload(value):
    text = normalize_lpa_text(value)
    if not text:
        return None
    for candidate in lpa_candidates(text):
        parsed = parse_lpa_candidate(candidate)
        if parsed:
            smdp, activation, confirmation = parsed
            return lpa_result(smdp, activation, confirmation)
    parsed = parse_lpa_named_fields(text)
    if parsed:
        smdp, activation, confirmation = parsed
        return lpa_result(smdp, activation, confirmation)
    return None


def normalize_lpa_text(value):
    text = str(value or "").strip()
    if not text:
        return ""
    for _ in range(3):
        decoded = urllib.parse.unquote(text)
        if decoded == text:
            break
        text = decoded
    text = text.translate(LPA_TEXT_TRANSLATION)
    return re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text).strip()


def lpa_candidates(text):
    candidates = []
    parsed = urllib.parse.urlparse(text)
    if parsed.query:
        for piece in parsed.query.split("&"):
            key, sep, raw_value = piece.partition("=")
            if sep and key.lower() in {"carddata", "lpa", "activationcode", "activation_code"}:
                candidates.append(normalize_lpa_text(raw_value))
    candidates.append(text)
    return candidates


def parse_lpa_candidate(text):
    if not text:
        return None
    normalized = normalize_lpa_text(text)
    normalized = re.sub(r"\s*([:$])\s*", r"\1", normalized)
    match = re.search(r"(?:LPA:)?1\$[^\s\"'<>]+", normalized, re.IGNORECASE)
    candidate = match.group(0) if match else normalized.strip()
    if candidate.upper().startswith("LPA:"):
        candidate = candidate[4:]
    if not candidate.startswith("1$"):
        return None
    parts = candidate.split("$")
    if len(parts) < 2 or parts[0] != "1":
        return None
    smdp = clean_lpa_token(parts[1])
    activation = clean_lpa_token(parts[2]) if len(parts) >= 3 else ""
    confirmation = clean_lpa_token(parts[3]) if len(parts) >= 4 else ""
    if not valid_lpa_parts(smdp, activation, confirmation, require_activation=False):
        return None
    return smdp, activation, confirmation


def parse_lpa_named_fields(text):
    normalized = normalize_lpa_text(text)
    smdp = extract_lpa_field(
        normalized,
        r"(?:SM\s*-\s*DP\+?|SMDP\+?|SM-DP\+\s*(?:地址|Address)?|服务器地址|SMDP地址)",
    )
    activation = extract_lpa_field(
        normalized,
        r"(?:Activation\s*Code|Matching\s*ID|激活码|匹配ID|配对ID)",
    )
    confirmation = extract_lpa_field(
        normalized,
        r"(?:Confirmation\s*Code|确认码)",
    )
    if not valid_lpa_parts(smdp, activation, confirmation, require_activation=False):
        return None
    return smdp, activation, confirmation


def extract_lpa_field(text, label_pattern):
    match = re.search(label_pattern + r"\s*[:：]\s*([^\r\n]+)", text, re.IGNORECASE)
    if not match:
        return ""
    return clean_lpa_token(match.group(1))


def clean_lpa_token(value):
    token = normalize_lpa_text(value)
    token = token.strip().strip(" \t\r\n\"'<>")
    token = re.split(r"[&#?]", token, 1)[0]
    return token.strip().strip(" \t\r\n\"'<>")


def valid_lpa_parts(smdp, activation, confirmation="", require_activation=True):
    if not smdp or (require_activation and not activation):
        return False
    if any(ch in smdp + activation for ch in "\r\n\t "):
        return False
    if confirmation and any(ch in confirmation for ch in "\r\n\t "):
        return False
    return True


def lpa_result(smdp, activation, confirmation=""):
    standard = make_lpa(smdp, activation, confirmation)
    complete = bool(smdp and activation)
    return {
        "smdpAddress": smdp,
        "activationCode": activation,
        "confirmationCode": confirmation,
        "lpa": standard,
        "complete": complete,
        "message": "" if complete else "已识别 SM-DP+，但二维码里没有激活码。",
        "iosInstallURL": "https://esimsetup.apple.com/esim_qrcode_provisioning?carddata=" + urllib.parse.quote(standard, safe=""),
    }


def make_lpa(smdp, activation, confirmation=""):
    if confirmation:
        return f"LPA:1${smdp}${activation}${confirmation}"
    return f"LPA:1${smdp}${activation}"


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


def parse_nonnegative_int_field(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return None
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return None


def parse_optional_nonnegative_int(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return None


def normalize_reminder_mode(value):
    mode = str(value or "default").strip()
    return mode if mode in {"default", "off", "custom"} else "default"


def parse_port(value, default=None):
    if value in (None, ""):
        value = default
    if isinstance(value, bool):
        return None
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None


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


_MISSING = object()

DEFAULT_WEBHOOK_PAYLOAD = json.dumps(
    {
        "event": "{{event_type}}",
        "card_name": "{{card_name}}",
        "country": "{{country}}",
        "plan": "{{plan}}",
        "expiry_date": "{{expiry_date}}",
        "days_left": "{{days_left}}",
        "phone_number": "{{phone_number}}",
        "operation_date": "{{operation_date}}",
        "operation_note": "{{operation_note}}",
    },
    ensure_ascii=False,
    indent=2,
)


def text_field(body, key, default="", strip=True):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str):
        return None
    return value.strip() if strip else value


def optional_text_field(body, key, strip=True):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        return ""
    if not isinstance(value, str):
        return None
    return value.strip() if strip else value


def blank_none(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def truncate_text(value, limit):
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def error_text(exc):
    text = str(exc).strip()
    return text or exc.__class__.__name__


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
