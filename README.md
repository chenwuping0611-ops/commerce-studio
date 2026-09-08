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

项目只支持 MySQL，不提供 SQLite 回退。仓库不包含本地 `.flaskenv`。
请复制 `.flaskenv.example` 为 `.flaskenv`，再填入自己的数据库、供应商和文件存储配置。
`.flaskenv` 已加入 Git 忽略规则，不会被提交到远端。

```powershell
MYSQL_HOST=your-mysql-host
MYSQL_PORT=3306
MYSQL_DATABASE=pear_ai_studio
MYSQL_TEST_DATABASE=pear_ai_studio_test
MYSQL_USERNAME=your-user
MYSQL_PASSWORD=your-password
```

全新环境使用下面的初始化命令。它会删除并重建 `MYSQL_DATABASE`，执行完整
Alembic 迁移，创建 Pear Admin、部门、RBAC、Studio、Amazon AI 及全部关系表。
不会导入 `test/pear.sql`，不会创建测试数据，默认只创建 `admin` 用户。
`--skip-storage` 用于 GoFastDFS 尚未部署时先完成数据库初始化：

```powershell
.\.venv\Scripts\python.exe -m flask init --fresh --yes --skip-storage
```

初始化会创建 ToAPIs、快跑 AI、接口AI 的供应商和模型模板，但 API Key 强制为空。
部门表默认创建 `总项目`、`三部五组`、`三部二组` 三个组织结构节点，
`admin` 绑定到 `总项目` 并作为唯一超级管理员；普通用户只能绑定两个业务部门。
登录后可以在部门管理中继续新增实际业务部门，再为部门配置供应商和 API Key。

接口AI使用 OpenAI 兼容 Responses API。默认 Base URL 为
`https://api.jiekou.ai/openai/v1`，请求地址为 `/responses`；支持
`gpt-5.5`、`gpt-5.4`、`gpt-5.4-mini`、`gpt-5.6-sol`、`gpt-5.6-terra`
和 `gpt-5.6-luna`。
它与快跑 AI 文本模型共用项目内的 Responses 请求适配，支持 Skill 文件、
产品图片和 `web_search` 工具。
接口AI同时提供 `gpt-image2` 图片模型，请求地址为
`https://api.jiekou.ai/v3/gpt-image-2-edit`。图片请求固定使用
`size=auto`、`background=opaque`、`output_format=png`，并将 1K、2K、4K
分别映射为 `quality=low`、`medium`、`high`；所选画面比例和分辨率会自动
追加到图片 Prompt 的输出规格末尾。接口AI返回的临时图片 URL 会先下载到
本地临时文件，再统一上传到 GoFastDFS。

供应商模型调用默认最多执行 3 次（首次请求加最多 2 次业务重试）。已获得上游任务 ID 或
同步输出后的存储失败不会重新提交生成请求；同一业务任务只保留一条本地历史。

GoFastDFS 部署完成并配置 `.flaskenv` 后，如需上传内置 Skill 文件，再执行：

```powershell
.\.venv\Scripts\python.exe -m flask init --seed-storage
```

线上发布时，如果需要把仓库内全部代码内置 Skill 重新上传到 GoFastDFS，
切换数据库中的新地址并清理旧对象，执行：

```bash
python -m flask sync-skills
```

该命令只处理 `applications/amazon_ai/skills/` 和共享反馈 Skill，不会同步
本地测试数据、产品素材、生成历史、自定义 Skill 或供应商 API Key。

启动本地服务：

```powershell
.\.venv\Scripts\python.exe -m flask run --host 0.0.0.0 --port 5000
```

访问：

```text
http://127.0.0.1:5000/admin/
```

首次初始化账号（如果没有设置 `ADMIN_PASSWORD`）：

```text
admin / 123456
```

生产环境请在 `.flaskenv` 设置随机的 `ADMIN_PASSWORD`，不要使用默认密码。
测试配置使用 `MYSQL_TEST_DATABASE`，必须使用独立的 MySQL 测试库，禁止指向生产库。
新建用户默认获得“AI 创作用户”角色，拥有 AI 创作工作台权限，不包含系统管理权限。
管理员可以在“角色管理”中按页面和操作逐项授权。

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
本地 `.flaskenv` 只在本机保存实际地址，服务器部署时必须先确认 fileserver 的实际监听端口，
再设置内部地址。公开仓库只提供占位示例：

```text
GOFASTDFS_INTERNAL_URL=http://127.0.0.1:<actual-port>
GOFASTDFS_PUBLIC_URL=https://your-domain.example/gofastdfs
GOFASTDFS_GROUP=group1
```

产品中心素材和 Skill 文件永久保留；用户参考文件以及 API 生成图片、视频按当前配置保留 30 天。
清理任务由 Flask-APScheduler 定时执行，删除失败会保留为可重试状态。

## CentOS 9 生产日志

生产模式不会把日志写入项目目录，也不会把应用运行日志作为主要输出留在
`journalctl` 中。项目日志统一写入 `/var/log/pear-ai`：

```text
/var/log/pear-ai/pear-ai.log             Flask、业务和 Alembic 日志
/var/log/pear-ai/gunicorn-access.log    HTTP 访问日志
/var/log/pear-ai/gunicorn-error.log     Gunicorn 启动和 Worker 错误
/var/log/pear-ai/systemd.log            systemd 标准输出
/var/log/pear-ai/systemd-error.log      systemd 标准错误
```

当前线上部署按实际服务器配置由 `root` 运行，不需要创建 `pear` 用户。
推荐把项目部署到 `/opt/pear-ai`，避免服务路径依赖 `/root` 目录。部署模板
位于 `deploy/`：

```bash
sudo install -d -o root -g root -m 0750 /var/log/pear-ai
sudo chown -R root:root /opt/pear-ai
sudo cp /opt/pear-ai/deploy/pear-ai.service /etc/systemd/system/pear-ai.service
sudo cp /opt/pear-ai/deploy/pear-ai-tmpfiles.conf /etc/tmpfiles.d/pear-ai.conf
sudo cp /opt/pear-ai/deploy/pear-ai-logrotate /etc/logrotate.d/pear-ai
sudo systemd-tmpfiles --create
sudo systemctl daemon-reload
sudo systemctl enable --now pear-ai
sudo systemctl status pear-ai --no-pager
```

实时查看项目运行日志：

```bash
sudo tail -f /var/log/pear-ai/pear-ai.log
sudo tail -f /var/log/pear-ai/gunicorn-error.log
sudo tail -f /var/log/pear-ai/gunicorn-access.log
```

`deploy/pear-ai.service` 会显式覆盖旧 `.flaskenv` 中的 `LOG_DIR=logs`，
使用 `PEAR_AI_LOG_DIR=/var/log/pear-ai` 和独立的 `pear-ai.log`。日志轮转
配置在 `deploy/pear-ai-logrotate`，无需修改应用代码即可配合 CentOS 9 的
`logrotate` 工作。

直接执行项目根目录的 `start.sh` 也会自动使用生产模式，并把 Gunicorn
日志写入同一目录。

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
