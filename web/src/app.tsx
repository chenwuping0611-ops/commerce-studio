import { useCallback, useEffect, useState } from "react";
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

import { api, streamGeneration, upload } from "./api";

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
  status?: string | null;
  variants?: Array<{
    id: string;
    sku: string;
    name?: string | null;
    color?: string | null;
    size?: string | null;
    material?: string | null;
  }>;
  assets?: ProductAsset[];
};

type ProductAsset = {
  id: string;
  type: string;
  view?: string | null;
  originalName?: string | null;
  mimeType: string;
  byteSize: number;
  reviewStatus: string;
  url: string;
};

type ProductMemory = {
  facts: Array<{ key: string; value: string; source?: string | null }>;
  brandVisual: Array<{ key: string; value: string }>;
  generationRules: Array<{ id: string; rule: string }>;
  forbiddenRules: Array<{ id: string; rule: string }>;
  latestVersion?: { version: number } | null;
};

type ModelProfile = {
  id: string;
  name: string;
  capability: Record<string, unknown>;
  provider?: { id: string; name: string };
  providerId?: string;
};

type ModelProvider = {
  id: string;
  name: string;
  kind: string;
  baseUrl: string;
  apiKeyHint?: string | null;
  enabled: boolean;
  profiles: ModelProfile[];
};

type ManagedUser = {
  id: string;
  email: string;
  displayName: string;
  status: string;
  roles: Array<{ id: string; code: string; name: string }>;
  teams: Array<{ id: string; code: string; name: string; isLead?: boolean }>;
};

type Role = {
  id: string;
  code: string;
  name: string;
  permissions: Array<{ id: string; code: string; name: string }>;
};

type Permission = { id: string; code: string; name: string };

type ManagedTeam = {
  id: string;
  name: string;
  code: string;
  members: Array<{
    id: string;
    email: string;
    displayName: string;
    isLead: boolean;
  }>;
};

type SystemSetting = {
  id: string;
  key: string;
  value: unknown;
  isSecret: boolean;
  configured?: boolean;
};

type AuditLog = {
  id: string;
  action: string;
  resource: string;
  resourceId?: string | null;
  createdAt: string;
  actor?: { email: string; displayName: string } | null;
  metadata?: Record<string, unknown> | null;
};

type Task = {
  id: string;
  status: string;
  type: string;
  idea: string;
  product?: { name: string; code: string };
  modelProfile?: { name: string };
  assets?: Array<{
    id: string;
    mimeType: string;
    byteSize: number;
    url: string;
  }>;
};

type View =
  | "overview"
  | "products"
  | "prompt"
  | "generate"
  | "canvas"
  | "tasks"
  | "account"
  | "admin";

type AdminTab =
  | "users"
  | "roles"
  | "teams"
  | "settings"
  | "providers"
  | "audit";

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
  const [adminTab, setAdminTab] = useState<AdminTab>("users");
  const handleTaskUpdated = useCallback((updated: Task) => {
    setActiveTask(updated);
    setTasks((current) =>
      current.map((item) => (item.id === updated.id ? updated : item)),
    );
  }, []);

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
          <NavItem
            label="个人中心"
            active={view === "account"}
            onClick={() => setView("account")}
          />
          {user.roles.includes("super_admin") && (
            <NavItem
              label="系统配置"
              active={view === "admin"}
              onClick={() => setView("admin")}
            />
          )}
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
                onTaskUpdated={handleTaskUpdated}
              />
            )}
            {view === "account" && (
              <AccountView user={user} onSaved={setUser} />
            )}
            {view === "admin" && (
              <AdminCenter tab={adminTab} onTabChange={setAdminTab} />
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
  const [password, setPassword] = useState("");
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
    <div className="products-layout">
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
      <div className="product-workspace">
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
        {selectedProductId && <ProductDetails productId={selectedProductId} />}
      </div>
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

function ProductDetails({ productId }: { productId: string }) {
  const [product, setProduct] = useState<Product | null>(null);
  const [memory, setMemory] = useState<ProductMemory | null>(null);
  const [assets, setAssets] = useState<ProductAsset[]>([]);
  const [tab, setTab] = useState<"profile" | "memory" | "assets">("profile");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [memoryText, setMemoryText] = useState({
    facts: "",
    brandVisual: "",
    generationRules: "",
    forbiddenRules: "",
  });
  const [assetType, setAssetType] = useState("PRODUCT_REFERENCE");
  const [assetView, setAssetView] = useState("front");

  const reload = useCallback(async () => {
    const [productData, memoryData, assetData] = await Promise.all([
      api<Product>(`/products/${productId}`),
      api<ProductMemory>(`/products/${productId}/memory`),
      api<ProductAsset[]>(`/products/${productId}/assets`),
    ]);
    setProduct(productData);
    setMemory(memoryData);
    setAssets(assetData ?? []);
    setMemoryText({
      facts: (memoryData?.facts ?? [])
        .map((item) => `${item.key}=${item.value}`)
        .join("\n"),
      brandVisual: (memoryData?.brandVisual ?? [])
        .map((item) => `${item.key}=${item.value}`)
        .join("\n"),
      generationRules: (memoryData?.generationRules ?? [])
        .map((item) => item.rule)
        .join("\n"),
      forbiddenRules: (memoryData?.forbiddenRules ?? [])
        .map((item) => item.rule)
        .join("\n"),
    });
  }, [productId]);

  useEffect(() => {
    setMessage("");
    void reload().catch((error) =>
      setMessage(error instanceof Error ? error.message : "产品详情加载失败"),
    );
  }, [reload]);

  async function saveMemory(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      await api(`/products/${productId}/memory`, {
        method: "PUT",
        bodyJson: {
          facts: parseKeyValueLines(memoryText.facts),
          brandVisual: parseKeyValueLines(memoryText.brandVisual),
          generationRules: splitLines(memoryText.generationRules),
          forbiddenRules: splitLines(memoryText.forbiddenRules),
        },
      });
      await reload();
      setMessage("产品记忆已保存并生成新版本");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "产品记忆保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function uploadAsset(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    setMessage("");
    try {
      const formData = new FormData();
      formData.set("file", file);
      formData.set("type", assetType);
      formData.set("view", assetView);
      await upload(`/products/${productId}/assets`, formData);
      await reload();
      setMessage("素材已上传");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "素材上传失败");
    } finally {
      setBusy(false);
    }
  }

  async function removeAsset(assetId: string) {
    if (!window.confirm("确认删除这个产品素材吗？")) return;
    setBusy(true);
    try {
      await api(`/products/${productId}/assets/${assetId}`, {
        method: "DELETE",
      });
      await reload();
      setMessage("素材已删除");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "素材删除失败");
    } finally {
      setBusy(false);
    }
  }

  if (!product) {
    return (
      <section className="panel loading-panel">正在加载产品档案...</section>
    );
  }

  return (
    <section className="panel product-details">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">PRODUCT PROFILE</span>
          <h3>{product.name}</h3>
          <p className="panel-subtitle">
            {product.code} · {product.brand || "未设置品牌"} ·{" "}
            {product.category || "未分类"}
          </p>
        </div>
        <StatusBadge status={product.status ?? "DRAFT"} />
      </div>
      <div className="tab-row">
        <TabButton active={tab === "profile"} onClick={() => setTab("profile")}>
          产品档案
        </TabButton>
        <TabButton active={tab === "memory"} onClick={() => setTab("memory")}>
          Product Memory
        </TabButton>
        <TabButton active={tab === "assets"} onClick={() => setTab("assets")}>
          素材库 · {assets.length}
        </TabButton>
      </div>
      {message && <div className="alert success">{message}</div>}
      {tab === "profile" && (
        <div className="profile-sheet">
          <div className="detail-grid">
            <div>
              <span>产品编码</span>
              <strong className="mono">{product.code}</strong>
            </div>
            <div>
              <span>品牌</span>
              <strong>{product.brand || "—"}</strong>
            </div>
            <div>
              <span>SKU 变体</span>
              <strong>{product.variants?.length ?? 0}</strong>
            </div>
          </div>
          <div className="profile-description">
            <span>产品描述</span>
            <p>{product.description || "尚未填写产品描述。"}</p>
          </div>
          <div className="variant-list">
            <div className="section-label">SKU / 变体</div>
            {product.variants?.length ? (
              product.variants.map((variant) => (
                <div className="compact-row" key={variant.id}>
                  <strong>{variant.sku}</strong>
                  <span>
                    {variant.name || "未命名"} · {variant.color || "未设置颜色"}{" "}
                    · {variant.material || "未设置材质"}
                  </span>
                </div>
              ))
            ) : (
              <EmptyState text="暂未建立 SKU 变体" />
            )}
          </div>
        </div>
      )}
      {tab === "memory" && (
        <form className="memory-editor" onSubmit={saveMemory}>
          <MemoryField
            label="产品事实"
            value={memoryText.facts}
            onChange={(value) =>
              setMemoryText((current) => ({ ...current, facts: value }))
            }
            placeholder={"material=铝合金\ncolor=曜石黑\nsize=标准版"}
          />
          <MemoryField
            label="品牌视觉记忆"
            value={memoryText.brandVisual}
            onChange={(value) =>
              setMemoryText((current) => ({ ...current, brandVisual: value }))
            }
            placeholder={"tone=高级、克制\nlighting=柔和侧光"}
          />
          <MemoryField
            label="生成规则"
            value={memoryText.generationRules}
            onChange={(value) =>
              setMemoryText((current) => ({
                ...current,
                generationRules: value,
              }))
            }
            placeholder={"保持产品主体结构不变\n保持真实材质和颜色"}
          />
          <MemoryField
            label="禁止规则"
            value={memoryText.forbiddenRules}
            onChange={(value) =>
              setMemoryText((current) => ({
                ...current,
                forbiddenRules: value,
              }))
            }
            placeholder={"禁止出现其他品牌 Logo\n禁止添加未授权配件"}
          />
          <div className="form-actions">
            <span className="form-note">
              当前版本：Memory v{memory?.latestVersion?.version ?? 0}
            </span>
            <button className="button primary" disabled={busy}>
              保存产品记忆
            </button>
          </div>
        </form>
      )}
      {tab === "assets" && (
        <div className="asset-library">
          <div className="asset-toolbar">
            <select
              value={assetType}
              onChange={(event) => setAssetType(event.target.value)}
            >
              <option value="PRODUCT_REFERENCE">产品参考图</option>
              <option value="PRODUCT_MAIN">产品主图</option>
              <option value="PRODUCT_DETAIL">产品细节图</option>
              <option value="PRODUCT_SCENE">产品场景图</option>
              <option value="SKU_VIEW">SKU 视角图</option>
            </select>
            <select
              value={assetView}
              onChange={(event) => setAssetView(event.target.value)}
            >
              <option value="front">正面</option>
              <option value="back">背面</option>
              <option value="left">左侧</option>
              <option value="right">右侧</option>
              <option value="detail">细节</option>
              <option value="scene">场景</option>
            </select>
            <label className="button primary file-button">
              上传素材
              <input
                type="file"
                accept="image/*,video/*"
                onChange={(event) => void uploadAsset(event)}
              />
            </label>
          </div>
          <div className="asset-grid">
            {assets.length ? (
              assets.map((asset) => (
                <div className="asset-card" key={asset.id}>
                  <div className="asset-preview">
                    {asset.mimeType.startsWith("video/") ? (
                      <video src={asset.url} controls />
                    ) : (
                      <img
                        src={asset.url}
                        alt={asset.originalName || "产品素材"}
                      />
                    )}
                  </div>
                  <div className="asset-card-copy">
                    <strong>{asset.view || "未标记视角"}</strong>
                    <span>
                      {asset.type} · {formatBytes(asset.byteSize)}
                    </span>
                  </div>
                  <button
                    className="button danger small"
                    onClick={() => void removeAsset(asset.id)}
                  >
                    删除
                  </button>
                </div>
              ))
            ) : (
              <EmptyState text="上传产品多角度参考图，后续生成会自动引用" />
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function AccountView({
  user,
  onSaved,
}: {
  user: User;
  onSaved: (user: User) => void;
}) {
  const [displayName, setDisplayName] = useState(user.displayName);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      const updated = await api<{
        id: string;
        email: string;
        displayName: string;
      }>("/system/profile", {
        method: "PATCH",
        bodyJson: {
          displayName,
          currentPassword: currentPassword || undefined,
          newPassword: newPassword || undefined,
        },
      });
      onSaved({ ...user, displayName: updated.displayName });
      setCurrentPassword("");
      setNewPassword("");
      setMessage("个人资料已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="two-column">
      <form className="panel form-panel" onSubmit={save}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">ACCOUNT CENTER</span>
            <h3>个人中心</h3>
          </div>
        </div>
        <label>
          登录邮箱
          <input value={user.email} readOnly />
        </label>
        <label>
          显示名称
          <input
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </label>
        <label>
          当前密码
          <input
            type="password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
            placeholder="修改密码时填写"
          />
        </label>
        <label>
          新密码
          <input
            type="password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
            placeholder="至少 8 位"
          />
        </label>
        {message && <div className="alert success">{message}</div>}
        <button className="button primary" disabled={saving}>
          {saving ? "保存中..." : "保存个人资料"}
        </button>
      </form>
      <section className="panel">
        <span className="eyebrow">ACCESS</span>
        <h3>当前权限</h3>
        <div className="tag-list">
          {user.roles.map((role) => (
            <span className="tag" key={role}>
              {role}
            </span>
          ))}
        </div>
        <div className="permission-list">
          {user.permissions.map((permission) => (
            <div className="compact-row" key={permission}>
              <strong>{permission}</strong>
              <span>已授权</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function AdminCenter({
  tab,
  onTabChange,
}: {
  tab: AdminTab;
  onTabChange: (tab: AdminTab) => void;
}) {
  const tabs: Array<{ id: AdminTab; label: string }> = [
    { id: "users", label: "用户管理" },
    { id: "roles", label: "角色权限" },
    { id: "teams", label: "团队管理" },
    { id: "settings", label: "系统设置" },
    { id: "providers", label: "模型供应商" },
    { id: "audit", label: "审计日志" },
  ];
  return (
    <div className="admin-center">
      <div className="admin-tabs">
        {tabs.map((item) => (
          <TabButton
            key={item.id}
            active={tab === item.id}
            onClick={() => onTabChange(item.id)}
          >
            {item.label}
          </TabButton>
        ))}
      </div>
      {tab === "users" && <UsersAdmin />}
      {tab === "roles" && <RolesAdmin />}
      {tab === "teams" && <TeamsAdmin />}
      {tab === "settings" && <SettingsAdmin />}
      {tab === "providers" && <ProvidersAdmin />}
      {tab === "audit" && <AuditAdmin />}
    </div>
  );
}

function UsersAdmin() {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [teams, setTeams] = useState<ManagedTeam[]>([]);
  const [form, setForm] = useState({
    email: "",
    displayName: "",
    password: "",
    roleId: "",
    teamId: "",
  });
  const [message, setMessage] = useState("");

  const reload = useCallback(async () => {
    const [userData, roleData, teamData] = await Promise.all([
      api<ManagedUser[]>("/system/users"),
      api<{ roles: Role[]; permissions: Permission[] }>("/system/roles"),
      api<ManagedTeam[]>("/system/teams"),
    ]);
    setUsers(userData ?? []);
    setRoles(roleData.roles ?? []);
    setTeams(teamData ?? []);
  }, []);
  useEffect(() => {
    void reload().catch((error) => setMessage(error.message));
  }, [reload]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api("/system/users", {
        method: "POST",
        bodyJson: {
          email: form.email,
          displayName: form.displayName,
          password: form.password,
          roleIds: form.roleId ? [form.roleId] : [],
          teamIds: form.teamId ? [form.teamId] : [],
        },
      });
      setForm({
        email: "",
        displayName: "",
        password: "",
        roleId: "",
        teamId: "",
      });
      await reload();
      setMessage("用户已创建");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "用户创建失败");
    }
  }

  return (
    <div className="admin-grid">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">USERS</span>
            <h3>用户与状态</h3>
          </div>
          <span className="count-badge">{users.length}</span>
        </div>
        <div className="table-list">
          {users.map((item) => (
            <div className="table-row" key={item.id}>
              <div>
                <strong>{item.displayName}</strong>
                <span>{item.email}</span>
              </div>
              <div className="row-meta">
                <span>
                  {item.roles.map((role) => role.name).join("、") ||
                    "未分配角色"}
                </span>
                <StatusBadge status={item.status} />
              </div>
            </div>
          ))}
        </div>
      </section>
      <form className="panel form-panel" onSubmit={create}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">NEW USER</span>
            <h3>新增工作台用户</h3>
          </div>
        </div>
        <label>
          邮箱
          <input
            type="email"
            required
            value={form.email}
            onChange={(event) =>
              setForm({ ...form, email: event.target.value })
            }
          />
        </label>
        <label>
          显示名称
          <input
            required
            value={form.displayName}
            onChange={(event) =>
              setForm({ ...form, displayName: event.target.value })
            }
          />
        </label>
        <label>
          初始密码
          <input
            required
            type="password"
            minLength={8}
            value={form.password}
            onChange={(event) =>
              setForm({ ...form, password: event.target.value })
            }
          />
        </label>
        <label>
          角色
          <select
            required
            value={form.roleId}
            onChange={(event) =>
              setForm({ ...form, roleId: event.target.value })
            }
          >
            <option value="">选择角色</option>
            {roles.map((role) => (
              <option key={role.id} value={role.id}>
                {role.name} · {role.code}
              </option>
            ))}
          </select>
        </label>
        <label>
          团队
          <select
            required
            value={form.teamId}
            onChange={(event) =>
              setForm({ ...form, teamId: event.target.value })
            }
          >
            <option value="">选择团队</option>
            {teams.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name} · {team.code}
              </option>
            ))}
          </select>
        </label>
        {message && <div className="alert success">{message}</div>}
        <button className="button primary">创建用户</button>
      </form>
    </div>
  );
}

function RolesAdmin() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [selected, setSelected] = useState("");
  const [message, setMessage] = useState("");
  useEffect(() => {
    void api<{ roles: Role[]; permissions: Permission[] }>("/system/roles")
      .then((data) => {
        setRoles(data.roles ?? []);
        setPermissions(data.permissions ?? []);
        setSelected(data.roles?.[0]?.id ?? "");
      })
      .catch((error) => setMessage(error.message));
  }, []);
  const active = roles.find((role) => role.id === selected);
  async function toggle(permissionId: string) {
    if (!active) return;
    const current = new Set(
      active.permissions.map((permission) => permission.id),
    );
    if (current.has(permissionId)) current.delete(permissionId);
    else current.add(permissionId);
    try {
      const data = await api<{ roles: Role[]; permissions: Permission[] }>(
        `/system/roles/${active.id}/permissions`,
        { method: "PATCH", bodyJson: { permissionIds: [...current] } },
      );
      setRoles(data.roles ?? []);
      setPermissions(data.permissions ?? []);
      setMessage("角色权限已更新");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "更新失败");
    }
  }
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">RBAC</span>
          <h3>角色权限矩阵</h3>
        </div>
      </div>
      <div className="role-layout">
        <div className="role-list">
          {roles.map((role) => (
            <button
              className={`role-row ${selected === role.id ? "selected" : ""}`}
              key={role.id}
              onClick={() => setSelected(role.id)}
            >
              <strong>{role.name}</strong>
              <span>{role.code}</span>
            </button>
          ))}
        </div>
        <div className="permission-matrix">
          <div className="section-label">
            {active?.name || "选择角色"} · 权限
          </div>
          {permissions.map((permission) => {
            const checked = Boolean(
              active?.permissions.some((item) => item.id === permission.id),
            );
            return (
              <label className="permission-row" key={permission.id}>
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => void toggle(permission.id)}
                />
                <span>
                  <strong>{permission.name}</strong>
                  <small>{permission.code}</small>
                </span>
              </label>
            );
          })}
          {message && <div className="alert success">{message}</div>}
        </div>
      </div>
    </section>
  );
}

function TeamsAdmin() {
  const [teams, setTeams] = useState<ManagedTeam[]>([]);
  const [form, setForm] = useState({ name: "", code: "" });
  const [message, setMessage] = useState("");
  const reload = useCallback(
    () =>
      api<ManagedTeam[]>("/system/teams").then((data) => setTeams(data ?? [])),
    [],
  );
  useEffect(() => {
    void reload().catch((error) => setMessage(error.message));
  }, [reload]);
  async function create(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api("/system/teams", { method: "POST", bodyJson: form });
      setForm({ name: "", code: "" });
      await reload();
      setMessage("团队已创建");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "团队创建失败");
    }
  }
  return (
    <div className="admin-grid">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">TEAMS</span>
            <h3>团队与成员</h3>
          </div>
        </div>
        <div className="table-list">
          {teams.map((team) => (
            <div className="table-row" key={team.id}>
              <div>
                <strong>{team.name}</strong>
                <span>{team.code}</span>
              </div>
              <div className="row-meta">
                <span>{team.members.length} 名成员</span>
              </div>
            </div>
          ))}
        </div>
      </section>
      <form className="panel form-panel" onSubmit={create}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">NEW TEAM</span>
            <h3>新增团队</h3>
          </div>
        </div>
        <label>
          团队名称
          <input
            required
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
        </label>
        <label>
          团队编码
          <input
            required
            value={form.code}
            onChange={(event) => setForm({ ...form, code: event.target.value })}
          />
        </label>
        {message && <div className="alert success">{message}</div>}
        <button className="button primary">创建团队</button>
      </form>
    </div>
  );
}

function SettingsAdmin() {
  const [settings, setSettings] = useState<SystemSetting[]>([]);
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [secret, setSecret] = useState(false);
  const [message, setMessage] = useState("");
  const reload = useCallback(
    () =>
      api<SystemSetting[]>("/system/settings").then((data) =>
        setSettings(data ?? []),
      ),
    [],
  );
  useEffect(() => {
    void reload().catch((error) => setMessage(error.message));
  }, [reload]);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api(`/system/settings/${encodeURIComponent(key)}`, {
        method: "POST",
        bodyJson: {
          value: secret ? value : parseSettingValue(value),
          isSecret: secret,
        },
      });
      setKey("");
      setValue("");
      await reload();
      setMessage("系统设置已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "设置保存失败");
    }
  }
  return (
    <div className="admin-grid">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">SETTINGS</span>
            <h3>系统设置</h3>
          </div>
        </div>
        <div className="table-list">
          {settings.map((setting) => (
            <div className="table-row" key={setting.id}>
              <div>
                <strong>{setting.key}</strong>
                <span>
                  {setting.isSecret
                    ? "敏感配置"
                    : JSON.stringify(setting.value)}
                </span>
              </div>
              <span className="status-badge succeeded">
                {setting.isSecret ? "已配置" : "普通"}
              </span>
            </div>
          ))}
        </div>
      </section>
      <form className="panel form-panel" onSubmit={save}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">UPSERT SETTING</span>
            <h3>写入系统配置</h3>
          </div>
        </div>
        <label>
          配置键
          <input
            required
            value={key}
            onChange={(event) => setKey(event.target.value)}
            placeholder="例如：default.aspect_ratio"
          />
        </label>
        <label>
          配置值
          <textarea
            required
            rows={5}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={secret}
            onChange={(event) => setSecret(event.target.checked)}
          />
          敏感配置
        </label>
        {message && <div className="alert success">{message}</div>}
        <button className="button primary">保存设置</button>
      </form>
    </div>
  );
}

function ProvidersAdmin() {
  const [providers, setProviders] = useState<ModelProvider[]>([]);
  const [form, setForm] = useState({
    name: "",
    baseUrl: "",
    apiKey: "",
    kind: "OPENAI_COMPATIBLE",
  });
  const [profileForm, setProfileForm] = useState({
    providerId: "",
    name: "",
    endpointPath: "",
    image: true,
    video: false,
  });
  const [message, setMessage] = useState("");
  const reload = useCallback(
    () =>
      api<ModelProvider[]>("/model-gateway/providers").then((data) =>
        setProviders(data ?? []),
      ),
    [],
  );
  useEffect(() => {
    void reload().catch((error) => setMessage(error.message));
  }, [reload]);
  async function create(event: React.FormEvent) {
    event.preventDefault();
    try {
      const created = await api<ModelProvider>("/model-gateway/providers", {
        method: "POST",
        bodyJson: form,
      });
      setForm({ name: "", baseUrl: "", apiKey: "", kind: "OPENAI_COMPATIBLE" });
      await reload();
      setProfileForm((current) => ({ ...current, providerId: created.id }));
      setMessage("供应商已保存，可继续添加模型 Profile");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "供应商保存失败");
    }
  }
  async function createProfile(event: React.FormEvent) {
    event.preventDefault();
    if (!profileForm.providerId) {
      setMessage("请先选择供应商");
      return;
    }
    try {
      await api(`/model-gateway/providers/${profileForm.providerId}/profiles`, {
        method: "POST",
        bodyJson: {
          name: profileForm.name,
          endpointPath: profileForm.endpointPath || undefined,
          capability: {
            image: profileForm.image,
            video: profileForm.video,
          },
        },
      });
      setProfileForm((current) => ({
        ...current,
        name: "",
        endpointPath: "",
      }));
      await reload();
      setMessage("模型 Profile 已保存");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "模型 Profile 保存失败",
      );
    }
  }
  return (
    <div className="admin-grid">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">MODEL GATEWAY</span>
            <h3>供应商与 API Key</h3>
          </div>
        </div>
        <div className="table-list">
          {providers.map((provider) => (
            <div className="table-row" key={provider.id}>
              <div>
                <strong>{provider.name}</strong>
                <span>
                  {provider.baseUrl} · {provider.apiKeyHint || "未显示密钥"}
                </span>
                {provider.profiles.length > 0 && (
                  <small className="provider-profile-list">
                    {provider.profiles
                      .map((profile) => profile.name)
                      .join("、")}
                  </small>
                )}
              </div>
              <StatusBadge status={provider.enabled ? "ACTIVE" : "DISABLED"} />
            </div>
          ))}
        </div>
      </section>
      <div className="admin-form-stack">
        <form className="panel form-panel" onSubmit={create}>
          <div className="panel-heading">
            <div>
              <span className="eyebrow">NEW PROVIDER</span>
              <h3>接入官方或中转 API</h3>
            </div>
          </div>
          <label>
            名称
            <input
              required
              value={form.name}
              onChange={(event) =>
                setForm({ ...form, name: event.target.value })
              }
            />
          </label>
          <label>
            Base URL
            <input
              required
              type="url"
              value={form.baseUrl}
              onChange={(event) =>
                setForm({ ...form, baseUrl: event.target.value })
              }
              placeholder="https://api.example.com/v1"
            />
          </label>
          <label>
            API Key
            <input
              required
              type="password"
              value={form.apiKey}
              onChange={(event) =>
                setForm({ ...form, apiKey: event.target.value })
              }
            />
          </label>
          <label>
            接入类型
            <select
              value={form.kind}
              onChange={(event) =>
                setForm({ ...form, kind: event.target.value })
              }
            >
              <option value="OPENAI_COMPATIBLE">OpenAI 兼容</option>
              <option value="NATIVE">官方原生</option>
            </select>
          </label>
          {message && <div className="alert success">{message}</div>}
          <button className="button primary">保存供应商</button>
        </form>
        <form className="panel form-panel" onSubmit={createProfile}>
          <div className="panel-heading">
            <div>
              <span className="eyebrow">MODEL PROFILE</span>
              <h3>配置可用模型</h3>
            </div>
          </div>
          <label>
            供应商
            <select
              required
              value={profileForm.providerId}
              onChange={(event) =>
                setProfileForm({
                  ...profileForm,
                  providerId: event.target.value,
                })
              }
            >
              <option value="">选择供应商</option>
              {providers.map((provider) => (
                <option key={provider.id} value={provider.id}>
                  {provider.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            模型名称
            <input
              required
              value={profileForm.name}
              onChange={(event) =>
                setProfileForm({ ...profileForm, name: event.target.value })
              }
              placeholder="例如：image-model-v1"
            />
          </label>
          <label>
            Endpoint Path
            <input
              value={profileForm.endpointPath}
              onChange={(event) =>
                setProfileForm({
                  ...profileForm,
                  endpointPath: event.target.value,
                })
              }
              placeholder="留空使用图片/视频默认路径"
            />
          </label>
          <div className="capability-row">
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={profileForm.image}
                onChange={(event) =>
                  setProfileForm({
                    ...profileForm,
                    image: event.target.checked,
                  })
                }
              />
              图片
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={profileForm.video}
                onChange={(event) =>
                  setProfileForm({
                    ...profileForm,
                    video: event.target.checked,
                  })
                }
              />
              视频
            </label>
          </div>
          <button className="button primary">保存模型配置</button>
        </form>
      </div>
    </div>
  );
}

function AuditAdmin() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [message, setMessage] = useState("");
  useEffect(() => {
    void api<AuditLog[]>("/system/audit-logs")
      .then((data) => setLogs(data ?? []))
      .catch((error) => setMessage(error.message));
  }, []);
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">AUDIT TRAIL</span>
          <h3>审计日志</h3>
        </div>
        <span className="count-badge">{logs.length}</span>
      </div>
      {message && <div className="alert error">{message}</div>}
      <div className="table-list">
        {logs.map((log) => (
          <div className="table-row" key={log.id}>
            <div>
              <strong>{log.action}</strong>
              <span>
                {log.resource} · {log.resourceId || "—"} ·{" "}
                {log.actor?.displayName || "系统"}
              </span>
            </div>
            <span className="row-meta">
              {new Date(log.createdAt).toLocaleString()}
            </span>
          </div>
        ))}
      </div>
    </section>
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
  onTaskUpdated,
}: {
  tasks: Task[];
  activeTask: Task | null;
  onSelect: (task: Task) => void;
  onTaskUpdated: (task: Task) => void;
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
          <TaskDetail task={activeTask} onUpdated={onTaskUpdated} />
        ) : (
          <EmptyState text="选择一个任务查看状态" />
        )}
      </section>
    </div>
  );
}

function TaskDetail({
  task,
  onUpdated,
}: {
  task: Task;
  onUpdated: (task: Task) => void;
}) {
  const [events, setEvents] = useState<string[]>([]);
  const [currentTask, setCurrentTask] = useState(task);

  const refresh = useCallback(async () => {
    const latest = await api<Task>(`/generation-tasks/${task.id}`);
    setCurrentTask(latest);
    onUpdated(latest);
  }, [onUpdated, task.id]);

  useEffect(() => {
    setEvents([]);
    setCurrentTask(task);
    const handleEvent = (event: MessageEvent) => {
      let data: Record<string, unknown> = {};
      try {
        data =
          typeof event.data === "string"
            ? (JSON.parse(event.data) as Record<string, unknown>)
            : (event.data as Record<string, unknown>);
      } catch {
        data = {};
      }
      if (typeof data.status === "string") {
        setCurrentTask((current) => ({
          ...current,
          status: data.status as string,
        }));
      }
      if (
        ["SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"].includes(
          String(data.status),
        )
      ) {
        void refresh().catch(() => undefined);
      }
    };
    const close = streamGeneration(task.id, (event) => {
      const eventData =
        typeof event.data === "string"
          ? event.data
          : JSON.stringify(event.data);
      setEvents((current) =>
        [`${event.type}: ${eventData}`, ...current].slice(0, 20),
      );
      handleEvent(event);
    });
    void refresh().catch(() => undefined);
    return close;
  }, [refresh, task, task.id]);
  return (
    <>
      <div className="panel-heading">
        <div>
          <span className="eyebrow">TASK DETAIL</span>
          <h3>{task.idea}</h3>
        </div>
        <StatusBadge status={currentTask.status} />
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
      {currentTask.assets && currentTask.assets.length > 0 && (
        <div className="asset-grid generated-assets">
          {currentTask.assets.map((asset) => (
            <a
              className="asset-card"
              href={asset.url}
              target="_blank"
              rel="noreferrer"
              key={asset.id}
            >
              <div className="asset-preview">
                {asset.mimeType.startsWith("video/") ? (
                  <video src={asset.url} controls />
                ) : (
                  <img src={asset.url} alt="生成结果" />
                )}
              </div>
              <div className="asset-card-copy">
                <strong>生成结果</strong>
                <span>{formatBytes(asset.byteSize)}</span>
              </div>
            </a>
          ))}
        </div>
      )}
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

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={`tab-button ${active ? "active" : ""}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function MemoryField({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}) {
  return (
    <label>
      {label}
      <textarea
        rows={4}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
      />
    </label>
  );
}

function parseKeyValueLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const separator = line.indexOf("=");
      if (separator < 1) return null;
      const key = line.slice(0, separator).trim();
      const itemValue = line.slice(separator + 1).trim();
      return key && itemValue ? { key, value: itemValue } : null;
    })
    .filter((item): item is { key: string; value: string } => item !== null);
}

function splitLines(value: string) {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function parseSettingValue(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return trimmed;
  }
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1,
  );
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function viewTitle(view: View) {
  return {
    overview: "工作台总览",
    products: "产品中心",
    prompt: "Prompt Engine",
    generate: "图片 / 视频生成",
    canvas: "Infinite Canvas",
    tasks: "生成历史",
    account: "个人中心",
    admin: "系统配置",
  }[view];
}
