import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type Node,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { api, streamGeneration } from "./api";

type User = {
  id: string;
  email: string;
  displayName: string;
  roles: string[];
  permissions: string[];
};

type Product = {
  id: string;
  name: string;
  code: string;
  brand?: string | null;
  category?: string | null;
  description?: string | null;
  variants?: Array<{ id: string; sku: string; name?: string | null }>;
};

type ModelProfile = {
  id: string;
  name: string;
  capability: Record<string, unknown>;
  provider?: { id: string; name: string };
};

type Task = {
  id: string;
  status: string;
  type: string;
  idea: string;
  product?: { name: string; code: string };
  modelProfile?: { name: string };
};

type View =
  | "overview"
  | "products"
  | "prompt"
  | "generate"
  | "canvas"
  | "tasks";

const starterNodes: Node[] = [
  {
    id: "product",
    type: "input",
    position: { x: 80, y: 160 },
    data: { label: "Product · 产品" },
  },
  {
    id: "memory",
    position: { x: 340, y: 160 },
    data: { label: "Memory · 产品记忆" },
  },
  {
    id: "prompt",
    position: { x: 620, y: 160 },
    data: { label: "Prompt · Prompt Engine" },
  },
  {
    id: "generation",
    position: { x: 940, y: 160 },
    data: { label: "Generation · 图片 / 视频" },
  },
  {
    id: "result",
    type: "output",
    position: { x: 1260, y: 160 },
    data: { label: "Result · 结果" },
  },
];

const starterEdges: Edge[] = [
  { id: "product-memory", source: "product", target: "memory", animated: true },
  { id: "memory-prompt", source: "memory", target: "prompt", animated: true },
  {
    id: "prompt-generation",
    source: "prompt",
    target: "generation",
    animated: true,
  },
  {
    id: "generation-result",
    source: "generation",
    target: "result",
    animated: true,
  },
];

export function App() {
  const [user, setUser] = useState<User | null>(null);
  const [view, setView] = useState<View>("overview");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [products, setProducts] = useState<Product[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [profiles, setProfiles] = useState<ModelProfile[]>([]);
  const [selectedProductId, setSelectedProductId] = useState("");
  const [prompt, setPrompt] = useState<{
    promptText?: string;
    negativePrompt?: string;
    memoryVersion?: number;
  }>({});
  const [activeTask, setActiveTask] = useState<Task | null>(null);

  const loadWorkspace = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const current = await api<User>("/auth/me");
      setUser(current);
      const [productData, taskData] = await Promise.all([
        api<Product[]>("/products"),
        api<Task[]>("/generation-tasks"),
      ]);
      setProducts(productData ?? []);
      setTasks(taskData ?? []);
      setSelectedProductId(
        (currentProductId) => currentProductId || productData?.[0]?.id || "",
      );
    } catch (err) {
      if (err instanceof Error && !err.message.includes("401"))
        setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  async function logout() {
    await api("/auth/logout", { method: "POST" });
    setUser(null);
  }

  if (!user) {
    return <Login onLogin={(nextUser) => setUser(nextUser)} error={error} />;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark">CS</div>
          <div>
            <strong>Commerce Studio</strong>
            <span>AI 产品创作工作台</span>
          </div>
        </div>
        <nav className="nav-list">
          <NavItem
            label="总览"
            active={view === "overview"}
            onClick={() => setView("overview")}
          />
          <NavItem
            label="产品中心"
            active={view === "products"}
            onClick={() => setView("products")}
          />
          <NavItem
            label="Prompt Engine"
            active={view === "prompt"}
            onClick={() => setView("prompt")}
          />
          <NavItem
            label="图片 / 视频生成"
            active={view === "generate"}
            onClick={() => setView("generate")}
          />
          <NavItem
            label="Infinite Canvas"
            active={view === "canvas"}
            onClick={() => setView("canvas")}
          />
          <NavItem
            label="生成历史"
            active={view === "tasks"}
            onClick={() => setView("tasks")}
          />
          <a
            className="nav-item external"
            href="/admin"
            target="_blank"
            rel="noreferrer"
          >
            系统管理 <span>↗</span>
          </a>
        </nav>
        <div className="sidebar-footer">
          <div className="status-dot" />
          <span>外置 MySQL 模式</span>
        </div>
      </aside>
      <main className="main-panel">
        <header className="topbar">
          <div>
            <span className="eyebrow">WORKSPACE</span>
            <h1>{viewTitle(view)}</h1>
          </div>
          <div className="topbar-actions">
            <span className="user-chip">{user.displayName}</span>
            <button className="button ghost" onClick={() => void logout()}>
              退出
            </button>
          </div>
        </header>
        {error && <div className="alert error">{error}</div>}
        {loading ? (
          <div className="loading-panel">正在加载工作台...</div>
        ) : (
          <section className="content">
            {view === "overview" && (
              <Overview
                products={products}
                tasks={tasks}
                onNavigate={setView}
              />
            )}
            {view === "products" && (
              <ProductsView
                products={products}
                selectedProductId={selectedProductId}
                onSelect={setSelectedProductId}
                onCreated={async () => {
                  const data = await api<Product[]>("/products");
                  setProducts(data ?? []);
                }}
              />
            )}
            {view === "prompt" && (
              <PromptView
                products={products}
                selectedProductId={selectedProductId}
                onProductChange={setSelectedProductId}
                prompt={prompt}
                onCompiled={setPrompt}
              />
            )}
            {view === "generate" && (
              <GenerateView
                products={products}
                profiles={profiles}
                selectedProductId={selectedProductId}
                onProductChange={setSelectedProductId}
                onProfiles={setProfiles}
                onCreated={(task) => {
                  setActiveTask(task);
                  setTasks((current) => [task, ...current]);
                }}
              />
            )}
            {view === "canvas" && (
              <CanvasView selectedProductId={selectedProductId} />
            )}
            {view === "tasks" && (
              <TasksView
                tasks={tasks}
                activeTask={activeTask}
                onSelect={setActiveTask}
              />
            )}
          </section>
        )}
      </main>
    </div>
  );
}

function Login({
  onLogin,
  error,
}: {
  onLogin: (user: User) => void;
  error: string;
}) {
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("change-me");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState(error);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setMessage("");
    try {
      const user = await api<User>("/auth/login", {
        method: "POST",
        bodyJson: { email, password },
      });
      onLogin(user);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-screen">
      <div className="login-visual">
        <div className="visual-grid" />
        <div className="visual-copy">
          <span className="eyebrow">PRODUCT MEMORY · PROMPT · GENERATION</span>
          <h1>让每一次生成都记得你的产品。</h1>
          <p>从产品资料到可执行的图片与视频创意，工作流在一个画布里完成。</p>
        </div>
      </div>
      <form className="login-card" onSubmit={submit}>
        <div className="brand-lockup compact">
          <div className="brand-mark">CS</div>
          <div>
            <strong>Commerce Studio</strong>
            <span>AI 电商视觉工作台</span>
          </div>
        </div>
        <div className="form-heading">
          <span className="eyebrow">SIGN IN</span>
          <h2>进入工作台</h2>
        </div>
        <label>
          邮箱
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            type="email"
          />
        </label>
        <label>
          密码
          <input
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            type="password"
          />
        </label>
        {message && <div className="alert error">{message}</div>}
        <button className="button primary wide" disabled={submitting}>
          {submitting ? "正在登录..." : "登录工作台"}
        </button>
        <span className="form-note">
          首次运行请先执行 Prisma migrate 和 seed。
        </span>
      </form>
    </div>
  );
}

function Overview({
  products,
  tasks,
  onNavigate,
}: {
  products: Product[];
  tasks: Task[];
  onNavigate: (view: View) => void;
}) {
  const running = tasks.filter((task) =>
    ["QUEUED", "RUNNING", "PROVIDER_SUBMITTED", "PROVIDER_PROCESSING"].includes(
      task.status,
    ),
  ).length;
  return (
    <>
      <div className="hero-band">
        <div>
          <span className="eyebrow">CREATIVE OPERATIONS</span>
          <h2>从产品记忆开始，做出一致的视觉内容。</h2>
          <p>产品、Prompt、模型和结果在同一个业务工作台里持续沉淀。</p>
        </div>
        <button
          className="button primary"
          onClick={() => onNavigate("generate")}
        >
          开始生成
        </button>
      </div>
      <div className="metric-grid">
        <Metric
          label="产品资料"
          value={products.length}
          caption="已建立的产品数据源"
        />
        <Metric
          label="生成任务"
          value={tasks.length}
          caption="图片与视频任务记录"
        />
        <Metric label="进行中" value={running} caption="正在等待或处理" />
        <Metric label="Canvas" value="∞" caption="可组合的创作空间" />
      </div>
      <div className="section-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">FLOW</span>
              <h3>推荐工作流</h3>
            </div>
            <button
              className="button ghost small"
              onClick={() => onNavigate("canvas")}
            >
              打开 Canvas
            </button>
          </div>
          <div className="flow-row">
            <FlowStep
              index="01"
              title="选择产品"
              detail="调用产品资料和多角度素材"
            />
            <FlowStep
              index="02"
              title="合并记忆"
              detail="读取品牌、事实和禁止规则"
            />
            <FlowStep
              index="03"
              title="生成结果"
              detail="提交图片或视频异步任务"
            />
          </div>
        </section>
        <section className="panel dark-panel">
          <span className="eyebrow">SYSTEM</span>
          <h3>服务状态</h3>
          <div className="system-row">
            <span className="status-dot" /> API 应用在线
          </div>
          <div className="system-row">
            <span className="status-dot amber" /> MySQL 等待外置连接
          </div>
          <div className="system-row">
            <span className="status-dot blue" /> 模型网关已就绪
          </div>
        </section>
      </div>
    </>
  );
}

function ProductsView({
  products,
  selectedProductId,
  onSelect,
  onCreated,
}: {
  products: Product[];
  selectedProductId: string;
  onSelect: (id: string) => void;
  onCreated: () => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [brand, setBrand] = useState("");
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState("");

  async function createProduct(event: React.FormEvent) {
    event.preventDefault();
    setCreating(true);
    setMessage("");
    try {
      await api("/products", {
        method: "POST",
        bodyJson: { name, code, brand },
      });
      setName("");
      setCode("");
      setBrand("");
      await onCreated();
      setMessage("产品已创建");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "创建失败");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="two-column">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">PRODUCT CENTER</span>
            <h3>产品资料</h3>
          </div>
          <span className="count-badge">{products.length}</span>
        </div>
        <div className="product-list">
          {products.length === 0 && <EmptyState text="还没有产品资料" />}
          {products.map((product) => (
            <button
              className={`product-row ${selectedProductId === product.id ? "selected" : ""}`}
              key={product.id}
              onClick={() => onSelect(product.id)}
            >
              <div className="product-avatar">{product.name.slice(0, 1)}</div>
              <div className="product-row-copy">
                <strong>{product.name}</strong>
                <span>
                  {product.code} · {product.brand || "未设置品牌"}
                </span>
              </div>
              <span className="row-arrow">→</span>
            </button>
          ))}
        </div>
      </section>
      <form className="panel form-panel" onSubmit={createProduct}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">NEW PRODUCT</span>
            <h3>建立产品数据源</h3>
          </div>
        </div>
        <label>
          产品名称
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            required
            placeholder="例如：高级无线耳机"
          />
        </label>
        <label>
          产品编码
          <input
            value={code}
            onChange={(event) => setCode(event.target.value)}
            required
            placeholder="例如：HEADPHONE-001"
          />
        </label>
        <label>
          品牌
          <input
            value={brand}
            onChange={(event) => setBrand(event.target.value)}
            placeholder="品牌名称"
          />
        </label>
        {message && <div className="alert success">{message}</div>}
        <button className="button primary" disabled={creating}>
          {creating ? "创建中..." : "创建产品"}
        </button>
      </form>
    </div>
  );
}

function PromptView({
  products,
  selectedProductId,
  onProductChange,
  prompt,
  onCompiled,
}: {
  products: Product[];
  selectedProductId: string;
  onProductChange: (id: string) => void;
  prompt: {
    promptText?: string;
    negativePrompt?: string;
    memoryVersion?: number;
  };
  onCompiled: (prompt: {
    promptText?: string;
    negativePrompt?: string;
    memoryVersion?: number;
  }) => void;
}) {
  const [idea, setIdea] = useState("生成一个高级汽车广告视频");
  const [type, setType] = useState<"IMAGE" | "VIDEO">("VIDEO");
  const [compiling, setCompiling] = useState(false);
  const [message, setMessage] = useState("");
  async function compile(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedProductId) return setMessage("请先选择产品");
    setCompiling(true);
    setMessage("");
    try {
      const data = await api<{
        promptText: string;
        negativePrompt: string;
        memoryVersion: number;
      }>(`/products/${selectedProductId}/prompt/compile`, {
        method: "POST",
        bodyJson: { idea, type },
      });
      onCompiled(data);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Prompt 编译失败");
    } finally {
      setCompiling(false);
    }
  }
  return (
    <div className="two-column prompt-layout">
      <form className="panel form-panel" onSubmit={compile}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">PROMPT ENGINE</span>
            <h3>把创意变成可执行 Prompt</h3>
          </div>
        </div>
        <label>
          产品
          <select
            value={selectedProductId}
            onChange={(event) => onProductChange(event.target.value)}
          >
            <option value="">选择产品</option>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.name}
              </option>
            ))}
          </select>
        </label>
        <div className="segmented">
          <button
            type="button"
            className={type === "IMAGE" ? "active" : ""}
            onClick={() => setType("IMAGE")}
          >
            图片
          </button>
          <button
            type="button"
            className={type === "VIDEO" ? "active" : ""}
            onClick={() => setType("VIDEO")}
          >
            视频
          </button>
        </div>
        <label>
          用户创意
          <textarea
            value={idea}
            onChange={(event) => setIdea(event.target.value)}
            rows={8}
            placeholder="描述你想要的场景、镜头和氛围"
          />
        </label>
        {message && <div className="alert error">{message}</div>}
        <button className="button primary" disabled={compiling}>
          {compiling ? "编译中..." : "生成 Prompt 预览"}
        </button>
      </form>
      <section className="panel prompt-result">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">PROMPT SNAPSHOT</span>
            <h3>当前编译结果</h3>
          </div>
          {prompt.memoryVersion ? (
            <span className="version-tag">Memory v{prompt.memoryVersion}</span>
          ) : null}
        </div>
        <div className="prompt-block">
          <span>正向 Prompt</span>
          <p>{prompt.promptText || "编译后显示完整 Prompt"}</p>
        </div>
        <div className="prompt-block negative">
          <span>禁止规则</span>
          <p>{prompt.negativePrompt || "读取产品记忆后显示禁止规则"}</p>
        </div>
      </section>
    </div>
  );
}

function GenerateView({
  products,
  profiles,
  selectedProductId,
  onProductChange,
  onProfiles,
  onCreated,
}: {
  products: Product[];
  profiles: ModelProfile[];
  selectedProductId: string;
  onProductChange: (id: string) => void;
  onProfiles: (profiles: ModelProfile[]) => void;
  onCreated: (task: Task) => void;
}) {
  const [idea, setIdea] = useState("生成一组高级电商主图");
  const [type, setType] = useState<"IMAGE" | "VIDEO">("IMAGE");
  const [profileId, setProfileId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (profiles.length) return;
    void api<Array<{ id: string; name: string; profiles?: ModelProfile[] }>>(
      "/model-gateway/providers",
    )
      .then((providers) => {
        const next = (providers ?? []).flatMap((provider: any) =>
          (provider.profiles ?? []).map((profile: ModelProfile) => ({
            ...profile,
            provider: { id: provider.id, name: provider.name },
          })),
        );
        onProfiles(next);
        setProfileId(next[0]?.id ?? "");
      })
      .catch(() => undefined);
  }, [profiles.length, onProfiles]);
  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedProductId) return setMessage("请先选择产品");
    if (!profileId) return setMessage("请先在系统管理中配置模型");
    setSubmitting(true);
    setMessage("");
    try {
      const task = await api<Task>("/generation-tasks", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        bodyJson: {
          productId: selectedProductId,
          modelProfileId: profileId,
          type,
          idea,
        },
      });
      onCreated(task);
      setMessage("任务已进入队列");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "任务提交失败");
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <div className="two-column">
      <form className="panel form-panel" onSubmit={submit}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">GENERATION TASK</span>
            <h3>提交生成任务</h3>
          </div>
        </div>
        <label>
          产品
          <select
            value={selectedProductId}
            onChange={(event) => onProductChange(event.target.value)}
          >
            <option value="">选择产品</option>
            {products.map((product) => (
              <option key={product.id} value={product.id}>
                {product.name}
              </option>
            ))}
          </select>
        </label>
        <div className="segmented">
          <button
            type="button"
            className={type === "IMAGE" ? "active" : ""}
            onClick={() => setType("IMAGE")}
          >
            图片
          </button>
          <button
            type="button"
            className={type === "VIDEO" ? "active" : ""}
            onClick={() => setType("VIDEO")}
          >
            视频
          </button>
        </div>
        <label>
          模型配置
          <select
            value={profileId}
            onChange={(event) => setProfileId(event.target.value)}
          >
            <option value="">选择模型</option>
            {profiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.name} · {profile.provider?.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          创意描述
          <textarea
            value={idea}
            onChange={(event) => setIdea(event.target.value)}
            rows={7}
          />
        </label>
        {message && (
          <div
            className={`alert ${message.includes("已进入") ? "success" : "error"}`}
          >
            {message}
          </div>
        )}
        <button className="button primary" disabled={submitting}>
          {submitting ? "提交中..." : "进入生成队列"}
        </button>
      </form>
      <section className="panel empty-generation">
        <div className="generation-icon">✦</div>
        <span className="eyebrow">ASYNC GENERATION</span>
        <h3>任务会在服务端执行</h3>
        <p>
          页面只接收任务状态，模型密钥、轮询和结果下载都由 Model Gateway 处理。
        </p>
        <div className="mini-status">
          <span className="status-dot blue" /> MySQL 任务持久化
        </div>
        <div className="mini-status">
          <span className="status-dot blue" /> SSE 状态推送
        </div>
        <div className="mini-status">
          <span className="status-dot blue" /> 单 Worker 恢复机制
        </div>
      </section>
    </div>
  );
}

function CanvasView({ selectedProductId }: { selectedProductId: string }) {
  const [nodes, setNodes, onNodesChange] = useNodesState(starterNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(starterEdges);
  const [instance, setInstance] = useState<ReactFlowInstance | null>(null);
  const [canvasId, setCanvasId] = useState("");
  const [message, setMessage] = useState("");
  const onConnect = useCallback(
    (params: Connection) =>
      setEdges((current) => addEdge({ ...params, animated: true }, current)),
    [setEdges],
  );
  useEffect(() => {
    void api<Array<{ id: string; nodes: Node[]; edges: Edge[] }>>("/canvas")
      .then((value) => {
        const first = value?.[0];
        if (!first) return;
        setCanvasId(first.id);
        if (first.nodes?.length) setNodes(first.nodes);
        if (first.edges?.length) setEdges(first.edges);
      })
      .catch(() => undefined);
  }, [setEdges, setNodes]);
  async function save() {
    setMessage("");
    try {
      const payload = {
        name: "Commerce Studio Canvas",
        productId: selectedProductId || undefined,
        nodes,
        edges,
        viewport: instance?.getViewport() ?? { x: 0, y: 0, zoom: 1 },
      };
      if (!canvasId) {
        const created = await api<{ id: string }>("/canvas", {
          method: "POST",
          bodyJson: payload,
        });
        setCanvasId(created.id);
      } else {
        await api(`/canvas/${canvasId}`, {
          method: "PATCH",
          bodyJson: payload,
        });
      }
      setMessage("Canvas 已保存");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Canvas 保存失败");
    }
  }
  return (
    <section className="canvas-panel">
      <div className="canvas-toolbar">
        <div>
          <span className="eyebrow">REACT FLOW CANVAS</span>
          <h3>产品视觉工作流</h3>
        </div>
        <div className="toolbar-actions">
          {message && <span className="toolbar-message">{message}</span>}
          <button className="button primary small" onClick={() => void save()}>
            保存画布
          </button>
        </div>
      </div>
      <div className="canvas-stage">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onInit={setInstance}
          fitView
        >
          <Background color="#d7deea" gap={24} size={1} />
          <Controls />
          <MiniMap nodeColor="#84a9ff" />
        </ReactFlow>
      </div>
    </section>
  );
}

function TasksView({
  tasks,
  activeTask,
  onSelect,
}: {
  tasks: Task[];
  activeTask: Task | null;
  onSelect: (task: Task) => void;
}) {
  return (
    <div className="two-column tasks-layout">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">HISTORY</span>
            <h3>生成任务</h3>
          </div>
          <span className="count-badge">{tasks.length}</span>
        </div>
        <div className="task-list">
          {tasks.length === 0 && <EmptyState text="还没有生成任务" />}
          {tasks.map((task) => (
            <button
              className={`task-row ${activeTask?.id === task.id ? "selected" : ""}`}
              key={task.id}
              onClick={() => onSelect(task)}
            >
              <div>
                <strong>{task.idea}</strong>
                <span>
                  {task.product?.name || "未知产品"} ·{" "}
                  {task.modelProfile?.name || "未配置模型"}
                </span>
              </div>
              <StatusBadge status={task.status} />
            </button>
          ))}
        </div>
      </section>
      <section className="panel task-detail">
        {activeTask ? (
          <TaskDetail task={activeTask} />
        ) : (
          <EmptyState text="选择一个任务查看状态" />
        )}
      </section>
    </div>
  );
}

function TaskDetail({ task }: { task: Task }) {
  const [events, setEvents] = useState<string[]>([]);
  useEffect(() => {
    const close = streamGeneration(task.id, (event) =>
      setEvents((current) =>
        [`${event.type}: ${event.data}`, ...current].slice(0, 20),
      ),
    );
    return close;
  }, [task.id]);
  return (
    <>
      <div className="panel-heading">
        <div>
          <span className="eyebrow">TASK DETAIL</span>
          <h3>{task.idea}</h3>
        </div>
        <StatusBadge status={task.status} />
      </div>
      <div className="detail-grid">
        <div>
          <span>产品</span>
          <strong>{task.product?.name || "—"}</strong>
        </div>
        <div>
          <span>模型</span>
          <strong>{task.modelProfile?.name || "—"}</strong>
        </div>
        <div>
          <span>任务 ID</span>
          <strong className="mono">{task.id}</strong>
        </div>
      </div>
      <div className="event-log">
        {events.length
          ? events.map((item, index) => (
              <div key={`${item}-${index}`}>{item}</div>
            ))
          : "等待任务事件..."}
      </div>
    </>
  );
}

function NavItem({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button className={`nav-item ${active ? "active" : ""}`} onClick={onClick}>
      <span className="nav-dot" />
      {label}
    </button>
  );
}
function Metric({
  label,
  value,
  caption,
}: {
  label: string;
  value: string | number;
  caption: string;
}) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{caption}</small>
    </div>
  );
}
function FlowStep({
  index,
  title,
  detail,
}: {
  index: string;
  title: string;
  detail: string;
}) {
  return (
    <div className="flow-step">
      <span>{index}</span>
      <strong>{title}</strong>
      <small>{detail}</small>
    </div>
  );
}
function StatusBadge({ status }: { status: string }) {
  const label: Record<string, string> = {
    QUEUED: "排队中",
    RUNNING: "执行中",
    PROVIDER_SUBMITTED: "已提交",
    PROVIDER_PROCESSING: "处理中",
    SUCCEEDED: "成功",
    FAILED: "失败",
    CANCELLED: "已取消",
    RETRY_WAITING: "等待重试",
  };
  return (
    <span className={`status-badge ${status.toLowerCase()}`}>
      {label[status] || status}
    </span>
  );
}
function EmptyState({ text }: { text: string }) {
  return (
    <div className="empty-state">
      <span>○</span>
      <p>{text}</p>
    </div>
  );
}
function viewTitle(view: View) {
  return {
    overview: "工作台总览",
    products: "产品中心",
    prompt: "Prompt Engine",
    generate: "图片 / 视频生成",
    canvas: "Infinite Canvas",
    tasks: "生成历史",
  }[view];
}
