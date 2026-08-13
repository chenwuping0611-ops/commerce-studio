# 实施路线

目标：在不引入 Dify、Flowise、Redis 或本地模型的情况下，完成 2C2G 可运行版本。

原则：

- 每阶段都有可验收结果。
- 每阶段都能独立提交 Git。
- 先验证兼容性，再开发业务。
- 先完成服务端数据和权限，再接入 Canvas。
- 生成任务必须从第一天就支持恢复。

---

## 阶段 0：兼容性闸门（代码侧已完成）

目标：

- 验证 NestJS、AdminJS、Prisma、MySQL、React Flow 组合。

输出：

- 版本锁定文件
- Nest Express 启动
- AdminJS 登录页
- 一个 Prisma CRUD 资源
- 一个 React Flow 自定义节点
- Nginx 代理验证

必须通过：

```text
AdminJS 页面加载
AdminJS Prisma 读取
AdminJS Prisma 读取；业务写入走 Nest API
React Flow 节点渲染
生产模式启动
2C2G 内存检查（目标服务器待验证）
```

如果失败，优先修正兼容层，不进入业务开发。

---

## 阶段 1：工程骨架（已完成）

目标：

- 建立模块化 NestJS 单体。

模块：

```text
common
config
database
http
logger
auth
rbac
system
```

输出：

- 环境配置校验
- 统一错误响应
- requestId/traceId
- Prisma Client 生命周期
- `/health/live`
- `/health/ready`
- Nginx 基础配置

---

## 阶段 2：认证、RBAC 和审计（MVP 已完成）

目标：

- 让所有后续业务从第一天带有权限边界。

输出：

- 登录、退出和当前用户
- 用户、角色、小组
- 权限资源和动作
- own/team/system 数据范围
- 管理员审计日志
- AdminJS 只读资源权限
- API 权限 Guard/Policy

验收：

- employee 不能访问系统模型密钥。
- team_lead 只能查看团队数据。
- visitor 不能创建任务。
- 管理员修改权限会生成审计记录。

---

## 阶段 3：产品中心（MVP 已完成）

目标：

- 建立产品和 SKU 的真实数据源。

输出：

- Product CRUD
- ProductVariant CRUD
- ProductAsset 元数据
- 视角素材管理
- 产品与团队关联
- 授权媒体上传和下载

验收：

- 产品可关联多个 SKU。
- 每个 SKU 可关联六面图、主图、细节图和场景图。
- 媒体不进入 MySQL BLOB。
- 越权用户无法读取产品素材。

---

## 阶段 4：Product Memory 和 Prompt Engine（基础能力已完成）

目标：

- 实现产品防跑偏和 Prompt 自动组合。

输出：

- 产品事实
- 品牌视觉记忆
- 生成边界
- 禁忌规则
- 记忆版本
- 成功/失败案例（待补充数据模型和页面）
- Prompt 模板和版本（表结构已预留，管理页面待补充）
- Prompt 编译预览
- 冲突检测

验收：

```text
产品
  + Product Memory
  + 用户创意
      -> Prompt 快照
```

生成任务必须保存当时的 Prompt 和 Memory 快照。

---

## 阶段 5：Model Gateway（OpenAI 兼容链路已完成）

目标：

- 统一官方 API 和中转 API。

输出：

- Provider CRUD
- ModelProfile CRUD
- API Key 加密
- Native Provider Adapter（按供应商逐个补充）
- OpenAI Compatible Adapter
- 图片/视频能力通过 OpenAI 兼容 Adapter 统一承载
- 超时和重试
- 能力检查
- 供应商错误归一化

验收：

- 浏览器看不到明文 API Key。
- 页面不能直连供应商。
- 同一个业务接口可切换官方和 OpenAI 兼容 Base URL。
- 供应商错误能映射到稳定错误码。

---

## 阶段 6：Generation Task 和媒体结果（基础闭环已完成）

目标：

- 完成图片/视频异步任务闭环。

输出：

- MySQL 任务表
- 单 Worker
- 租约和心跳
- 任务恢复
- 供应商任务 ID
- 轮询已完成；Webhook 待补充
- 结果下载
- GenerationAsset
- CostLedger（表结构已预留，成本写入待补充）

验收：

- Node 进程重启后未完成任务可继续。
- 视频任务不会占用长 HTTP 请求。
- 同一回调重复到达不会生成重复结果。
- 任务失败有错误码和重试记录。

---

## 阶段 7：React Flow Canvas（保存链路已完成，执行编排待补充）

目标：

- 把产品记忆和生成能力嵌入 Canvas。

第一批节点：

```text
Product
ProductVariant
Memory
Prompt
Structure
Model
ImageReference
ImageGeneration
FirstFrame
VideoGeneration
Result
History
```

输出：

- React Flow 页面
- 基础节点已完成；业务自定义节点待补充
- 自定义边
- 节点校验和执行编译（待补充）
- Canvas JSON 保存
- 版本快照
- 执行快照
- Canvas Ops、撤销重做（待补充）
- 产品和素材选择器

验收：

- Canvas 只保存业务引用，不保存 API Key 和大文件。
- Canvas 执行使用服务端任务接口。
- 节点权限和产品权限一致。
- 页面刷新后能恢复视口、节点和连线。

---

## 阶段 8：历史、成本和运营后台（基础能力已完成）

目标：

- 对齐星河起源式运营后台能力。

输出：

- 任务记录
- 生成历史
- 成本统计（待接入 CostLedger 写入）
- 供应商错误率（待补充聚合查询）
- 失败任务重试
- 结果评分
- 审计查询
- 模型启停

---

## 阶段 9：2C2G 部署与维护（模板已完成，服务器联调待执行）

目标：

- 在单节点服务器稳定运行。

输出：

- Nginx HTTPS
- systemd 服务
- 外部 MySQL 连接和迁移模板
- 单 Worker
- 日志轮转
- MySQL 备份
- 媒体备份
- 恢复演练（待在目标服务器执行）
- 健康检查
- 发布脚本

验收：

- API、AdminJS、SSE、媒体访问均通过 Nginx（配置已提供，目标服务器待验证）。
- MySQL 不暴露公网。
- 2C2G 下有 Swap 和内存告警。
- 备份可以恢复到测试目录。

---

## Git 里程碑

每个阶段完成后单独提交：

```text
chore: verify stack compatibility
feat: add application skeleton
feat: add auth and rbac
feat: add product center
feat: add product memory and prompt engine
feat: add model gateway
feat: add generation task worker
feat: add react flow canvas
feat: add history and cost dashboard
ops: add single node deployment
```

`main` 只接收通过测试和审查的阶段提交。

---

## 暂不实施

- 本地模型
- ComfyUI
- Dify 常驻部署
- Flowise 常驻部署
- Redis/BullMQ
- 多节点部署
- 多租户计费
- 任意远程 JS 插件
- Canvas 多人实时协作
- Protobuf 浏览器主协议

触发扩容或复杂化的条件见根目录 `agent.md`。
