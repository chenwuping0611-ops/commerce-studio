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
- go-fastdfs：产品素材、Skill、参考文件和生成结果的统一文件存储

Infinite Canvas 不在当前实现范围内。

## 技术栈

- Python 3.11
- Flask 2.0.2
- Flask-SQLAlchemy 2.5.1
- MySQL + PyMySQL
- Flask-APScheduler
- Requests
- Layui + Pear Admin

## 本地安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirement\requirement-dev.txt
```

## MySQL-only 本地启动

项目只支持 MySQL，不提供 SQLite 回退。先在 `.flaskenv` 配置可访问的 MySQL：

```powershell
MYSQL_HOST=your-mysql-host
MYSQL_PORT=3306
MYSQL_DATABASE=pear_ai_studio
MYSQL_TEST_DATABASE=pear_ai_studio_test
MYSQL_USERNAME=your-user
MYSQL_PASSWORD=your-password
```

如果目标数据库还不存在，先执行一次 Pear Admin 的 MySQL 初始化命令。它会创建目标数据库并导入基础管理表；数据库已经存在时不会重复导入：

```powershell
.\.venv\Scripts\python.exe -m flask init
```

然后创建 Commerce Studio 表、菜单、RBAC、ToAPIs 供应商和默认模型模板：

```powershell
.\.venv\Scripts\python.exe -m flask studio-init
```

启动本地服务：

```powershell
.\.venv\Scripts\python.exe -m flask run --host 0.0.0.0 --port 5000
```

访问：

```text
http://127.0.0.1:5000/admin/
```

默认账号：

```text
admin / 123456
```

首次进入后应立即修改密码。测试配置使用 `MYSQL_TEST_DATABASE`，必须使用独立的 MySQL 测试库，禁止指向生产库。

## ToAPIs 配置

登录后台后进入“模型供应商”：

1. 编辑 ToAPIs，填写 API Key。
2. 确认用户余额地址为 `/v1/user/balance`，Token 余额地址为 `/v1/balance`。
3. 编辑图片或视频模型，按中转接口文档维护 body 字段。
4. 在对应创作页选择产品和模型，提交异步任务。
5. 使用生成历史中的 7 位编号查看状态和输出。

模型字段由数据库配置驱动。`field` 是上游 body key，`runtime_key` 将字段绑定到创作页输入；空字段不会发送。

## go-fastdfs 配置

所有新图片、视频和 Skill 文件都通过 `FileService` 写入 go-fastdfs。
本地 `.flaskenv` 保留公网地址，服务器部署时必须先确认 fileserver 的实际监听端口，
再设置内部地址：

```text
GOFASTDFS_INTERNAL_URL=http://127.0.0.1:<actual-port>
GOFASTDFS_PUBLIC_URL=https://ray.garafana.com/gofastdfs
GOFASTDFS_GROUP=group1
```

产品中心素材和 Skill 文件永久保留；用户参考文件以及 API 生成图片、视频保留 7 天。
清理任务由 Flask-APScheduler 定时执行，删除失败会保留为可重试状态。

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
