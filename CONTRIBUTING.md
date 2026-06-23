# 贡献指南

感谢参与 SIMHUB Web！

## 项目结构

- `app/main.py` — 单文件 Flask 后端（路由、API、SQLite、邮件、限流）。保持轻量，不引入重型依赖。
- `app/templates/spa.html` — 单页前端（原生 JS + CSS 变量，无框架）。
- `app/templates/login.html` / `setup.html` / `login_code.html` — 独立的认证页面。
- `app/countries.py` + `app/country_map.json` — 252 国数据与国旗/背景映射。
- `app/static/flags/` — 国旗光效卡片背景图。

## 本地开发

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
SECRET_KEY=dev DATABASE=./dev.sqlite flask --app app.main run
# 打开 http://127.0.0.1:5000
```

## 提交前自检

- 创建管理员 → 登录 → 卡片增删改查 → 导入导出，全流程跑通。
- 亮色 / 暗色两种主题都看一眼。
- 浏览器控制台无报错。

## 约定

- 提交信息用中文或英文均可，说明「做了什么 + 为什么」。
- 大改动先开 Issue 讨论范围。
- 本项目以 AGPL-3.0 授权，提交即表示同意以该协议贡献。
