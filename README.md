# SIMHUB Web

SIMHUB Web 是一个自托管的 SIM / eSIM 卡片管理后台，用来记录运营商、号码、套餐、国家/地区、到期时间、续费成本、LPA 信息和提醒状态。它适合长期维护保号卡、旅行卡、备用号码和各类 eSIM 资料。

当前版本是面向 Linux / Docker 的独立 Web 版本，数据保存在自己的 SQLite 数据库里，不依赖第三方云服务。

## 功能概览

- 账户初始化、登录、修改用户名、修改密码
- 概览面板：卡片总数、7 天内到期、已过期、风险项、费用估算、90 天到期时间线
- 卡片管理：卡片视图 / 列表视图、搜索、国家筛选、状态筛选、批量编辑、批量删除
- 卡片详情：运营商、国家/地区、号码、套餐、价格、备注、官网、App Store 入口、LPA / EID 信息
- 国旗背景卡片：按国家/地区自动匹配卡片背景，可清除或手动设置
- eSIM 解析器：支持手动输入、二维码图片识别、摄像头扫描，生成 LPA 字符串和二维码
- 导入导出：JSON / CSV 导入导出，导入前预览，兼容 App 备份格式
- 通知提醒：邮件、Telegram、Webhook，到期提醒和单卡操作提醒
- 提醒历史和最近活动清理
- 深色 / 浅色主题，浅色玻璃拟态 UI
- Docker Compose、HTTPS Caddy、systemd + nginx 部署方式

> 第三方运营商转换工具当前未包含在正式 UI 中，后续等流程稳定后再考虑加入。

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

## 快速部署

### 生产环境 HTTPS

准备一个域名，并让 DNS A 记录指向服务器。然后：

```bash
cp .env.example .env

python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"
python3 -c "import secrets; print('DATA_ENCRYPTION_KEY=' + secrets.token_urlsafe(48))"
```

把生成的 `SECRET_KEY`、`DATA_ENCRYPTION_KEY` 写入 `.env`，并把 `SIMHUB_DOMAIN` 改成你的域名：

```env
SECRET_KEY=请替换为固定随机值
DATA_ENCRYPTION_KEY=请替换为另一个固定随机值
SIMHUB_DOMAIN=simhub.example.com
SESSION_COOKIE_SECURE=1
ENABLE_HSTS=1
```

启动：

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Caddy 会自动申请 HTTPS 证书。首次访问 `https://你的域名` 时会进入管理员创建流程。

### 本地或内网测试

```bash
cp .env.example .env
docker compose up -d --build
```

访问：

```text
http://服务器IP:8080
```

公网部署不要裸跑 HTTP。

## 环境变量

核心变量：

```env
SECRET_KEY=change-this-to-a-long-random-string
DATA_ENCRYPTION_KEY=change-this-to-another-long-random-string
DATABASE=/data/simhub.sqlite
TZ=Asia/Shanghai
SIMHUB_DOMAIN=simhub.example.com
REMINDER_SCAN_INTERVAL_SECONDS=3600
```

安全相关：

```env
SESSION_COOKIE_SECURE=1
ENABLE_HSTS=1
# 仅在可信反代覆盖 X-Forwarded-For 时开启
# TRUST_PROXY=1
```

导入限制：

```env
MAX_CONTENT_LENGTH=8388608
MAX_IMPORT_CARDS=1000
```

邮件、Telegram、Webhook 通知主要在网页「设置」里配置，不需要直接写环境变量。

## 数据与备份

Docker 默认把数据库挂载到 `/data/simhub.sqlite`。生产环境请定期备份数据卷。

一键导出：

```text
设置 -> 数据备份 -> 导出 JSON 备份
```

Docker 卷备份示例：

```bash
docker run --rm -v simhub-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/simhub-backup-$(date +%Y%m%d).tar.gz -C /data .
```

导出的 JSON 可能包含号码、SM-DP+、激活码、确认码、EID 等敏感信息，请按密钥文件保存。

## 提醒机制

Docker Compose 会同时启动：

- `simhub-keeper`：Web 后台
- `simhub-reminders`：后台提醒 worker

默认每小时扫描一次：

```env
REMINDER_SCAN_INTERVAL_SECONDS=3600
```

支持：

- 到期提醒
- 单卡操作提醒，例如续费、充值、实名、取消套餐
- 邮件、Telegram、Webhook
- 提醒历史、失败原因、立即扫描

提醒去重按 `card_id + event_type + sent_date + channel` 记录。发送失败不会记为成功，同一天会继续重试。

## 安全说明

- 密码使用 `pbkdf2:sha256` 哈希保存
- SMTP 授权码、Telegram Token、SM-DP+、激活码、确认码、EID 会加密后入库
- 写操作 API 需要 `X-CSRF-Token`，并只接受 JSON 请求体
- 默认登录限流，防止暴力破解
- 支持邮箱或 Telegram 登录二次验证
- 生产环境建议开启 `SESSION_COOKIE_SECURE=1` 和 `ENABLE_HSTS=1`
- 不要把 `.env`、数据库、导出 JSON、备份包提交到 GitHub

`DATA_ENCRYPTION_KEY` 必须长期固定。丢失后，已加密的通知配置和 eSIM 敏感字段无法解密，需要重新填写。

## eSIM 解析器

后台的「eSIM 工具」目前只保留通用解析器：

- 手动输入 `LPA:1$smdp.example.com$MATCHINGID`
- 从二维码图片识别 LPA
- 使用摄像头扫描二维码
- 生成二维码
- 复制 iOS 安装链接
- 带入新卡片表单

解析在浏览器和本服务内完成，不会发送到第三方二维码解析服务。

## API 概览

登录后可访问 `/api/docs` 查看字段和端点说明。

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

GET    /api/smtp
POST   /api/smtp
POST   /api/smtp/test

GET    /api/reminders/status
POST   /api/reminders/run

POST   /api/username
POST   /api/password
```

## 开发

本地运行：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
flask --app app.main run --debug
```

语法检查：

```bash
python3 -m compileall app
```

开发约定：

- 后端保持轻量 Flask，不引入重型框架
- 前端为 `app/templates/spa.html` 单页原生 JS
- 数据结构兼容 App 的 JSON 导入导出
- UI 以浅色玻璃拟态为主，优先可读性和管理效率

## 许可证

[AGPL-3.0](LICENSE)。你可以自由使用、修改和自托管；如果修改后对外提供网络服务，需要同样以 AGPL 开源修改版本。
