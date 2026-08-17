# Commerce Studio

基于 Pear Admin Flask 二次开发的 AI 电商图片 / 视频生成后台。

## 当前范围

- Pear Admin 登录、用户、角色、权限、部门、操作日志和审计能力
- 工作台首页
- 图片创作与异步任务轮询
- 视频创作与异步任务轮询
- 产品中心：产品资料、Product Profile、产品记忆、生成规则、禁止修改规则、引用素材
- Skill 配置：手动创建，以及拖拽导入 `md`、`json`、`txt`、`yaml`、`yml`
- 模型供应商：官方 API 或中转 API 连接配置
- 模型定义：图片 / 视频分开，支持自定义提交地址、查询地址和任意请求字段
- 生成历史：7 位任务编号查询、状态、进度和输出资产
- ToAPIs：图片与视频任务提交、任务查询、用户余额和 Token 余额

Infinite Canvas 不在当前实现范围内。

## 技术栈

- Python 3.11
- Flask 2.0.2
- Flask-SQLAlchemy 2.5.1
- MySQL + PyMySQL
- SQLite（仅用于本地临时验证）
- Flask-APScheduler
- Requests
- Layui + Pear Admin

## 本地安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirement\requirement-dev.txt
```

## 临时 SQLite 启动

远程 MySQL 尚未放行本机来源时，可以先使用 SQLite 验证页面和业务流程：

```powershell
$env:STUDIO_USE_SQLITE = "1"
.\.venv\Scripts\python.exe -m flask studio-init
.\.venv\Scripts\python.exe -m flask run --host 127.0.0.1 --port 5000
```

访问：

```text
http://127.0.0.1:5000/admin/
```

默认账号：

```text
admin / 123456
```

首次进入后应立即修改密码。

## MySQL 初始化

本地 `.flaskenv` 只用于开发，已经加入 `.gitignore`，不要提交到 Git。部署时配置以下变量：

```text
MYSQL_HOST=your-mysql-host
MYSQL_PORT=3306
MYSQL_DATABASE=pear_ai_studio
MYSQL_USERNAME=your-user
MYSQL_PASSWORD=your-password
```

确认数据库允许当前客户端来源、且目标库已经创建后执行：

```powershell
.\.venv\Scripts\python.exe -m flask studio-init
```

`studio-init` 会创建 Commerce Studio 表，补齐后台菜单和 RBAC 权限，并初始化 ToAPIs、`gpt-image-2` 和 `seedance-2` 模板。
如果需要导入 Pear Admin 原始 SQL，也可以先执行 `flask init`；新安装不要求重复执行。

## ToAPIs 配置

登录后台后进入“模型供应商”：

1. 编辑 ToAPIs，填写 API Key。
2. 确认用户余额地址为 `/v1/user/balance`，Token 余额地址为 `/v1/balance`。
3. 编辑图片或视频模型，按中转接口文档维护 body 字段。
4. 在对应创作页选择产品和模型，提交异步任务。
5. 使用生成历史中的 7 位编号查看状态和输出。

模型字段由数据库配置驱动。`field` 是上游 body key，`runtime_key` 将字段绑定到创作页输入；空字段不会发送。

## 目录边界

```text
applications/models/              SQLAlchemy 实体
applications/studio/              请求构造、供应商客户端、提示词和任务轮询
applications/view/studio/         页面路由和 JSON API
templates/studio/                 工作台页面
static/studio/                    共享样式和浏览器脚本
agent.md                          长期开发与维护规范
```

## 验证

```powershell
.\.venv\Scripts\python.exe -m compileall -q applications app.py
```

后续新增功能必须遵循 [agent.md](agent.md) 中的模块边界、RBAC、供应商请求和验证流程。
