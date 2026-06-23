# SIMHUB Web

独立版 Linux 自托管 Web 端，用来管理 SIM/eSIM **保号卡片**——记录运营商、号码、套餐、到期日，临近到期提醒续费，避免号码被注销。

## 项目定位

这是 iOS App [`maow318/simhub`](https://github.com/maow318) 内置 Web 管理端的**独立 Linux 版本**，字段与 JSON 格式和 App 完全对齐：

- 前端参考：`esimSubscription/WebManagement/simhubweb.html`
- API 参考：`esimSubscription/WebManagement/WebAPIController.swift`
- 数据结构参考：`esimSubscription/ESIMCard.swift` 里的 `ESIMCardDTO`

**和 App 的关系 / 数据同步**：本 Web 端是**自成一体**的，自己的 SQLite 数据库就是数据源，**不与 App 实时双向同步**。两端互通靠**JSON 导入/导出**（格式一致，可来回搬运）。同一台服务器上多个浏览器之间，靠每 4 秒轮询 `/api/status` 做到近实时刷新——任一端改动，其它端自动重载。

## 功能

- 首次启动创建管理员账号；密码登录，所有后台页面必须登录
- **登录限流**：同一 IP 连续登录失败会进入冷却，防暴力破解
- **邮件功能**（对齐 App「邮件提醒」，在「设置」里自己填 SMTP，无需改服务端）
  - 登录两步验证：开启后登录需「密码 + 邮箱一次性验证码」
  - 卡片到期提醒：临近到期自动发邮件（可设提前天数，每张卡每天最多一封）
  - 服务商下拉自动带出服务器/端口、可寄测试邮件；授权码用 `SECRET_KEY` 加密后存库，不明文落盘
- 单页管理端（SPA）：概览、卡片管理、导入导出、设置
- 概览面板：卡片总数 / 7 天内到期 / 已过期统计，国家分布、最近修改
- 卡片详情视图 + 居中弹窗编辑；右上角 ⋯ 进详情，详情内再编辑
- **国旗光效卡片背景**：每张卡按国家显示对应背景图（166 国），遮罩随主题自适应，可手动换/清除
- 国家/地区选择器（252 个 ISO 地区，国旗 + 中英文名 + 区号搜索）
- **JSON 导入兼容**：国家代码 ↔ 国旗 ↔ 名称 ↔ 卡片背景自动互相补全，从 App 备份导入即带正确国旗与背景
- App Store 图标搜索（后端代理 Apple iTunes Search API，按国家 storefront）
- 批量编辑：多选后批量打标签 / 批量删除
- 电话号码默认打码，可单独点眼睛显示
- 深色 / 浅色主题切换
- 数据备份入口（设置内一键导出 JSON + 卷备份说明）
- JSON / CSV 导入导出（导入前预览、去重后写入）
- Docker / Docker Compose（含 HTTPS）/ systemd + nginx 多种部署

## 隐私与安全

- **数据完全本地化**：所有卡片存在你自己服务器的 SQLite（Docker 卷 `simhub-data`），不上传任何第三方。
- **登录密码**：`pbkdf2:sha256` 哈希存储，不可逆。
- **SMTP 授权码**：用 `SECRET_KEY` 派生密钥加密后存库（非明文）。请务必固定 `SECRET_KEY`，否则重启后解不开需重填。
- **登录限流**：连续失败进入冷却，配合可选的邮箱两步验证防爆破。
- **传输加密**：生产环境请走 HTTPS（见下方 Caddy 部署），不要让登录走公网明文 HTTP。
- 卡片里的 SM-DP+ / 激活码 / EID 等敏感字段当前以明文存于本机数据库，安全性依赖服务器自身（建议磁盘加密 + 严格文件权限 + 定期备份）。

## 部署

### 方式一：生产 HTTPS（推荐，Caddy 自动签证书）

前提：有一个域名，其 DNS A 记录已指向本服务器，且服务器 80/443 端口可达。

```bash
cp .env.example .env
# 生成并填入 SECRET_KEY；把 SIMHUB_DOMAIN 改成你的域名
python3 -c "import secrets;print('SECRET_KEY='+secrets.token_urlsafe(48))"

docker compose -f docker-compose.prod.yml up -d --build
```

Caddy 会自动为 `SIMHUB_DOMAIN` 签发 Let's Encrypt 证书并强制 HTTPS。访问 `https://你的域名`，第一次打开会要求创建管理员。

### 方式二：纯 HTTP（仅本地 / 内网测试）

```bash
cp .env.example .env   # 填好 SECRET_KEY
docker compose up -d --build
# 访问 http://服务器IP:8080
```

> ⚠️ 公网请勿只用 HTTP——登录密码会明文传输。务必用方式一或自行套 HTTPS。

### 方式三：裸机 systemd + nginx

```bash
sudo useradd --system --home /var/lib/simhub-keeper --shell /usr/sbin/nologin simhub
sudo mkdir -p /opt/simhub-keeper-web /var/lib/simhub-keeper
sudo chown simhub:simhub /var/lib/simhub-keeper
python3 -m venv /opt/simhub-keeper-web/.venv
/opt/simhub-keeper-web/.venv/bin/pip install -r requirements.txt
```

环境文件 `/etc/simhub-keeper.env`：

```text
SECRET_KEY=change-this-to-a-long-random-string
DATABASE=/var/lib/simhub-keeper/simhub.sqlite
```

复制 `systemd/simhub-keeper.service` 到 `/etc/systemd/system/`，然后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now simhub-keeper
```

再把 `nginx/simhub-keeper.conf` 按域名改好放进 nginx 配置目录（建议配合 certbot 上 HTTPS）。

## 备份

- **一键导出**：设置 → 数据备份 → 导出 JSON 备份（兼容 App 格式，可再导入）。
- **整库备份**（Docker 卷）：

```bash
docker run --rm -v simhub-data:/data -v "$PWD":/backup alpine \
  tar czf /backup/simhub-backup-$(date +%Y%m%d).tar.gz -C /data .
```

## 界面预览

> 截图可放在 `docs/screenshots/` 下：概览页、卡片管理（国旗背景）、卡片详情、编辑弹窗、设置页。

## App 数据兼容 / API

SQLite 内部表 `cards` 字段用 snake_case 保存；导入导出与 API 返回时转换成 App 的 camelCase `ESIMCardDTO`。

```text
GET    /api/cards
POST   /api/cards
GET    /api/cards/<id>
PUT    /api/cards/<id>
DELETE /api/cards/<id>
POST   /api/cards/batch-update     # {"ids":[...],"action":"delete"|"addTags","tags":[...]}
GET    /api/export
POST   /api/import                 # {"mode":"preview"|"commit","cards":[...]}
GET    /api/countries              # 252 国（国旗、区号、卡片背景）
GET    /api/appsearch?term=&country=US   # 代理 Apple iTunes 搜 App 图标
GET    /api/smtp  /  POST /api/smtp  /  POST /api/smtp/test   # 邮件配置
POST   /api/password               # 修改登录密码
```

## 贡献

欢迎 Issue / PR。开发约定：

- 后端：单文件 Flask（`app/main.py`），保持轻量、无重型依赖。
- 前端：`app/templates/spa.html` 单页，原生 JS + CSS 变量，无前端框架。
- 提 PR 前请本地跑通：创建管理员 → 登录 → 增删改查卡片 → 导入导出。
- Bug / 需求请走 GitHub Issues（建议附复现步骤、截图、部署方式）。

## 许可证

[AGPL-3.0](LICENSE)。你可以自由使用、修改、自托管；但若你修改后**对外提供网络服务**，须同样以 AGPL 开源你的修改版本。
