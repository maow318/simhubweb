# SIMHUB Web

SIMHUB Web 是一个自托管的 SIM / eSIM 卡片管理后台，用 Flask + SQLite 实现，前端是原生 JS 单页应用。它适合管理保号卡、旅行卡、备用号码、银行绑定号、实体 SIM 和 eSIM 资料。

数据默认保存在你自己的服务器 SQLite 数据库里，不依赖第三方云服务。你可以通过 Docker Compose 快速部署，也可以在本地开发运行。

> 使用入口必须是 `http://` 或 `https://` 服务地址。不要直接打开 `app/templates/spa.html`，`file://` 模式下 API、App 图标代理、摄像头权限、登录状态等功能都不会按生产环境工作。

## 社区与反馈

- Telegram 交流群：[https://t.me/+BMNiJDL-Qjc5MDg1](https://t.me/+BMNiJDL-Qjc5MDg1)
- GitHub：提交 Issue 或 PR 前，请尽量附上部署方式、浏览器、日志和复现步骤。

## 功能概览

- 管理 SIM / eSIM 卡片：运营商、国家/地区、号码、套餐、价格、备注、官网、App Store 入口
- 到期与续费：到期日期、长期卡、续费周期、费用估算、90 天到期时间线
- eSIM 信息：SM-DP+、激活码、确认码、EID、LPA 字符串
- eSIM 工具：LPA 解析、二维码识别、摄像头扫描、本地二维码生成、iOS 安装链接
- giffgaff 转 eSIM：OAuth 登录、账户读取、邮件验证、SIM swap、生成 eSIM LPA
- 卡片背景：按国家/地区匹配背景图，也可手动清除或选择
- App 图标：从 Apple iTunes Search API 搜索，图标通过后端安全代理加载
- 导入导出：JSON / CSV 导入导出，导入前预览，兼容 App 备份格式
- 提醒通知：邮件、Telegram、Webhook，到期提醒和单卡操作提醒
- 安全：首次安装令牌、登录限流、CSRF、敏感字段加密、CSV 公式注入防护
- 部署：Docker Compose、Caddy 自动 HTTPS、非 root 容器、后台提醒 worker

## 推荐部署方式

生产环境推荐使用：

```text
Docker Compose + Caddy + HTTPS + SQLite 数据卷
```

本仓库的 `docker-compose.prod.yml` 会启动：

- `simhub-keeper`：Web 后台
- `simhub-reminders`：后台提醒 worker
- `simhub-caddy`：Caddy 反向代理，自动申请 HTTPS 证书

你需要准备：

- 一台 Linux VPS
- 一个域名
- 域名 DNS A 记录指向 VPS 公网 IP
- VPS 开放 80 / 443 端口
- 已安装 Docker 和 Docker Compose

## 快速部署

### 1. 拉取项目

```bash
git clone https://github.com/maow318/simhubweb.git
cd simhubweb
cp .env.example .env
```

### 2. 生成密钥

分别生成 `SECRET_KEY`、`DATA_ENCRYPTION_KEY` 和 `SETUP_TOKEN`：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
python3 -c "import secrets; print(secrets.token_urlsafe(24))"
```

把生成结果写入 `.env`：

```env
SECRET_KEY=替换为第一条随机值
DATA_ENCRYPTION_KEY=替换为第二条随机值
SETUP_TOKEN=替换为第三条随机值
SIMHUB_DOMAIN=simhub.example.com
SESSION_COOKIE_SECURE=1
ENABLE_HSTS=1
TRUST_PROXY=1
TZ=Asia/Shanghai
```

说明：

- `SECRET_KEY` 用于会话签名，必须长期固定。
- `DATA_ENCRYPTION_KEY` 用于加密 SMTP、Telegram、SM-DP+、激活码、确认码、EID 等敏感字段，丢失后旧数据无法解密。
- `SETUP_TOKEN` 用于首次创建管理员，公网部署强烈建议设置，避免 `/setup` 被他人抢先注册。
- `SIMHUB_DOMAIN` 改成你的真实域名，不要带 `https://`。

### 3. 启动生产环境

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

访问：

```text
https://你的域名
```

首次进入会创建管理员。如果设置了 `SETUP_TOKEN`，页面会要求输入安装令牌。

### 4. 查看状态

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f app
docker compose -f docker-compose.prod.yml logs -f reminders
```

## 本地或内网测试

本地测试可以用普通 Docker Compose，不需要 HTTPS：

```bash
cp .env.example .env
docker compose up -d --build
```

访问：

```text
http://服务器IP:8080
```

本地 HTTP 测试时不要开启：

```env
SESSION_COOKIE_SECURE=1
ENABLE_HSTS=1
```

## 升级

如果是从 GitHub 部署：

```bash
cd simhubweb
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

升级不会删除 Docker 数据卷。升级前仍建议先备份。

## 备份与恢复

网页内导出：

```text
设置 -> 数据备份 -> 导出 JSON 备份
```

Docker 数据卷备份：

```bash
docker run --rm -v simhub-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/simhub-backup-$(date +%Y%m%d).tar.gz -C /data .
```

恢复时先停止服务，再把备份解压回数据卷。导出的 JSON 和数据库可能包含号码、LPA、EID、Telegram Token、SMTP 授权码等敏感信息，请按密钥文件保存。

## 环境变量

核心变量：

```env
SECRET_KEY=change-this-to-a-long-random-string
DATA_ENCRYPTION_KEY=change-this-to-another-long-random-string
SETUP_TOKEN=change-this-first-run-token
DATABASE=/data/simhub.sqlite
TZ=Asia/Shanghai
SIMHUB_DOMAIN=simhub.example.com
PUBLIC_BASE_URL=https://simhub.example.com
REMINDER_SCAN_INTERVAL_SECONDS=3600
```

安全相关：

```env
SESSION_COOKIE_SECURE=1
ENABLE_HSTS=1
TRUST_PROXY=1
```

`TRUST_PROXY=1` 只应在可信反向代理后开启，并且反代必须覆盖或正确设置 `X-Forwarded-For`。使用本仓库 `docker-compose.prod.yml` + `Caddyfile` 时可以保持默认开启。裸 Flask 直连公网时不要开启。

导入限制：

```env
MAX_CONTENT_LENGTH=8388608
MAX_IMPORT_CARDS=1000
```

giffgaff 转 eSIM 工具：

```env
GIFFGAFF_CLIENT_ID=
GIFFGAFF_CLIENT_SECRET=
GIFFGAFF_REDIRECT_URI=giffgaff://auth/callback/
```

`GIFFGAFF_CLIENT_ID` 和 `GIFFGAFF_CLIENT_SECRET` 只写入服务器 `.env`，不要提交到 GitHub。

## giffgaff 转 eSIM

使用路径：

```text
eSIM 工具 -> giffgaff 转 eSIM
```

建议流程：

1. 先用 Google Chrome 打开 `giffgaff.com` 并登录账号。
2. 回到 SIMHUB Web，点击「生成登录链接」。
3. 点击「打开登录」。
4. 在 Chrome 按 F12 打开开发者工具，到 Network 面板中找到以 `giffgaff://auth/callback/?code=...&state=...` 开头的回调内容。
5. 把整条回调 URL 或其中的 `code` 粘贴到 SIMHUB Web，点击「换取令牌」。
6. 读取账户，发送邮件验证码，验证后执行转换。

注意：

- 转换会发起 giffgaff SIM swap，当前实体 SIM 可能失效。
- giffgaff access token 只保存在当前浏览器会话中，不写入 SIMHUB 数据库。
- 生成的 LPA 会在本机生成二维码，不发送到第三方二维码服务。

## 安全说明

- 密码使用 `pbkdf2:sha256` 哈希保存。
- SMTP 授权码、Telegram Token、SM-DP+、激活码、确认码、EID 会加密后入库。
- 写操作 API 需要 `X-CSRF-Token`，并只接受 JSON 请求体。
- 登录失败限流记录持久化在 SQLite，避免重启后清零。
- 首次安装可设置 `SETUP_TOKEN`，防止公网管理员抢注。
- CSV 导出会中和 `= + - @` 开头的单元格，降低公式注入风险。
- App Store 图标代理只允许 Apple `mzstatic.com` 图片，避免开放代理风险。
- 不要把 `.env`、数据库、导出 JSON、备份包提交到 GitHub。

## 项目结构

```text
app/
  main.py                 Flask 后端、API、提醒逻辑
  schema.sql              SQLite 表结构
  reminder_worker.py      Docker 后台提醒 worker
  countries.py            国家/地区和国旗背景映射
  templates/spa.html      主单页后台
  static/                 图标、背景、PWA 资源
docker-compose.yml        本地 / 内网 HTTP 部署
docker-compose.prod.yml   生产 HTTPS + Caddy 部署
Dockerfile                应用镜像
systemd/                  裸机部署服务文件
nginx/                    裸机反代示例
```

## 开发

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
flask --app app.main run --debug
```

检查：

```bash
python3 -m compileall app
python3 -m unittest discover -s tests -v
```

前端在 `app/templates/spa.html`，后端主要在 `app/main.py`。项目设计目标是保持轻量 Flask，不引入重型框架，并尽量兼容现有 App 的 JSON 导入导出结构。

## API

登录后可访问：

```text
/api/docs
```

常用端点：

```text
GET    /api/status
GET    /api/cards
POST   /api/cards
GET    /api/cards/<id>
PUT    /api/cards/<id>
DELETE /api/cards/<id>
POST   /api/cards/batch-update

GET    /api/export
POST   /api/import
POST   /api/lpa/parse

GET    /api/countries
GET    /api/appsearch?term=&country=US
GET    /api/app-icon?url=

GET    /api/reminders/status
POST   /api/reminders/run
```

## 许可证

[AGPL-3.0](LICENSE)。你可以自由使用、修改和自托管；如果修改后对外提供网络服务，需要同样以 AGPL 开源修改版本。
