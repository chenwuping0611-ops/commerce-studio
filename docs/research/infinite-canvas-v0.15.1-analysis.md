# infinite-canvas v0.15.1 源码分析

分析对象：

```text
references/infinite-canvas-v0.15.1/
```

版本文件：

```text
v0.15.1
```

许可证：

```text
MIT License
```

分析方式：只读静态源码分析，未安装依赖、未启动项目、未修改第三方源码。

---

## 1. 项目实际定位

`infinite-canvas` 不是后台管理系统，也不是带 RBAC、产品中心和服务端任务中心的 SaaS 基础。

它实际是一个面向图片创作的浏览器工作台，核心能力包括：

- 无限画布
- 文本、图片、视频、音频和配置节点
- 节点拖拽、缩放、选择和连线
- 图片/视频/音频/文本生成
- 参考图编辑
- Prompt 来源和提示词库
- 本地素材库
- 画布助手
- 本地 Canvas Agent
- 远程节点插件
- 导入导出和撤销重做

仓库还包含：

- `web`：Vite + React 前端
- `canvas-agent`：本地 Agent HTTP/MCP 服务
- `plugins`：Codex app 插件相关内容
- `docs`：文档站

因此它更接近“创作工作台前端 + 本地 Agent 工具”，而不是未来电商平台的完整服务端。

---

## 2. 技术架构

### 2.1 前端

`web/package.json` 显示：

- React 19
- Vite 7
- TypeScript
- React Router 7
- Ant Design
- Tailwind CSS
- Zustand
- Axios
- LocalForage
- React Query
- CodeMirror

前端路由包括：

```text
/
/image
/video
/assets
/prompts
/canvas
/canvas/:id
/config
```

### 2.2 Canvas 实现方式

重要结论：

> 当前版本没有使用 `reactflow` 或 `@xyflow/react`。

它是自研 Canvas，主要由以下部分组成：

- `web/src/components/canvas/infinite-canvas.tsx`
- `web/src/components/canvas/canvas-node.tsx`
- `web/src/components/canvas/canvas-connections.tsx`
- `web/src/pages/canvas/project.tsx`
- `web/src/types/canvas.ts`
- `web/src/lib/canvas/*`

实现方式：

```text
HTML 容器
  -> viewport transform: translate(x, y) scale(k)
      -> HTML 节点
      -> SVG 连线
      -> CSS 网格背景
```

视口结构：

```ts
type ViewportTransform = {
  x: number;
  y: number;
  k: number;
};
```

源码直接处理：

- 鼠标滚轮缩放
- 中键拖动画布
- Space 临时平移
- Ctrl 临时平移
- Pointer Capture
- `requestAnimationFrame` 合并视口更新
- 选择框
- 节点移动
- 节点缩放
- 连线命中区域
- 小地图
- 节点分组

### 2.3 节点和连线模型

核心节点结构：

```ts
type CanvasNodeData = {
  id: string;
  type: CanvasNodeTypeId;
  title: string;
  position: { x: number; y: number };
  width: number;
  height: number;
  metadata?: CanvasNodeMetadata;
};
```

内置节点：

```text
image
text
config
video
audio
group
```

连线结构：

```ts
type CanvasConnection = {
  id: string;
  fromNodeId: string;
  toNodeId: string;
};
```

它没有 React Flow 那样的标准 `sourceHandle` / `targetHandle` 数据模型，而是通过节点左右两侧和自定义几何规则推导连线。

### 2.4 状态管理

主要使用 Zustand：

- `useCanvasStore`
- `useCanvasUiStore`
- `usePluginStore`
- `useConfigStore`
- `useAssetStore`
- `usePromptSourceStore`
- `useAgentStore`
- `useWorkbenchAgentStore`

画布项目结构中包含：

- 项目标题
- 节点
- 连线
- 对话会话
- 当前对话 ID
- 背景模式
- 是否显示图片信息
- 视口

画布页面的交互状态仍大量使用 React `useState` 和 `useRef`，例如：

- 当前选中节点
- 正在连接的节点
- 框选状态
- 拖动状态
- 当前生成节点
- 弹窗状态
- 撤销/重做历史

这说明项目采用的是：

```text
持久化业务状态 -> Zustand
页面交互瞬时状态 -> React State/Ref
```

---

## 3. 数据持久化方式

### 3.1 浏览器本地存储

项目默认把以下内容放在浏览器：

- AI Base URL
- API Key
- 画布项目
- 节点和连线
- 本地素材
- 生成记录
- 插件源码
- Prompt 来源

存储方式：

```text
LocalForage
  -> IndexedDB
  -> localStorage fallback
```

源码中的关键实现：

- `web/src/lib/localforage-storage.ts`
- `web/src/services/image-storage.ts`
- `web/src/services/file-storage.ts`
- `web/src/stores/canvas/use-canvas-store.ts`
- `web/src/stores/use-asset-store.ts`
- `web/src/stores/use-config-store.ts`

### 3.2 对 commerce-studio 的影响

这一套适合个人工具，但不适合作为电商平台的正式存储，因为它无法天然提供：

- 多用户
- RBAC
- 数据范围
- 部门和团队
- 服务端审计
- 产品记忆共享
- 统一模型密钥管理
- 生成任务恢复
- 成本统计
- 服务端备份

未来必须改成：

```text
浏览器
  -> NestJS API
      -> MySQL
      -> 文件/对象存储
      -> Model Gateway
```

浏览器本地存储只保留：

- UI 偏好
- 当前画布临时草稿缓存
- 临时筛选条件
- 非敏感的交互状态

API Key、产品、素材、Prompt、任务和历史都必须进入服务端。

---

## 4. 模型 API 设计

### 4.1 当前项目方式

当前项目的图片、视频、音频和文本请求由浏览器直接发送：

```text
浏览器
  -> 用户配置的 Base URL
      -> 官方 API 或中转 API
```

它通过 `useConfigStore` 保存：

- Base URL
- API Key
- API 格式
- 模型名
- 模型能力
- 生成参数
- 自定义模型调用脚本

已观察到的适配能力：

- OpenAI 风格接口
- Gemini 风格接口
- Ark 风格接口
- 自定义模型脚本
- 图片生成
- 图片编辑
- 视频异步任务轮询
- 音频生成
- 文本流式输出

### 4.2 可复用的设计思想

可以参考：

- `ModelCapability` 能力分类
- `ModelChannel` 渠道配置
- 模型与渠道绑定
- 生成参数按能力区分
- 统一解析错误消息
- `AbortSignal` 取消请求
- 视频任务创建和轮询分开
- 自定义 Provider Adapter 的思路

### 4.3 必须重写的部分

不能直接使用浏览器直连方式：

- API Key 会暴露给用户浏览器。
- 无法统一计算成本。
- 无法统一限流。
- 无法可靠记录供应商任务。
- 页面关闭可能导致生成任务中断。
- 无法保证团队成员使用同一产品记忆。
- 无法做服务端重试和恢复。

commerce-studio 必须改成：

```text
页面
  -> POST /api/v1/generation-tasks
      -> 保存任务和 Prompt 快照
      -> 单 Worker 执行
          -> Model Gateway
              -> 官方 Provider
              -> OpenAI Compatible Provider
              -> 图片 Provider
              -> 视频 Provider
```

---

## 5. Canvas 可复用能力

### 5.1 可以参考或重写复用

高价值部分：

1. `ViewportTransform`
   - `x`
   - `y`
   - `k`
   - 以鼠标位置为中心缩放
   - 缩放范围限制

2. 自研 Canvas 交互
   - 平移
   - 框选
   - 多选
   - 节点拖动
   - 节点缩放
   - 节点复制
   - 节点删除
   - 连线
   - 小地图
   - 撤销重做

3. 节点数据设计
   - 节点 ID
   - 节点类型
   - 标题
   - 位置
   - 尺寸
   - metadata

4. 节点注册表
   - `registerNodeDefinitions`
   - `unregisterPluginNodes`
   - `getNodeDefinition`
   - `getNodeSpec`

5. 插件宿主接口
   - 节点渲染
   - 节点面板
   - 工具栏
   - 节点上下游访问
   - 事件总线
   - 宿主 AI 能力

6. 画布 Agent 操作协议
   - `add_node`
   - `update_node`
   - `delete_node`
   - `connect_nodes`
   - `set_viewport`
   - `select_nodes`
   - `run_generation`

7. 生成节点上下文
   - 上游节点作为参考输入
   - Prompt 节点和配置节点分离
   - 生成结果写回画布

### 5.2 不建议直接复制

- 整个 `project.tsx`
- 整个 `CanvasNode`
- 整个本地存储层
- 浏览器 API Key 配置
- 浏览器端视频轮询
- 远程插件任意 JavaScript 执行
- 直接把 `metadata` 作为所有业务字段

原因：

- 文件过大且页面耦合严重。
- 生成任务、素材、弹窗和 Canvas 状态混在一个页面中。
- 与产品中心、RBAC、服务端任务不匹配。
- 直接复制会把浏览器本地存储设计带入主项目。

---

## 6. 插件系统风险

当前插件机制：

```text
下载远程 JavaScript
  -> Blob URL
  -> 动态 import
  -> 注册节点和 CSS
  -> 注入宿主 React Runtime
```

相关实现：

- `plugin-loader.ts`
- `plugin-runtime.ts`
- `plugin-registry.ts`
- `types/canvas-plugin.ts`

优点：

- 节点扩展容易。
- 插件可以定义节点、面板和工具栏。
- 插件可以访问宿主 Canvas 能力。
- 插件可以复用宿主的图片、视频和文本生成能力。

风险：

- 远程 JavaScript 具有浏览器执行能力。
- 插件源码可能读取可访问的页面状态。
- 插件可注入 CSS。
- 插件更新不一定经过代码审查。
- 不适合企业后台直接允许任意远程插件。

commerce-studio 的改造建议：

- 第一阶段关闭远程任意插件安装。
- 只允许编译时内置节点。
- 后续插件必须经过管理员审核。
- 插件包必须锁定版本和哈希。
- 插件只能访问明确的 Host API。
- 插件不能读取 API Key。
- 插件不能自行访问内部管理 API。
- 插件权限必须纳入 RBAC。

---

## 7. Canvas Agent 和长连接

### 7.1 当前 Canvas Agent

`canvas-agent` 是独立的本地 Node 服务：

- Express HTTP 服务
- SSE 事件通道
- MCP Server
- Codex app-server 连接
- Claude Code 适配保留
- Canvas 状态同步
- Canvas 操作工具
- 本地附件和日志

它默认监听：

```text
127.0.0.1
```

并使用 token 和 Origin 绑定保护连接。

### 7.2 可借鉴部分

- 事件流按 `threadId`、`turnId`、`itemId` 归属。
- 读画布状态和执行画布操作分离。
- Canvas 操作使用结构化 `ops`。
- 连接断开时以持久化状态为准。
- 工具入参使用 Zod 校验。
- 事件采用增量广播。

### 7.3 不纳入 2C2G 服务器主链路

当前本地 Canvas Agent 依赖：

- `@openai/codex`
- MCP SDK
- Codex app-server
- 本地线程和技能存储
- 本地用户电脑文件

它是桌面辅助工具，不是生产服务器的必要组件。

未来产品可以保留一个简化的“Prompt/Canvas Assistant”，但必须调用：

```text
commerce-studio API
  -> 权限检查
  -> Product Memory
  -> Prompt Engine
  -> Canvas 操作
```

不能直接把本地 Codex Agent 暴露到公网。

---

## 8. 与 React Flow 的路线判断

### 8.1 infinite-canvas 自研 Canvas

优点：

- 交互自由。
- 节点视觉可完全控制。
- 不受 React Flow 数据模型限制。
- 已有创作型节点和素材交互。
- 对媒体创作更自然。

缺点：

- 连接规则、选择、拖动、键盘、撤销重做都要自己维护。
- 复杂业务节点越多，维护成本越高。
- 多人协作、可访问性和生态能力需要自己补。
- 与标准工作流执行器的兼容成本高。

### 8.2 React Flow

优点：

- 节点、边、Handle、视口和状态模型成熟。
- 更适合 Product -> Memory -> Prompt -> Model -> Result 工作流。
- 更容易实现标准化节点和执行图。
- 后续可接工作流校验、序列化和协作能力。

缺点：

- 需要重新实现当前创作型节点 UI。
- 复杂图片编辑、批量结果和自由布局仍需定制。

### 8.3 最终路线

主项目继续使用 React Flow 作为业务 Canvas 基础。

从 infinite-canvas 借鉴：

- 创作型节点外观
- 媒体预览
- 节点工具栏
- Prompt 面板
- 上下游引用
- 画布 Agent 操作协议
- 画布快捷键和缩放体验

不建议把 infinite-canvas 的自研 Canvas 整体迁移进主项目。

---

## 9. 适合直接复用的模块清单

| 模块 | 处理建议 |
| --- | --- |
| 视口缩放和平移算法 | 参考重写 |
| Canvas 网格背景 | 参考重写 |
| 节点卡片视觉 | 参考设计 |
| 图片/视频节点预览 | 参考重写 |
| 节点状态展示 | 参考重写 |
| Prompt 节点交互 | 参考重写 |
| 节点操作菜单 | 参考重写 |
| 小地图思路 | 参考实现 |
| 撤销重做结构 | 参考实现 |
| 节点注册表 | 设计上复用 |
| 插件 Host API | 安全收敛后复用 |
| Canvas Ops | 设计上复用 |
| 本地 Agent 事件归属 | 设计上复用 |
| 浏览器 API Key 存储 | 不复用 |
| IndexedDB 业务持久化 | 不复用 |
| 浏览器直连模型 API | 不复用 |
| 远程任意 JS 插件 | 不复用 |
| 本地 Codex Agent 服务 | 不纳入主服务器 |

---

## 10. 对 commerce-studio 的架构结论

### 10.1 继续采用

```text
NestJS
AdminJS
React
React Flow
Prisma
MySQL
Nginx
Zustand（仅前端交互状态）
```

### 10.2 重新设计

必须由主项目自建：

- 产品中心
- SKU 和产品素材
- Product Memory
- Product Memory 快照
- Prompt Engine
- RBAC 和数据范围
- Model Gateway
- 官方 API Adapter
- OpenAI 兼容 Adapter
- 图片任务
- 视频任务
- MySQL 任务恢复
- 成本记录
- 审计日志
- 授权媒体访问

### 10.3 第一批业务 Canvas 节点

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

节点的 `data` 只保存业务引用和配置快照，不保存 API Key 和大文件。

---

## 11. 最终判断

`infinite-canvas v0.15.1` 适合作为：

```text
Canvas 创作体验参考
+ 节点交互参考
+ 图片/视频节点视觉参考
+ 插件 Host API 参考
+ Canvas Agent Ops 参考
```

不适合作为：

```text
完整电商后台
RBAC 基础
服务端数据库基础
统一模型网关
任务队列基础
产品记忆基础
```

最终开发策略：

1. 主项目以 `NestJS + AdminJS + MySQL + React Flow` 为工程骨架。
2. 从 `infinite-canvas` 参考创作型 Canvas 体验。
3. 先实现 Product、Memory、Prompt、Model、Image、Video、Result 节点。
4. 所有模型请求由服务端 Model Gateway 发起。
5. 所有产品、素材、Prompt、任务和历史由 MySQL 管理。
6. 2C2G 版本使用 MySQL 持久化任务表和单 Worker。
7. 暂时不纳入 `canvas-agent`、Codex MCP 和远程任意插件运行时。
