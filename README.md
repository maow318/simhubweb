# SIMHUB Web

独立版 Linux Web 端，用来管理 SIM/eSIM 保号卡片。这个版本已经对齐 `maow318/simhub` 里的内置 Web 管理端：

- 前端参考：`esimSubscription/WebManagement/simhubweb.html`
- API 参考：`esimSubscription/WebManagement/WebAPIController.swift`
- 数据结构参考：`esimSubscription/ESIMCard.swift` 里的 `ESIMCardDTO`

它保留 Linux 自托管需要的密码登录，同时使用和 iOS App 一致的卡片字段与 JSON 导入导出格式。

## 功能

- 首次启动创建管理员账号
- 密码登录，所有后台页面必须登录
- 邮件功能（对齐 App「邮件提醒」）：在「设置」里自己填 SMTP（服务商下拉自动带出服务器/端口、发信邮箱、授权码、可寄测试邮件），无需改服务端
  - 登录两步验证：开启后登录需「密码 + 邮箱一次性验证码」
  - 卡片到期提醒：临近到期自动发邮件（可设提前天数，每张卡每天最多一封）
  - 授权码用 `SECRET_KEY` 加密后存库，不明文落盘
- 单页管理端（SPA），对齐 iOS 内置 Web：概览、卡片管理、导入导出、设置
- 概览面板：卡片总数、7 天内到期、已过期统计，国家/地区分布和最近修改
- 抽屉式新增/编辑卡片，字段对齐 `ESIMCardDTO`：运营商、套餐、号码、国家/地区、到期日、价格、余额、标签、SM-DP+、激活码、EID 等
- 国家/地区选择器（252 个 ISO 地区，带国旗、中英文名、区号搜索）
- 国旗光效卡片背景：每张卡按国家显示对应的国旗光效背景图（166 国），可在编辑里手动换/清除
- JSON 导入兼容：国家代码 ↔ 国旗 ↔ 名称 ↔ 卡片背景自动互相补全，从 App 备份导入即带正确国旗与背景
- App Store 图标搜索（后端代理 Apple iTunes Search API，按国家 storefront）
- 方案时长快捷按钮（7/15/30/70/90/180/365 天）与长期保号开关
- 批量编辑：多选卡片后批量打标签、批量删除
- 电话号码默认打码，可单独点眼睛显示
- 深色 / 浅色主题切换
- 设置内直接修改登录密码
- JSON 导入/导出兼容 App 备份格式（导入前预览、去重后写入）
- `/api/cards`、`/api/export`、`/api/import`、`/api/countries`、`/api/appsearch` 使用和内置 Web 相近的 JSON envelope
- CSV 导出
- Docker Compose 部署
- systemd + nginx 裸机部署示例

## Docker 部署

```bash
cp .env.example .env
python3 - <<'PY'
import secrets
print("SECRET_KEY=" + secrets.token_urlsafe(48))
PY
```

把输出写进 `.env` 的 `SECRET_KEY`，然后启动：

```bash
docker compose up -d --build
```

访问：

```text
http://服务器IP:8080
```

第一次打开会要求创建管理员。

## 裸机部署

Ubuntu/Debian 示例：

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

复制 `systemd/simhub-keeper.service` 到 `/etc/systemd/system/` 后：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now simhub-keeper
```

再把 `nginx/simhub-keeper.conf` 按域名改好，放进 nginx 配置目录。

## App 数据兼容

SQLite 内部表名是 `cards`，字段用 snake_case 保存；导入导出和 API 返回时会转换成 App 使用的 camelCase `ESIMCardDTO`。

常用端点：

```text
GET  /api/cards
POST /api/cards
GET  /api/cards/<id>
PUT  /api/cards/<id>
DELETE /api/cards/<id>
GET  /api/export
POST /api/import
POST /api/cards/batch-update   # {"ids":[...],"action":"delete"|"addTags","tags":[...]}
GET  /api/countries            # 国家/地区列表（含国旗、区号）
GET  /api/appsearch?term=&country=US   # 代理 Apple iTunes 搜索 App 图标
POST /api/password             # {"current":"...","new":"..."} 修改登录密码
```

`/api/import` 支持：

```json
{"mode":"preview","cards":[...]}
{"mode":"commit","cards":[...]}
```

## 下一步

iOS 内置 Web 的单页交互已整体搬过来（概览、批量标签、App Store 图标搜索、国家/地区选择器、抽屉式编辑、深色模式等）。如需进一步贴近原生 App，可继续补充卡片背景图、拖拽排序、活动日志可视化等细节。`app/countries.py` 里的国家列表可按需扩充。
