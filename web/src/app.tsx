import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useEdgesState,
  useNodesState,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
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

type ModelCapability = {
  image?: boolean;
  video?: boolean;
  aspectRatios?: string[];
  imageAspectRatios?: string[];
  videoAspectRatios?: string[];
  maxCount?: number;
  durationOptions?: number[];
  referenceImage?: boolean;
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

type SkillProfile = {
  id: string;
  name: string;
  code: string;
  mediaType: "IMAGE" | "VIDEO" | "BOTH" | string;
  description?: string | null;
  version?: string | null;
  tags?: string[] | null;
  promptTemplate?: string | null;
  negativePrompt?: string | null;
  settings?: Record<string, unknown> | null;
  enabled: boolean;
  createdAt?: string;
  updatedAt?: string;
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
  historyCode?: string | null;
  status: string;
  type: string;
  idea: string;
  createdAt?: string;
  options?: Record<string, unknown> | null;
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
  | "image"
  | "video"
  | "canvas"
  | "tasks"
  | "account"
  | "admin";

type AdminTab =
  | "users"
  | "roles"
  | "teams"
  | "menus"
  | "settings"
  | "providers"
  | "skills"
  | "audit";

type MenuDefinition = {
  code: string;
  label: string;
  group: string;
  icon: string;
  permission?: string;
  description: string;
};

const MENU_DEFINITIONS: MenuDefinition[] = [
  {
    code: "overview",
    label: "工作台首页",
    group: "工作台",
    icon: "⌂",
    description: "查看工作台概览、最近任务和快速入口",
  },
  {
    code: "image",
    label: "图片创作",
    group: "创作中心",
    icon: "✦",
    permission: "generation:create:team",
    description: "创建电商产品图片并查看生成结果",
  },
  {
    code: "video",
    label: "视频创作",
    group: "创作中心",
    icon: "▶",
    permission: "generation:create:team",
    description: "创建电商产品视频并查看生成结果",
  },
  {
    code: "canvas",
    label: "Infinite Canvas",
    group: "创作中心",
    icon: "∞",
    permission: "canvas:manage:team",
    description: "组合产品、记忆、Prompt 和生成节点",
  },
  {
    code: "products",
    label: "产品中心",
    group: "资源中心",
    icon: "□",
    permission: "product:read:team",
    description: "管理产品档案、产品记忆和参考素材",
  },
  {
    code: "tasks",
    label: "生成历史",
    group: "资源中心",
    icon: "◷",
    permission: "generation:read:team",
    description: "查询生成编号、任务状态和输出资产",
  },
  {
    code: "account",
    label: "个人中心",
    group: "工作台",
    icon: "◎",
    description: "维护个人资料、密码和当前授权",
  },
  {
    code: "admin",
    label: "系统配置",
    group: "系统管理",
    icon: "⚙",
    permission: "user:manage:system",
    description: "管理用户、角色、菜单、模型和审计日志",
  },
];

function hasPermission(user: User, permission: string) {
  return (
    user.roles.includes("super_admin") || user.permissions.includes(permission)
  );
}

function firstAccessibleView(user: User): View {
  if (
    hasPermission(user, "generation:create:team") ||
    hasPermission(user, "product:read:team") ||
    hasPermission(user, "generation:read:team")
  ) {
    return "overview";
  }
  if (
    hasPermission(user, "user:manage:system") ||
    hasPermission(user, "model_config:read:system") ||
    hasPermission(user, "audit:read:system")
  ) {
    return "admin";
  }
  return "account";
}

const starterNodes: Node[] = [
  {
    id: "product",
    type: "input",
    position: { x: 80, y: 160 },
    data: { kind: "product", label: "Product · 产品" },
  },
  {
    id: "memory",
    position: { x: 340, y: 160 },
    data: { kind: "memory", label: "Memory · 产品记忆" },
  },
  {
    id: "prompt",
    position: { x: 620, y: 160 },
    data: { kind: "prompt", label: "Prompt · Prompt Engine" },
  },
  {
    id: "generation",
    position: { x: 940, y: 160 },
    data: { kind: "generation", label: "Generation · 图片 / 视频" },
  },
  {
    id: "result",
    type: "output",
    position: { x: 1260, y: 160 },
    data: { kind: "result", label: "Result · 结果" },
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
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(max-width: 680px)").matches,
  );
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [quickSearchOpen, setQuickSearchOpen] = useState(false);
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
      setView(firstAccessibleView(current));
      const canReadProducts = hasPermission(current, "product:read:team");
      const canReadTasks = hasPermission(current, "generation:read:team");
      const [productData, taskData] = await Promise.all([
        canReadProducts
          ? api<Product[]>("/products")
          : Promise.resolve([] as Product[]),
        canReadTasks
          ? api<Task[]>("/generation-tasks")
          : Promise.resolve([] as Task[]),
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

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [view, adminTab]);

  async function logout() {
    await api("/auth/logout", { method: "POST" });
    setUser(null);
  }

  function navigateToView(nextView: View) {
    setView(nextView);
    if (window.matchMedia("(max-width: 680px)").matches) {
      setSidebarCollapsed(true);
    }
  }

  if (!user) {
    return (
      <Login
        onLogin={(nextUser) => {
          setUser(nextUser);
          setView(firstAccessibleView(nextUser));
          void loadWorkspace();
        }}
        error={error}
      />
    );
  }

  const canReadProducts = hasPermission(user, "product:read:team");
  const canEditProducts = hasPermission(user, "product:update:team");
  const canGenerate = hasPermission(user, "generation:create:team");
  const canReadTasks = hasPermission(user, "generation:read:team");
  const canManageCanvas = hasPermission(user, "canvas:manage:team");
  const canManageSystem =
    user.roles.includes("super_admin") ||
    user.permissions.some((permission) =>
      [
        "user:manage:system",
        "model_config:read:system",
        "audit:read:system",
      ].includes(permission),
    );
  const searchableViews = MENU_DEFINITIONS.filter((item) => {
    if (!item.permission) return true;
    return hasPermission(user, item.permission);
  }).map((item) => ({
    view: item.code as View,
    label: item.label,
    description: item.description,
  }));
  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await document.documentElement.requestFullscreen();
      }
    } catch {
      // Fullscreen is a browser capability; the workbench remains usable if it is denied.
    }
  }

  if (view === "canvas" && canManageCanvas) {
    return (
      <CanvasView
        selectedProductId={selectedProductId}
        products={products}
        tasks={tasks}
        onExit={() => setView(canGenerate ? "image" : "products")}
        onProductChange={setSelectedProductId}
      />
    );
  }

  return (
    <div
      className={`app-shell admin-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""}`}
    >
      {!sidebarCollapsed && (
        <button
          className="sidebar-backdrop"
          type="button"
          aria-label="关闭侧栏"
          onClick={() => setSidebarCollapsed(true)}
        />
      )}
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark">CS</div>
          <div className="brand-copy">
            <strong>Commerce Studio</strong>
            <span>AI 产品创作工作台</span>
          </div>
        </div>
        <nav className="nav-list admin-nav">
          <div className="nav-section-label">工作台</div>
          <NavItem
            icon="⌂"
            label="工作台首页"
            active={view === "overview"}
            onClick={() => navigateToView("overview")}
          />
          <NavItem
            icon="◎"
            label="个人中心"
            active={view === "account"}
            onClick={() => navigateToView("account")}
          />
          <div className="nav-section-label">创作中心</div>
          {canGenerate && (
            <>
              <NavItem
                icon="✦"
                label="图片创作"
                active={view === "image"}
                onClick={() => navigateToView("image")}
                badge="IMAGE"
              />
              <NavItem
                icon="▶"
                label="视频创作"
                active={view === "video"}
                onClick={() => navigateToView("video")}
                badge="VIDEO"
              />
            </>
          )}
          {canManageCanvas && (
            <NavItem
              icon="∞"
              label="Infinite Canvas"
              active={view === "canvas"}
              onClick={() => navigateToView("canvas")}
            />
          )}
          <div className="nav-section-label">资源中心</div>
          {canReadProducts && (
            <NavItem
              icon="□"
              label="产品中心"
              active={view === "products"}
              onClick={() => navigateToView("products")}
            />
          )}
          {canReadTasks && (
            <NavItem
              icon="◷"
              label="生成历史"
              active={view === "tasks"}
              onClick={() => navigateToView("tasks")}
            />
          )}
          {canManageSystem && (
            <>
              <div className="nav-section-label">系统管理</div>
              <NavItem
                icon="⚙"
                label="系统配置"
                active={view === "admin"}
                onClick={() => navigateToView("admin")}
              />
            </>
          )}
        </nav>
        <div className="sidebar-footer">
          <div className="status-dot" />
          <span className="sidebar-footer-copy">产品记忆已连接</span>
        </div>
      </aside>
      <main className="main-panel">
        <header className="topbar admin-topbar">
          <div className="topbar-leading">
            <button
              className="icon-button sidebar-toggle"
              type="button"
              title={sidebarCollapsed ? "展开侧栏" : "收起侧栏"}
              aria-label={sidebarCollapsed ? "展开侧栏" : "收起侧栏"}
              onClick={() => setSidebarCollapsed((current) => !current)}
            >
              ☰
            </button>
            <div className="breadcrumb-stack">
              <div className="breadcrumb-row">
                <span>工作台</span>
                <span className="breadcrumb-separator">/</span>
                <strong>{viewTitle(view)}</strong>
                {view === "admin" && (
                  <>
                    <span className="breadcrumb-separator">/</span>
                    <strong>{adminTabTitle(adminTab)}</strong>
                  </>
                )}
              </div>
              <div className="topbar-context">
                <span className="topbar-context-dot" />
                <span>创作运营工作台</span>
              </div>
            </div>
          </div>
          <div className="topbar-actions">
            <button
              className="icon-button topbar-tool"
              type="button"
              title="全屏"
              aria-label="全屏"
              onClick={() => void toggleFullscreen()}
            >
              ⛶
            </button>
            <button
              className="icon-button topbar-tool"
              type="button"
              title="快捷搜索"
              aria-label="快捷搜索"
              onClick={() => setQuickSearchOpen(true)}
            >
              ⌕
            </button>
            <div className="user-menu">
              <button
                className="user-menu-trigger"
                type="button"
                aria-expanded={userMenuOpen}
                onClick={() => setUserMenuOpen((current) => !current)}
              >
                <span className="user-avatar">
                  {user.displayName.slice(0, 1)}
                </span>
                <span className="user-menu-copy">
                  <strong>{user.displayName}</strong>
                  <small>{user.roles[0] || "成员"}</small>
                </span>
                <span className="user-menu-chevron">⌄</span>
              </button>
              {userMenuOpen && (
                <div className="user-menu-popover">
                  <button
                    type="button"
                    onClick={() => {
                      navigateToView("account");
                      setUserMenuOpen(false);
                    }}
                  >
                    个人中心
                  </button>
                  {canManageSystem && (
                    <button
                      type="button"
                      onClick={() => {
                        navigateToView("admin");
                        setUserMenuOpen(false);
                      }}
                    >
                      系统配置
                    </button>
                  )}
                  <button
                    type="button"
                    className="danger-text"
                    onClick={() => void logout()}
                  >
                    退出登录
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>
        {quickSearchOpen && (
          <QuickSearch
            items={searchableViews}
            onClose={() => setQuickSearchOpen(false)}
            onNavigate={(nextView) => {
              navigateToView(nextView);
              setQuickSearchOpen(false);
            }}
          />
        )}
        {error && <div className="alert error">{error}</div>}
        {loading ? (
          <div className="loading-panel">正在加载工作台...</div>
        ) : (
          <section className="content">
            {view === "overview" && (
              <Overview
                products={products}
                tasks={tasks}
                onNavigate={navigateToView}
              />
            )}
            {view === "products" && (
              <ProductsView
                products={products}
                selectedProductId={selectedProductId}
                onSelect={setSelectedProductId}
                canEdit={canEditProducts}
                onCreated={async () => {
                  const data = await api<Product[]>("/products");
                  setProducts(data ?? []);
                }}
              />
            )}
            {view === "image" && (
              <GenerationStudio
                type="IMAGE"
                products={products}
                tasks={tasks}
                profiles={profiles}
                selectedProductId={selectedProductId}
                onProductChange={setSelectedProductId}
                onProfiles={setProfiles}
                onTaskUpdated={handleTaskUpdated}
                onCreated={(task) => {
                  setActiveTask(task);
                  setTasks((current) => [task, ...current]);
                }}
              />
            )}
            {view === "video" && (
              <GenerationStudio
                type="VIDEO"
                products={products}
                tasks={tasks}
                profiles={profiles}
                selectedProductId={selectedProductId}
                onProductChange={setSelectedProductId}
                onProfiles={setProfiles}
                onTaskUpdated={handleTaskUpdated}
                onCreated={(task) => {
                  setActiveTask(task);
                  setTasks((current) => [task, ...current]);
                }}
              />
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
              <AdminCenter
                user={user}
                tab={adminTab}
                onTabChange={setAdminTab}
              />
            )}
          </section>
        )}
      </main>
    </div>
  );
}

function QuickSearch({
  items,
  onClose,
  onNavigate,
}: {
  items: Array<{ view: View; label: string; description: string }>;
  onClose: () => void;
  onNavigate: (view: View) => void;
}) {
  const [query, setQuery] = useState("");
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);
  const normalizedQuery = query.trim().toLowerCase();
  const visibleItems = items.filter((item) =>
    [item.label, item.description, item.view].some((value) =>
      value.toLowerCase().includes(normalizedQuery),
    ),
  );
  return (
    <div className="quick-search-layer" role="presentation" onClick={onClose}>
      <section
        className="quick-search-panel"
        role="dialog"
        aria-modal="true"
        aria-label="快捷搜索"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="quick-search-heading">
          <div>
            <span className="eyebrow">QUICK SEARCH</span>
            <h2>跳转到工作台功能</h2>
          </div>
          <button
            className="icon-button"
            type="button"
            title="关闭搜索"
            aria-label="关闭搜索"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <input
          autoFocus
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="搜索产品、图片创作、系统配置..."
        />
        <div className="quick-search-results">
          {visibleItems.length ? (
            visibleItems.map((item) => (
              <button
                key={item.view}
                type="button"
                className="quick-search-result"
                onClick={() => onNavigate(item.view)}
              >
                <span className="quick-search-result-icon">
                  {MENU_DEFINITIONS.find((menu) => menu.code === item.view)
                    ?.icon || "·"}
                </span>
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
                <span className="quick-search-result-key">↵</span>
              </button>
            ))
          ) : (
            <EmptyState text="没有匹配的工作台功能" />
          )}
        </div>
      </section>
    </div>
  );
}

function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  aside,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
  aside?: React.ReactNode;
}) {
  return (
    <div className="page-heading">
      <div className="page-heading-copy">
        <span className="eyebrow">{eyebrow}</span>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      {(actions || aside) && (
        <div className="page-heading-actions">
          {aside}
          {actions}
        </div>
      )}
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
  const recentTasks = tasks.slice(0, 4);
  return (
    <div className="overview-page">
      <div className="overview-header page-toolbar">
        <div>
          <span className="eyebrow">GOOD MORNING · CREATIVE OPS</span>
          <h2>今天要为哪个产品创造内容？</h2>
          <p>产品记忆、模型和生成结果都在这里持续沉淀。</p>
        </div>
        <div className="toolbar-actions">
          <button
            className="button ghost"
            type="button"
            onClick={() => onNavigate("products")}
          >
            管理产品
          </button>
          <button
            className="button primary"
            type="button"
            onClick={() => onNavigate("image")}
          >
            开始创作
          </button>
        </div>
      </div>
      <div className="metric-grid">
        <Metric
          label="产品数据源"
          value={products.length}
          caption="已建立的产品资料"
        />
        <Metric
          label="生成任务"
          value={tasks.length}
          caption="图片与视频任务记录"
        />
        <Metric label="处理中" value={running} caption="正在等待或处理" />
        <Metric label="创作画布" value="∞" caption="可组合的工作流空间" />
      </div>
      <div className="overview-grid">
        <section className="panel overview-workflow-card">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">RECOMMENDED FLOW</span>
              <h3>从产品到成片</h3>
            </div>
            <button
              className="button ghost small"
              type="button"
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
        <section className="panel overview-recent-card">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">RECENT ACTIVITY</span>
              <h3>最近任务</h3>
            </div>
            <button
              className="text-button"
              type="button"
              onClick={() => onNavigate("tasks")}
            >
              查看全部
            </button>
          </div>
          <div className="overview-task-list">
            {recentTasks.length ? (
              recentTasks.map((task) => (
                <button
                  className="overview-task-row"
                  type="button"
                  key={task.id}
                  onClick={() => onNavigate("tasks")}
                >
                  <span
                    className={`overview-task-icon ${
                      task.type === "VIDEO" ? "video" : "image"
                    }`}
                  >
                    {task.type === "VIDEO" ? "▶" : "✦"}
                  </span>
                  <span>
                    <strong>{task.idea}</strong>
                    <small>
                      {task.product?.name || "未关联产品"} ·{" "}
                      {task.historyCode || "待分配编号"}
                    </small>
                  </span>
                  <StatusBadge status={task.status} />
                </button>
              ))
            ) : (
              <EmptyState text="还没有生成任务" />
            )}
          </div>
        </section>
      </div>
      <div className="overview-lower-grid">
        <section className="panel quick-action-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">QUICK START</span>
              <h3>快速入口</h3>
            </div>
          </div>
          <div className="quick-action-grid">
            <button type="button" onClick={() => onNavigate("image")}>
              <span>✦</span>
              <strong>生成图片</strong>
              <small>适合主图、细节图和电商场景</small>
            </button>
            <button type="button" onClick={() => onNavigate("video")}>
              <span>▶</span>
              <strong>生成视频</strong>
              <small>选择产品后快速制作广告镜头</small>
            </button>
            <button type="button" onClick={() => onNavigate("products")}>
              <span>□</span>
              <strong>维护产品</strong>
              <small>更新档案、记忆和参考素材</small>
            </button>
          </div>
        </section>
        <section className="panel system-status-card">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">SYSTEM STATUS</span>
              <h3>服务状态</h3>
            </div>
            <span className="status-dot" />
          </div>
          <div className="system-row">
            <span className="status-dot" /> API 应用在线
          </div>
          <div className="system-row">
            <span className="status-dot amber" /> MySQL 外部连接
          </div>
          <div className="system-row">
            <span className="status-dot blue" /> 模型网关已就绪
          </div>
        </section>
      </div>
    </div>
  );
}

function ProductsView({
  products,
  selectedProductId,
  onSelect,
  canEdit,
  onCreated,
}: {
  products: Product[];
  selectedProductId: string;
  onSelect: (id: string) => void;
  canEdit: boolean;
  onCreated: () => Promise<void>;
}) {
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [brand, setBrand] = useState("");
  const [category, setCategory] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState("");

  async function createProduct(event: React.FormEvent) {
    event.preventDefault();
    setCreating(true);
    setMessage("");
    try {
      const created = await api<Product>("/products", {
        method: "POST",
        bodyJson: { name, code, brand, category, description },
      });
      setName("");
      setCode("");
      setBrand("");
      setCategory("");
      setDescription("");
      await onCreated();
      onSelect(created.id);
      setCreateOpen(false);
      setMessage("产品已创建");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "创建失败");
    } finally {
      setCreating(false);
    }
  }

  const normalizedQuery = query.trim().toLowerCase();
  const visibleProducts = products.filter((product) => {
    const matchesQuery =
      !normalizedQuery ||
      [product.name, product.code, product.brand, product.category]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalizedQuery));
    const matchesStatus =
      statusFilter === "ALL" || (product.status ?? "DRAFT") === statusFilter;
    return matchesQuery && matchesStatus;
  });

  return (
    <div className="product-center-shell">
      <PageHeader
        eyebrow="PRODUCT CENTER"
        title="产品中心"
        description="先建立产品资料，再维护 Product Profile、产品记忆与可引用素材。"
        aside={
          <span className="page-heading-count">{products.length} 个产品</span>
        }
        actions={
          canEdit && (
            <button
              className="button primary"
              type="button"
              onClick={() => setCreateOpen((current) => !current)}
            >
              {createOpen ? "关闭新建" : "新建产品"}
            </button>
          )
        }
      />
      {createOpen && canEdit && (
        <div
          className="drawer-backdrop product-drawer-backdrop"
          role="presentation"
          onClick={() => setCreateOpen(false)}
        >
          <form
            className="product-create-drawer"
            onSubmit={createProduct}
            onClick={(event) => event.stopPropagation()}
          >
            <div>
              <span className="eyebrow">NEW PRODUCT SOURCE</span>
              <h3>建立产品数据源</h3>
              <p>
                产品名称和编码用于后续生成历史、素材与 Product Memory
                的唯一识别。
              </p>
            </div>
            <div className="compact-form-grid">
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
              <label>
                类目
                <input
                  value={category}
                  onChange={(event) => setCategory(event.target.value)}
                  placeholder="例如：消费电子"
                />
              </label>
            </div>
            <label>
              产品描述
              <textarea
                rows={3}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="记录产品定位、主要卖点和电商展示要求"
              />
            </label>
            <div className="drawer-actions">
              {message && <div className="alert success">{message}</div>}
              <button className="button primary" disabled={creating}>
                {creating ? "创建中..." : "创建并打开产品"}
              </button>
            </div>
          </form>
        </div>
      )}
      <div className="product-center-layout">
        <section className="panel product-catalog-panel">
          <div className="panel-heading product-catalog-heading">
            <div>
              <span className="eyebrow">DATA SOURCES</span>
              <h3>产品资料</h3>
              <p className="panel-subtitle">
                选择产品后，在右侧维护档案、记忆和参考素材
              </p>
            </div>
            <span className="count-badge">{visibleProducts.length}</span>
          </div>
          <div className="catalog-filters">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索名称、编码或品牌"
              aria-label="搜索产品"
            />
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              aria-label="筛选产品状态"
            >
              <option value="ALL">全部状态</option>
              <option value="DRAFT">草稿</option>
              <option value="ACTIVE">启用</option>
              <option value="ARCHIVED">归档</option>
            </select>
          </div>
          <div className="product-list product-catalog-list">
            {visibleProducts.length === 0 && (
              <EmptyState
                text={products.length ? "没有匹配的产品" : "还没有产品数据源"}
              />
            )}
            {visibleProducts.map((product) => (
              <button
                className={`product-row product-catalog-row ${selectedProductId === product.id ? "selected" : ""}`}
                key={product.id}
                onClick={() => onSelect(product.id)}
              >
                <div className="product-avatar">
                  {product.name.slice(0, 1).toUpperCase()}
                </div>
                <div className="product-row-copy">
                  <strong>{product.name}</strong>
                  <span>
                    {product.code} · {product.brand || "未设置品牌"}
                  </span>
                  <small>
                    {product.category || "未分类"} ·{" "}
                    {product.status === "ACTIVE" ? "已启用" : "草稿"}
                  </small>
                </div>
                <span className="row-arrow">→</span>
              </button>
            ))}
          </div>
        </section>
        <div className="product-detail-workspace">
          {selectedProductId ? (
            <ProductDetails productId={selectedProductId} canEdit={canEdit} />
          ) : (
            <section className="panel product-empty-detail">
              <div className="empty-illustration">□</div>
              <h3>选择一个产品开始维护</h3>
              <p>
                产品档案、Product Memory
                和素材库会在这里分层管理，并自动供图片与视频创作引用。
              </p>
              {canEdit && (
                <button
                  className="button primary"
                  type="button"
                  onClick={() => setCreateOpen(true)}
                >
                  建立第一个产品
                </button>
              )}
            </section>
          )}
        </div>
      </div>
      {message && !createOpen && <div className="alert success">{message}</div>}
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

function ProductDetails({
  productId,
  canEdit,
}: {
  productId: string;
  canEdit: boolean;
}) {
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
  const [profileText, setProfileText] = useState({
    name: "",
    code: "",
    brand: "",
    category: "",
    description: "",
  });

  const reload = useCallback(async () => {
    const [productData, memoryData, assetData] = await Promise.all([
      api<Product>(`/products/${productId}`),
      api<ProductMemory>(`/products/${productId}/memory`),
      api<ProductAsset[]>(`/products/${productId}/assets`),
    ]);
    setProduct(productData);
    setMemory(memoryData);
    setAssets(assetData ?? []);
    setProfileText({
      name: productData.name,
      code: productData.code,
      brand: productData.brand ?? "",
      category: productData.category ?? "",
      description: productData.description ?? "",
    });
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
    if (!canEdit) return;
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

  async function saveProfile(event: React.FormEvent) {
    event.preventDefault();
    if (!canEdit) return;
    setBusy(true);
    setMessage("");
    try {
      await api(`/products/${productId}`, {
        method: "PATCH",
        bodyJson: {
          name: profileText.name,
          code: profileText.code,
          brand: profileText.brand || undefined,
          category: profileText.category || undefined,
          description: profileText.description || undefined,
        },
      });
      await reload();
      setMessage("产品档案已保存");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "产品档案保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function uploadAsset(event: React.ChangeEvent<HTMLInputElement>) {
    if (!canEdit) return;
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
    if (!canEdit) return;
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
      <div className="panel-heading product-profile-heading">
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
      {!canEdit && (
        <div className="read-only-note">
          当前账号拥有产品查看权限，编辑、记忆维护和素材上传由管理员授权后开放。
        </div>
      )}
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
        <form className="profile-sheet" onSubmit={saveProfile}>
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
          <div className="compact-form-grid profile-edit-grid">
            <label>
              产品名称
              <input
                required
                disabled={!canEdit}
                value={profileText.name}
                onChange={(event) =>
                  setProfileText((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              产品编码
              <input
                required
                disabled={!canEdit}
                value={profileText.code}
                onChange={(event) =>
                  setProfileText((current) => ({
                    ...current,
                    code: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              品牌
              <input
                disabled={!canEdit}
                value={profileText.brand}
                onChange={(event) =>
                  setProfileText((current) => ({
                    ...current,
                    brand: event.target.value,
                  }))
                }
              />
            </label>
            <label>
              类目
              <input
                disabled={!canEdit}
                value={profileText.category}
                onChange={(event) =>
                  setProfileText((current) => ({
                    ...current,
                    category: event.target.value,
                  }))
                }
              />
            </label>
          </div>
          <label>
            产品描述
            <textarea
              rows={4}
              disabled={!canEdit}
              value={profileText.description}
              onChange={(event) =>
                setProfileText((current) => ({
                  ...current,
                  description: event.target.value,
                }))
              }
              placeholder="产品定位、核心卖点、材质和展示边界"
            />
          </label>
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
          <div className="form-actions">
            <span className="form-note">
              产品资料会作为 Prompt Engine 的基础输入
            </span>
            {canEdit && (
              <button className="button primary" disabled={busy}>
                保存产品档案
              </button>
            )}
          </div>
        </form>
      )}
      {tab === "memory" && (
        <form className="memory-editor" onSubmit={saveMemory}>
          <MemoryField
            label="产品事实"
            value={memoryText.facts}
            disabled={!canEdit}
            onChange={(value) =>
              setMemoryText((current) => ({ ...current, facts: value }))
            }
            placeholder={"material=铝合金\ncolor=曜石黑\nsize=标准版"}
          />
          <MemoryField
            label="品牌视觉记忆"
            value={memoryText.brandVisual}
            disabled={!canEdit}
            onChange={(value) =>
              setMemoryText((current) => ({ ...current, brandVisual: value }))
            }
            placeholder={"tone=高级、克制\nlighting=柔和侧光"}
          />
          <MemoryField
            label="生成规则"
            value={memoryText.generationRules}
            disabled={!canEdit}
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
            disabled={!canEdit}
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
            {canEdit && (
              <button className="button primary" disabled={busy}>
                保存产品记忆
              </button>
            )}
          </div>
        </form>
      )}
      {tab === "assets" && (
        <div className="asset-library">
          <div className="asset-toolbar">
            <select
              value={assetType}
              disabled={!canEdit}
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
              disabled={!canEdit}
              onChange={(event) => setAssetView(event.target.value)}
            >
              <option value="front">正面</option>
              <option value="back">背面</option>
              <option value="left">左侧</option>
              <option value="right">右侧</option>
              <option value="detail">细节</option>
              <option value="scene">场景</option>
            </select>
            {canEdit && (
              <label className="button primary file-button">
                上传素材
                <input
                  type="file"
                  accept="image/*,video/*"
                  onChange={(event) => void uploadAsset(event)}
                />
              </label>
            )}
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
                  {canEdit && (
                    <button
                      className="button danger small"
                      type="button"
                      onClick={() => void removeAsset(asset.id)}
                    >
                      删除
                    </button>
                  )}
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
    <div className="account-page">
      <PageHeader
        eyebrow="ACCOUNT CENTER"
        title="个人中心"
        description="维护登录资料、密码和当前工作台授权。"
      />
      <div className="two-column">
        <form className="panel form-panel" onSubmit={save}>
          <div className="panel-heading">
            <div>
              <span className="eyebrow">PROFILE</span>
              <h3>基本资料</h3>
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
          <h3>权限概览</h3>
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
    </div>
  );
}

function AdminCenter({
  user,
  tab,
  onTabChange,
}: {
  user: User;
  tab: AdminTab;
  onTabChange: (tab: AdminTab) => void;
}) {
  const has = (permission: string) =>
    user.roles.includes("super_admin") || user.permissions.includes(permission);
  const tabs = useMemo<Array<{ id: AdminTab; label: string }>>(
    () => [
      ...(has("user:manage:system")
        ? [
            { id: "users" as const, label: "用户管理" },
            { id: "roles" as const, label: "角色权限" },
            { id: "teams" as const, label: "部门管理" },
            { id: "menus" as const, label: "菜单权限" },
          ]
        : []),
      ...(has("model_config:read:system")
        ? [
            { id: "settings" as const, label: "系统设置" },
            { id: "providers" as const, label: "模型供应商" },
            { id: "skills" as const, label: "Skill 配置" },
          ]
        : []),
      ...(has("audit:read:system")
        ? [{ id: "audit" as const, label: "审计日志" }]
        : []),
    ],
    [user],
  );
  const firstTab = tabs[0]?.id;
  useEffect(() => {
    if (firstTab && !tabs.some((item) => item.id === tab)) {
      onTabChange(firstTab);
    }
  }, [firstTab, onTabChange, tab, tabs]);
  return (
    <div className="admin-center">
      <PageHeader
        eyebrow="SYSTEM ADMINISTRATION"
        title="系统管理"
        description="按后台管理系统的权限边界组织用户、角色、部门、页面权限、模型和审计数据。"
        aside={<span className="page-heading-count">{tabs.length} 个模块</span>}
      />
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
      {tab === "users" && has("user:manage:system") && <UsersAdmin />}
      {tab === "roles" && has("user:manage:system") && <RolesAdmin />}
      {tab === "teams" && has("user:manage:system") && <TeamsAdmin />}
      {tab === "menus" && has("user:manage:system") && <MenusAdmin />}
      {tab === "settings" && has("model_config:read:system") && (
        <SettingsAdmin canWrite={has("model_config:update:system")} />
      )}
      {tab === "providers" && has("model_config:read:system") && (
        <ProvidersAdmin canWrite={has("model_config:update:system")} />
      )}
      {tab === "skills" && has("model_config:read:system") && (
        <SkillsAdmin canWrite={has("model_config:update:system")} />
      )}
      {tab === "audit" && has("audit:read:system") && <AuditAdmin />}
    </div>
  );
}

function UsersAdmin() {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [teams, setTeams] = useState<ManagedTeam[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [selectedUser, setSelectedUser] = useState<ManagedUser | null>(null);
  const [form, setForm] = useState({
    email: "",
    displayName: "",
    password: "",
    roleId: "",
    teamId: "",
  });
  const [editForm, setEditForm] = useState({
    email: "",
    displayName: "",
    status: "ACTIVE",
    roleIds: [] as string[],
    teamIds: [] as string[],
  });
  const [resetPassword, setResetPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [userData, roleData, teamData] = await Promise.all([
        api<ManagedUser[]>("/system/users"),
        api<{ roles: Role[]; permissions: Permission[] }>("/system/roles"),
        api<ManagedTeam[]>("/system/teams"),
      ]);
      setUsers(userData ?? []);
      setRoles(roleData.roles ?? []);
      setTeams(teamData ?? []);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload().catch((error) => setMessage(error.message));
  }, [reload]);

  const visibleUsers = users.filter((item) => {
    const normalizedQuery = query.trim().toLowerCase();
    const matchesQuery =
      !normalizedQuery ||
      [item.displayName, item.email, ...item.roles.map((role) => role.name)]
        .join(" ")
        .toLowerCase()
        .includes(normalizedQuery);
    return (
      matchesQuery && (statusFilter === "ALL" || item.status === statusFilter)
    );
  });

  function openUser(item: ManagedUser) {
    setSelectedUser(item);
    setEditForm({
      email: item.email,
      displayName: item.displayName,
      status: item.status,
      roleIds: item.roles.map((role) => role.id),
      teamIds: item.teams.map((team) => team.id),
    });
    setResetPassword("");
    setMessage("");
  }

  function toggleSelection(key: "roleIds" | "teamIds", value: string) {
    setEditForm((current) => ({
      ...current,
      [key]: current[key].includes(value)
        ? current[key].filter((item) => item !== value)
        : [...current[key], value],
    }));
  }

  async function updateUser(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedUser) return;
    setSaving(true);
    setMessage("");
    try {
      const updated = await api<ManagedUser>(
        `/system/users/${selectedUser.id}`,
        {
          method: "PATCH",
          bodyJson: editForm,
        },
      );
      await reload();
      openUser(updated);
      setMessage("用户信息已更新");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "用户更新失败");
    } finally {
      setSaving(false);
    }
  }

  async function changePassword(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedUser || resetPassword.length < 8) {
      setMessage("新密码至少需要 8 位");
      return;
    }
    setSaving(true);
    setMessage("");
    try {
      await api(`/system/users/${selectedUser.id}/reset-password`, {
        method: "POST",
        bodyJson: { password: resetPassword },
      });
      setResetPassword("");
      setMessage("密码已重置");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "密码重置失败");
    } finally {
      setSaving(false);
    }
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
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
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="admin-grid users-admin-grid">
      <section className="panel admin-list-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">USERS</span>
            <h3>用户与状态</h3>
            <p className="panel-subtitle">
              点击用户打开编辑抽屉，可调整角色、部门、状态和密码。
            </p>
          </div>
          <span className="count-badge">{users.length}</span>
        </div>
        <div className="admin-filter-bar">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索姓名、邮箱或角色"
            aria-label="搜索用户"
          />
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            aria-label="筛选用户状态"
          >
            <option value="ALL">全部状态</option>
            <option value="ACTIVE">正常</option>
            <option value="DISABLED">已停用</option>
          </select>
        </div>
        <div className="admin-table">
          <div className="admin-table-head">
            <span>用户</span>
            <span>角色 / 部门</span>
            <span>状态</span>
          </div>
          {loading ? (
            <AdminLoadingState text="正在加载用户、角色和部门..." />
          ) : visibleUsers.length ? (
            visibleUsers.map((item) => (
              <button
                className={`admin-table-row ${selectedUser?.id === item.id ? "selected" : ""}`}
                type="button"
                key={item.id}
                onClick={() => openUser(item)}
              >
                <span className="admin-user-cell">
                  <span className="user-avatar">
                    {item.displayName.slice(0, 1)}
                  </span>
                  <span>
                    <strong>{item.displayName}</strong>
                    <small>{item.email}</small>
                  </span>
                </span>
                <span className="admin-user-meta">
                  <small>
                    {item.roles.map((role) => role.name).join("、") ||
                      "未分配角色"}
                  </small>
                  <small>
                    {item.teams.map((team) => team.name).join("、") ||
                      "未加入部门"}
                  </small>
                </span>
                <StatusBadge status={item.status} />
              </button>
            ))
          ) : (
            <EmptyState text="没有匹配的用户" />
          )}
        </div>
      </section>
      <form className="panel form-panel admin-create-panel" onSubmit={create}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">NEW USER</span>
            <h3>新增工作台用户</h3>
            <p className="panel-subtitle">
              创建后可以继续在用户抽屉中补充授权。
            </p>
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
        <button className="button primary" disabled={saving}>
          {saving ? "保存中..." : "创建用户"}
        </button>
      </form>
      {selectedUser && (
        <div
          className="drawer-backdrop"
          role="presentation"
          onClick={() => setSelectedUser(null)}
        >
          <aside
            className="admin-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="编辑用户"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="admin-drawer-header">
              <div>
                <span className="eyebrow">EDIT USER</span>
                <h3>{selectedUser.displayName}</h3>
                <p>{selectedUser.email}</p>
              </div>
              <button
                className="icon-button"
                type="button"
                title="关闭编辑"
                aria-label="关闭编辑"
                onClick={() => setSelectedUser(null)}
              >
                ×
              </button>
            </div>
            <form className="admin-drawer-form" onSubmit={updateUser}>
              <label>
                邮箱
                <input
                  type="email"
                  required
                  value={editForm.email}
                  onChange={(event) =>
                    setEditForm({ ...editForm, email: event.target.value })
                  }
                />
              </label>
              <label>
                显示名称
                <input
                  required
                  value={editForm.displayName}
                  onChange={(event) =>
                    setEditForm({
                      ...editForm,
                      displayName: event.target.value,
                    })
                  }
                />
              </label>
              <label>
                状态
                <select
                  value={editForm.status}
                  onChange={(event) =>
                    setEditForm({ ...editForm, status: event.target.value })
                  }
                >
                  <option value="ACTIVE">正常</option>
                  <option value="DISABLED">停用</option>
                </select>
              </label>
              <div className="drawer-section">
                <span className="section-label">角色</span>
                <div className="drawer-choice-grid">
                  {roles.map((role) => (
                    <label className="checkbox-label" key={role.id}>
                      <input
                        type="checkbox"
                        checked={editForm.roleIds.includes(role.id)}
                        onChange={() => toggleSelection("roleIds", role.id)}
                      />
                      {role.name}
                    </label>
                  ))}
                </div>
              </div>
              <div className="drawer-section">
                <span className="section-label">部门</span>
                <div className="drawer-choice-grid">
                  {teams.map((team) => (
                    <label className="checkbox-label" key={team.id}>
                      <input
                        type="checkbox"
                        checked={editForm.teamIds.includes(team.id)}
                        onChange={() => toggleSelection("teamIds", team.id)}
                      />
                      {team.name}
                    </label>
                  ))}
                </div>
              </div>
              {message && <div className="alert success">{message}</div>}
              <button className="button primary" disabled={saving}>
                {saving ? "保存中..." : "保存用户授权"}
              </button>
            </form>
            <form className="drawer-danger-section" onSubmit={changePassword}>
              <div>
                <span className="section-label">PASSWORD</span>
                <strong>重置登录密码</strong>
              </div>
              <input
                type="password"
                minLength={8}
                value={resetPassword}
                onChange={(event) => setResetPassword(event.target.value)}
                placeholder="输入至少 8 位新密码"
              />
              <button className="button danger" disabled={saving}>
                重置密码
              </button>
            </form>
          </aside>
        </div>
      )}
    </div>
  );
}

function RolesAdmin() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [selected, setSelected] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    void api<{ roles: Role[]; permissions: Permission[] }>("/system/roles")
      .then((data) => {
        setRoles(data.roles ?? []);
        setPermissions(data.permissions ?? []);
        setSelected(data.roles?.[0]?.id ?? "");
      })
      .catch((error) => setMessage(error.message))
      .finally(() => setLoading(false));
  }, []);
  const active = roles.find((role) => role.id === selected);
  const permissionGroups = useMemo(
    () =>
      permissions.reduce<Record<string, Permission[]>>((groups, permission) => {
        const group = permission.code.split(":")[0] || "other";
        (groups[group] ??= []).push(permission);
        return groups;
      }, {}),
    [permissions],
  );
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
          {loading ? (
            <AdminLoadingState text="正在加载角色..." />
          ) : (
            roles.map((role) => (
              <button
                className={`role-row ${selected === role.id ? "selected" : ""}`}
                key={role.id}
                onClick={() => setSelected(role.id)}
              >
                <strong>{role.name}</strong>
                <span>{role.code}</span>
              </button>
            ))
          )}
        </div>
        <div className="permission-matrix">
          <div className="role-permission-summary">
            <div>
              <span className="section-label">当前角色</span>
              <strong>{active?.name || "选择角色"}</strong>
            </div>
            <span className="count-badge">
              {active?.permissions.length ?? 0} / {permissions.length} 项
            </span>
          </div>
          <div className="permission-group-grid">
            {loading ? (
              <AdminLoadingState text="正在加载权限矩阵..." />
            ) : (
              Object.entries(permissionGroups).map(([group, items]) => (
                <div className="permission-group-card" key={group}>
                  <div className="section-label">{group.toUpperCase()}</div>
                  {items.map((permission) => {
                    const checked = Boolean(
                      active?.permissions.some(
                        (item) => item.id === permission.id,
                      ),
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
                </div>
              ))
            )}
          </div>
          {message && <div className="alert success">{message}</div>}
        </div>
      </div>
    </section>
  );
}

function MenusAdmin() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [selected, setSelected] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<{ roles: Role[]; permissions: Permission[] }>(
        "/system/roles",
      );
      setRoles(data.roles ?? []);
      setPermissions(data.permissions ?? []);
      setSelected((current) => current || data.roles?.[0]?.id || "");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload().catch((error) => setMessage(error.message));
  }, [reload]);

  const active = roles.find((role) => role.id === selected);
  const permissionGroups = permissions.reduce<Record<string, Permission[]>>(
    (groups, permission) => {
      const group = permission.code.split(":")[0] || "other";
      (groups[group] ??= []).push(permission);
      return groups;
    },
    {},
  );

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
      setMessage("菜单访问权限已更新");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "权限更新失败");
    }
  }

  return (
    <div className="admin-grid menu-admin-grid">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">MENU REGISTRY</span>
            <h3>菜单与页面</h3>
            <p className="panel-subtitle">
              菜单沿用页面权限控制，未授权的入口不会出现在侧栏。
            </p>
          </div>
          <span className="count-badge">{MENU_DEFINITIONS.length}</span>
        </div>
        <div className="menu-registry-list">
          {MENU_DEFINITIONS.map((item) => (
            <div className="menu-registry-row" key={item.code}>
              <span className="menu-registry-icon">{item.icon}</span>
              <div>
                <strong>{item.label}</strong>
                <span>
                  {item.group} · {item.permission || "登录后可见"}
                </span>
                <small>{item.description}</small>
              </div>
              <span
                className={`status-badge ${
                  item.permission &&
                  !active?.permissions.some(
                    (permission) => permission.code === item.permission,
                  )
                    ? "disabled"
                    : "succeeded"
                }`}
              >
                {item.permission &&
                !active?.permissions.some(
                  (permission) => permission.code === item.permission,
                )
                  ? "未授权"
                  : "可访问"}
              </span>
            </div>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">ROLE ACCESS</span>
            <h3>角色菜单权限</h3>
          </div>
          <select
            className="admin-inline-select"
            aria-label="选择角色"
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
          >
            <option value="">选择角色</option>
            {roles.map((role) => (
              <option key={role.id} value={role.id}>
                {role.name}
              </option>
            ))}
          </select>
        </div>
        <div className="menu-permission-groups">
          {loading ? (
            <AdminLoadingState text="正在加载角色菜单权限..." />
          ) : (
            Object.entries(permissionGroups).map(([group, items]) => (
              <div className="menu-permission-group" key={group}>
                <div className="section-label">{group.toUpperCase()}</div>
                {items.map((permission) => (
                  <label className="permission-row" key={permission.id}>
                    <input
                      type="checkbox"
                      checked={Boolean(
                        active?.permissions.some(
                          (item) => item.id === permission.id,
                        ),
                      )}
                      onChange={() => void toggle(permission.id)}
                    />
                    <span>
                      <strong>{permission.name}</strong>
                      <small>{permission.code}</small>
                    </span>
                  </label>
                ))}
              </div>
            ))
          )}
        </div>
        {message && <div className="alert success">{message}</div>}
      </section>
    </div>
  );
}

function TeamsAdmin() {
  const [teams, setTeams] = useState<ManagedTeam[]>([]);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [selected, setSelected] = useState<ManagedTeam | null>(null);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ name: "", code: "" });
  const [memberForm, setMemberForm] = useState({ userId: "", isLead: false });
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [teamData, userData] = await Promise.all([
        api<ManagedTeam[]>("/system/teams"),
        api<ManagedUser[]>("/system/users"),
      ]);
      setTeams(teamData ?? []);
      setUsers(userData ?? []);
    } finally {
      setLoading(false);
    }
  }, []);
  useEffect(() => {
    void reload().catch((error) => setMessage(error.message));
  }, [reload]);

  function openTeam(team: ManagedTeam) {
    setSelected(team);
    setForm({ name: team.name, code: team.code });
    setMemberForm({ userId: "", isLead: false });
    setMessage("");
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    try {
      await api("/system/teams", { method: "POST", bodyJson: form });
      setForm({ name: "", code: "" });
      await reload();
      setMessage("团队已创建");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "团队创建失败");
    } finally {
      setSaving(false);
    }
  }

  async function updateTeam(event: React.FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setSaving(true);
    setMessage("");
    try {
      await api<ManagedTeam>(`/system/teams/${selected.id}`, {
        method: "PATCH",
        bodyJson: form,
      });
      const nextTeams = await api<ManagedTeam[]>("/system/teams");
      setTeams(nextTeams ?? []);
      const updated = (nextTeams ?? []).find((team) => team.id === selected.id);
      if (updated) setSelected(updated);
      setMessage("部门信息已更新");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "部门更新失败");
    } finally {
      setSaving(false);
    }
  }

  async function addMember(event: React.FormEvent) {
    event.preventDefault();
    if (!selected || !memberForm.userId) return;
    setSaving(true);
    setMessage("");
    try {
      await api(`/system/teams/${selected.id}/members`, {
        method: "POST",
        bodyJson: memberForm,
      });
      const nextTeams = await api<ManagedTeam[]>("/system/teams");
      setTeams(nextTeams ?? []);
      const updated = (nextTeams ?? []).find((team) => team.id === selected.id);
      if (updated) setSelected(updated);
      setMemberForm({ userId: "", isLead: false });
      setMessage("部门成员已更新");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "成员更新失败");
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="admin-grid teams-admin-grid">
      <section className="panel admin-list-panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">DEPARTMENTS</span>
            <h3>部门与成员</h3>
            <p className="panel-subtitle">
              部门对应团队数据域，成员关系会影响产品与生成任务的可见范围。
            </p>
          </div>
          <span className="count-badge">{teams.length}</span>
        </div>
        <div className="admin-table">
          <div className="admin-table-head">
            <span>部门</span>
            <span>编码</span>
            <span>成员</span>
          </div>
          {loading ? (
            <AdminLoadingState text="正在加载部门和成员..." />
          ) : (
            teams.map((team) => (
              <button
                className={`admin-table-row ${selected?.id === team.id ? "selected" : ""}`}
                type="button"
                key={team.id}
                onClick={() => openTeam(team)}
              >
                <span>
                  <strong>{team.name}</strong>
                  <small>
                    {team.members.find((member) => member.isLead)
                      ?.displayName || "未设置负责人"}
                  </small>
                </span>
                <span className="mono">{team.code}</span>
                <span>{team.members.length} 人</span>
              </button>
            ))
          )}
        </div>
      </section>
      <form className="panel form-panel admin-create-panel" onSubmit={create}>
        <div className="panel-heading">
          <div>
            <span className="eyebrow">NEW TEAM</span>
            <h3>新增部门</h3>
          </div>
        </div>
        <label>
          部门名称
          <input
            required
            value={selected ? "" : form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
        </label>
        <label>
          部门编码
          <input
            required
            value={selected ? "" : form.code}
            onChange={(event) => setForm({ ...form, code: event.target.value })}
          />
        </label>
        {message && <div className="alert success">{message}</div>}
        <button
          className="button primary"
          disabled={saving || Boolean(selected)}
        >
          {selected ? "请先关闭编辑抽屉" : "创建部门"}
        </button>
      </form>
      {selected && (
        <div
          className="drawer-backdrop"
          role="presentation"
          onClick={() => setSelected(null)}
        >
          <aside
            className="admin-drawer"
            role="dialog"
            aria-modal="true"
            aria-label="编辑部门"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="admin-drawer-header">
              <div>
                <span className="eyebrow">DEPARTMENT</span>
                <h3>{selected.name}</h3>
                <p>
                  {selected.members.length} 名成员 · {selected.code}
                </p>
              </div>
              <button
                className="icon-button"
                type="button"
                title="关闭编辑"
                aria-label="关闭编辑"
                onClick={() => setSelected(null)}
              >
                ×
              </button>
            </div>
            <form className="admin-drawer-form" onSubmit={updateTeam}>
              <label>
                部门名称
                <input
                  required
                  value={form.name}
                  onChange={(event) =>
                    setForm({ ...form, name: event.target.value })
                  }
                />
              </label>
              <label>
                部门编码
                <input
                  required
                  value={form.code}
                  onChange={(event) =>
                    setForm({ ...form, code: event.target.value })
                  }
                />
              </label>
              <button className="button primary" disabled={saving}>
                保存部门
              </button>
            </form>
            <form
              className="drawer-section drawer-member-form"
              onSubmit={addMember}
            >
              <div className="drawer-section-heading">
                <span className="section-label">MEMBERS</span>
                <strong>添加部门成员</strong>
              </div>
              <select
                required
                value={memberForm.userId}
                onChange={(event) =>
                  setMemberForm({ ...memberForm, userId: event.target.value })
                }
              >
                <option value="">选择用户</option>
                {users.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.displayName} · {user.email}
                  </option>
                ))}
              </select>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={memberForm.isLead}
                  onChange={(event) =>
                    setMemberForm({
                      ...memberForm,
                      isLead: event.target.checked,
                    })
                  }
                />
                设为部门负责人
              </label>
              <button className="button ghost" disabled={saving}>
                添加成员
              </button>
              <div className="drawer-member-list">
                {selected.members.map((member) => (
                  <div className="drawer-member-row" key={member.id}>
                    <span>
                      <strong>{member.displayName}</strong>
                      <small>{member.email}</small>
                    </span>
                    {member.isLead && <span className="tag">负责人</span>}
                  </div>
                ))}
              </div>
            </form>
            {message && <div className="alert success">{message}</div>}
          </aside>
        </div>
      )}
    </div>
  );
}

function SettingsAdmin({ canWrite = true }: { canWrite?: boolean }) {
  const [settings, setSettings] = useState<SystemSetting[]>([]);
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const [secret, setSecret] = useState(false);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<SystemSetting[]>("/system/settings");
      setSettings(data ?? []);
    } finally {
      setLoading(false);
    }
  }, []);
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
          {loading ? (
            <AdminLoadingState text="正在加载系统设置..." />
          ) : settings.length ? (
            settings.map((setting) => (
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
            ))
          ) : (
            <EmptyState text="暂未配置系统设置" />
          )}
        </div>
      </section>
      {canWrite && (
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
      )}
    </div>
  );
}

function ProvidersAdmin({ canWrite = true }: { canWrite?: boolean }) {
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
    imageAspectRatios: "1:1, 4:5, 16:9",
    videoAspectRatios: "16:9, 9:16, 1:1",
    maxCount: "4",
    durationOptions: "5, 10, 15",
    referenceImage: true,
  });
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<ModelProvider[]>("/model-gateway/providers");
      setProviders(data ?? []);
    } finally {
      setLoading(false);
    }
  }, []);
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
            imageAspectRatios: parseCommaList(profileForm.imageAspectRatios),
            videoAspectRatios: parseCommaList(profileForm.videoAspectRatios),
            maxCount: Number(profileForm.maxCount) || 1,
            durationOptions: parseNumberList(profileForm.durationOptions),
            referenceImage: profileForm.referenceImage,
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
          {loading ? (
            <AdminLoadingState text="正在加载模型供应商..." />
          ) : providers.length ? (
            providers.map((provider) => (
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
                <StatusBadge
                  status={provider.enabled ? "ACTIVE" : "DISABLED"}
                />
              </div>
            ))
          ) : (
            <EmptyState text="暂未配置模型供应商" />
          )}
        </div>
      </section>
      <div className="admin-form-stack">
        {canWrite && (
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
        )}
        {canWrite && (
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
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={profileForm.referenceImage}
                  onChange={(event) =>
                    setProfileForm({
                      ...profileForm,
                      referenceImage: event.target.checked,
                    })
                  }
                />
                支持参考图
              </label>
            </div>
            <div className="compact-form-grid model-capability-grid">
              <label>
                图片画幅
                <input
                  value={profileForm.imageAspectRatios}
                  onChange={(event) =>
                    setProfileForm({
                      ...profileForm,
                      imageAspectRatios: event.target.value,
                    })
                  }
                  placeholder="1:1, 4:5, 16:9"
                />
              </label>
              <label>
                视频画幅
                <input
                  value={profileForm.videoAspectRatios}
                  onChange={(event) =>
                    setProfileForm({
                      ...profileForm,
                      videoAspectRatios: event.target.value,
                    })
                  }
                  placeholder="16:9, 9:16"
                />
              </label>
              <label>
                图片最大数量
                <input
                  type="number"
                  min={1}
                  max={16}
                  value={profileForm.maxCount}
                  onChange={(event) =>
                    setProfileForm({
                      ...profileForm,
                      maxCount: event.target.value,
                    })
                  }
                />
              </label>
              <label>
                视频时长（秒）
                <input
                  value={profileForm.durationOptions}
                  onChange={(event) =>
                    setProfileForm({
                      ...profileForm,
                      durationOptions: event.target.value,
                    })
                  }
                  placeholder="5, 10, 15"
                />
              </label>
            </div>
            <p className="form-note">
              每个模型独立保存能力；创作页只展示当前模型支持的画幅、数量、时长和参考图选项。
            </p>
            <button className="button primary">保存模型配置</button>
          </form>
        )}
      </div>
    </div>
  );
}

function SkillsAdmin({ canWrite = true }: { canWrite?: boolean }) {
  const [skills, setSkills] = useState<SkillProfile[]>([]);
  const [mode, setMode] = useState<"import" | "manual">("import");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({
    name: "",
    code: "",
    mediaType: "BOTH",
    version: "1.0.0",
    description: "",
    tags: "",
    promptTemplate: "",
    negativePrompt: "",
  });

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api<SkillProfile[]>("/skills/admin");
      setSkills(data ?? []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload().catch((error) => setMessage(error.message));
  }, [reload]);

  async function saveManual(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      await api<SkillProfile>("/skills", {
        method: "POST",
        bodyJson: {
          name: form.name,
          code: form.code,
          mediaType: form.mediaType,
          version: form.version || undefined,
          description: form.description || undefined,
          tags: parseCommaList(form.tags),
          promptTemplate: form.promptTemplate || undefined,
          negativePrompt: form.negativePrompt || undefined,
        },
      });
      setForm({
        name: "",
        code: "",
        mediaType: "BOTH",
        version: "1.0.0",
        description: "",
        tags: "",
        promptTemplate: "",
        negativePrompt: "",
      });
      await reload();
      setMessage("Skill 已保存，可在图片或视频创作页使用");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Skill 保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function importSkills(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    setBusy(true);
    setMessage("");
    try {
      const parsed = JSON.parse(await file.text()) as unknown;
      const records = Array.isArray(parsed) ? parsed : [parsed];
      let imported = 0;
      for (const value of records) {
        if (!value || typeof value !== "object") continue;
        const raw = value as Record<string, unknown>;
        const name = String(raw.name ?? raw.title ?? "未命名 Skill").trim();
        if (!name) continue;
        const mediaType = normalizeSkillType(
          raw.mediaType ?? raw.type ?? raw.kind,
        );
        await api<SkillProfile>("/skills", {
          method: "POST",
          bodyJson: {
            name,
            code: String(raw.code ?? slugifySkillCode(name)),
            mediaType,
            version: raw.version ? String(raw.version) : undefined,
            description: raw.description ? String(raw.description) : undefined,
            tags: Array.isArray(raw.tags)
              ? raw.tags.map(String)
              : parseCommaList(String(raw.tags ?? "")),
            promptTemplate: String(
              raw.promptTemplate ?? raw.prompt ?? raw.instructions ?? "",
            ),
            negativePrompt: String(raw.negativePrompt ?? ""),
            settings:
              raw.settings ??
              (raw.parameters && typeof raw.parameters === "object"
                ? raw.parameters
                : {}),
          },
        });
        imported += 1;
      }
      await reload();
      setMessage(
        imported ? `已导入 ${imported} 个 Skill` : "文件中没有可导入的 Skill",
      );
    } catch (error) {
      setMessage(
        error instanceof Error
          ? `导入失败：${error.message}`
          : "Skill 文件导入失败",
      );
    } finally {
      setBusy(false);
    }
  }

  async function toggleSkill(skill: SkillProfile) {
    setBusy(true);
    setMessage("");
    try {
      await api(`/skills/${skill.id}`, {
        method: "PATCH",
        bodyJson: { enabled: !skill.enabled },
      });
      await reload();
      setMessage(skill.enabled ? "Skill 已停用" : "Skill 已重新启用");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Skill 状态更新失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="skill-center">
      <div className="skill-intro">
        <div>
          <span className="eyebrow">SKILL LIBRARY</span>
          <h2>Skill 配置中心</h2>
          <p>
            把一套成熟的图片或视频创作方法保存成可复用模板，新手只需选择 Skill
            和产品即可开始。
          </p>
        </div>
        <div className="skill-intro-stat">
          <strong>{skills.filter((skill) => skill.enabled).length}</strong>
          <span>个可用 Skill</span>
        </div>
      </div>
      <div className="skill-layout">
        <section className="panel skill-list-panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">AVAILABLE SKILLS</span>
              <h3>已配置 Skill</h3>
            </div>
            <span className="count-badge">{skills.length}</span>
          </div>
          <div className="skill-list">
            {loading ? (
              <AdminLoadingState text="正在加载 Skill 配置..." />
            ) : skills.length ? (
              skills.map((skill) => (
                <div
                  className={`skill-row ${!skill.enabled ? "disabled" : ""}`}
                  key={skill.id}
                >
                  <div className="skill-row-icon">
                    {skill.mediaType === "VIDEO"
                      ? "▶"
                      : skill.mediaType === "IMAGE"
                        ? "✦"
                        : "◆"}
                  </div>
                  <div className="skill-row-copy">
                    <div className="skill-row-title">
                      <strong>{skill.name}</strong>
                      <StatusBadge
                        status={skill.enabled ? "ACTIVE" : "DISABLED"}
                      />
                    </div>
                    <span>
                      {skill.code} · {skill.mediaType} · v
                      {skill.version || "1.0.0"}
                    </span>
                    <small>{skill.description || "未填写使用说明"}</small>
                    {Array.isArray(skill.tags) && skill.tags.length > 0 && (
                      <div className="skill-tag-list">
                        {skill.tags.slice(0, 4).map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
                    )}
                  </div>
                  {canWrite && (
                    <button
                      className="button ghost small skill-toggle"
                      type="button"
                      disabled={busy}
                      onClick={() => void toggleSkill(skill)}
                    >
                      {skill.enabled ? "停用" : "启用"}
                    </button>
                  )}
                </div>
              ))
            ) : (
              <EmptyState text="还没有 Skill，请导入一个 JSON 配置" />
            )}
          </div>
        </section>
        {canWrite && (
          <section className="panel skill-editor-panel">
            <div className="panel-heading">
              <div>
                <span className="eyebrow">IMPORT OR CREATE</span>
                <h3>添加创作 Skill</h3>
              </div>
            </div>
            <div className="segmented skill-mode-switcher">
              <button
                type="button"
                className={mode === "import" ? "active" : ""}
                onClick={() => setMode("import")}
              >
                导入 JSON
              </button>
              <button
                type="button"
                className={mode === "manual" ? "active" : ""}
                onClick={() => setMode("manual")}
              >
                手动创建
              </button>
            </div>
            {mode === "import" ? (
              <div className="skill-import-box">
                <label className="skill-dropzone">
                  <span className="skill-dropzone-icon">↑</span>
                  <strong>选择 Skill JSON 文件</strong>
                  <small>
                    支持单个对象或对象数组，导入后可直接在创作页选择
                  </small>
                  <input
                    type="file"
                    accept=".json,application/json"
                    disabled={busy}
                    onChange={(event) => void importSkills(event)}
                  />
                </label>
                <div className="skill-schema-note">
                  <strong>推荐字段</strong>
                  <code>
                    name · code · mediaType · promptTemplate · negativePrompt ·
                    tags
                  </code>
                  <span>
                    mediaType 可填写 IMAGE、VIDEO 或 BOTH；promptTemplate
                    会自动追加到产品记忆 Prompt。
                  </span>
                </div>
              </div>
            ) : (
              <form className="form-panel skill-form" onSubmit={saveManual}>
                <div className="compact-form-grid">
                  <label>
                    Skill 名称
                    <input
                      required
                      value={form.name}
                      onChange={(event) =>
                        setForm({ ...form, name: event.target.value })
                      }
                      placeholder="例如：高级产品主图"
                    />
                  </label>
                  <label>
                    唯一编码
                    <input
                      required
                      value={form.code}
                      onChange={(event) =>
                        setForm({ ...form, code: event.target.value })
                      }
                      placeholder="product-hero"
                    />
                  </label>
                  <label>
                    适用类型
                    <select
                      value={form.mediaType}
                      onChange={(event) =>
                        setForm({ ...form, mediaType: event.target.value })
                      }
                    >
                      <option value="BOTH">图片 + 视频</option>
                      <option value="IMAGE">仅图片</option>
                      <option value="VIDEO">仅视频</option>
                    </select>
                  </label>
                  <label>
                    版本
                    <input
                      value={form.version}
                      onChange={(event) =>
                        setForm({ ...form, version: event.target.value })
                      }
                    />
                  </label>
                </div>
                <label>
                  使用说明
                  <input
                    value={form.description}
                    onChange={(event) =>
                      setForm({ ...form, description: event.target.value })
                    }
                    placeholder="告诉团队什么时候使用这个 Skill"
                  />
                </label>
                <label>
                  标签
                  <input
                    value={form.tags}
                    onChange={(event) =>
                      setForm({ ...form, tags: event.target.value })
                    }
                    placeholder="电商主图,棚拍,高级感"
                  />
                </label>
                <label>
                  Prompt 模板
                  <textarea
                    required
                    rows={5}
                    value={form.promptTemplate}
                    onChange={(event) =>
                      setForm({ ...form, promptTemplate: event.target.value })
                    }
                    placeholder="例如：商业棚拍，主体居中，柔和侧光，保留真实材质..."
                  />
                </label>
                <label>
                  禁止规则补充
                  <textarea
                    rows={3}
                    value={form.negativePrompt}
                    onChange={(event) =>
                      setForm({ ...form, negativePrompt: event.target.value })
                    }
                    placeholder="例如：禁止出现额外 Logo、禁止改变产品结构"
                  />
                </label>
                <button className="button primary" disabled={busy}>
                  {busy ? "保存中..." : "保存并启用 Skill"}
                </button>
              </form>
            )}
            {message && <div className="alert success">{message}</div>}
          </section>
        )}
      </div>
    </div>
  );
}

function AuditAdmin() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    void api<AuditLog[]>("/system/audit-logs")
      .then((data) => setLogs(data ?? []))
      .catch((error) => setMessage(error.message))
      .finally(() => setLoading(false));
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
        {loading ? (
          <AdminLoadingState text="正在加载审计日志..." />
        ) : logs.length ? (
          logs.map((log) => (
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
          ))
        ) : (
          <EmptyState text="暂未产生审计日志" />
        )}
      </div>
    </section>
  );
}

function GenerationStudio({
  type,
  products,
  tasks,
  profiles,
  selectedProductId,
  onProductChange,
  onProfiles,
  onTaskUpdated,
  onCreated,
}: {
  type: "IMAGE" | "VIDEO";
  products: Product[];
  tasks: Task[];
  profiles: ModelProfile[];
  selectedProductId: string;
  onProductChange: (id: string) => void;
  onProfiles: (profiles: ModelProfile[]) => void;
  onTaskUpdated: (task: Task) => void;
  onCreated: (task: Task) => void;
}) {
  const [idea, setIdea] = useState(
    type === "IMAGE" ? "生成一组高级电商主图" : "生成一个高级产品广告视频",
  );
  const [profileId, setProfileId] = useState("");
  const [skills, setSkills] = useState<SkillProfile[]>([]);
  const [skillId, setSkillId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState("");
  const [modelLoadError, setModelLoadError] = useState("");
  const [promptPreview, setPromptPreview] = useState("");
  const [negativePrompt, setNegativePrompt] = useState("");
  const [memoryVersion, setMemoryVersion] = useState<number | null>(null);
  const [assetUrls, setAssetUrls] = useState<string[]>([]);
  const [productAssets, setProductAssets] = useState<ProductAsset[]>([]);
  const [assetPickerOpen, setAssetPickerOpen] = useState(false);
  const [referenceUploading, setReferenceUploading] = useState(false);
  const [aspectRatio, setAspectRatio] = useState("");
  const [imageCount, setImageCount] = useState("1");
  const [videoDuration, setVideoDuration] = useState("");
  const [watchedTaskId, setWatchedTaskId] = useState("");
  const [previewTask, setPreviewTask] = useState<Task | null>(
    tasks.find((task) => task.type === type && task.assets?.length) ?? null,
  );
  useEffect(() => {
    void api<ModelProfile[]>(`/model-gateway/profiles?type=${type}`)
      .then((next) => {
        setModelLoadError("");
        onProfiles(next ?? []);
        setProfileId((current) =>
          next?.some((profile) => profile.id === current)
            ? current
            : next?.[0]?.id || "",
        );
      })
      .catch((error) => {
        setModelLoadError(
          error instanceof Error ? error.message : "可用模型读取失败",
        );
        onProfiles([]);
        setProfileId("");
      });
  }, [onProfiles, type]);
  useEffect(() => {
    void api<SkillProfile[]>(`/skills?type=${type}`)
      .then((next) => {
        const available = next ?? [];
        setSkills(available);
        setSkillId((current) =>
          available.some((skill) => skill.id === current)
            ? current
            : available[0]?.id || "",
        );
      })
      .catch(() => {
        setSkills([]);
        setSkillId("");
      });
  }, [type]);
  useEffect(() => {
    const nextPreview =
      tasks.find((task) => task.type === type && task.assets?.length) ?? null;
    setPreviewTask((current) => {
      if (current?.type === type) {
        return tasks.find((task) => task.id === current.id) ?? current;
      }
      return nextPreview;
    });
  }, [tasks, type]);
  useEffect(() => {
    if (!watchedTaskId) return;
    let disposed = false;
    const refresh = async () => {
      try {
        const latest = await api<Task>(`/generation-tasks/${watchedTaskId}`);
        if (disposed) return;
        onTaskUpdated(latest);
        setPreviewTask(latest);
        if (
          ["SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"].includes(
            latest.status,
          )
        ) {
          setWatchedTaskId("");
        }
      } catch {
        // SSE reconnects and the next event will retry the detail request.
      }
    };
    const close = streamGeneration(watchedTaskId, (event) => {
      let payload: Record<string, unknown> = {};
      try {
        payload =
          typeof event.data === "string"
            ? (JSON.parse(event.data) as Record<string, unknown>)
            : (event.data as Record<string, unknown>);
      } catch {
        payload = {};
      }
      if (typeof payload.status === "string") {
        setPreviewTask((current) =>
          current ? { ...current, status: String(payload.status) } : current,
        );
      }
      if (
        ["SUCCEEDED", "FAILED", "CANCELLED", "EXPIRED"].includes(
          String(payload.status),
        )
      ) {
        void refresh();
      }
    });
    void refresh();
    return () => {
      disposed = true;
      close();
    };
  }, [onTaskUpdated, watchedTaskId]);
  useEffect(() => {
    setPromptPreview("");
    setNegativePrompt("");
    setMemoryVersion(null);
    setAssetUrls([]);
    setAspectRatio("");
    setImageCount("1");
    setVideoDuration("");
    setSkillId("");
  }, [selectedProductId, type]);
  useEffect(() => {
    if (!selectedProductId) {
      setProductAssets([]);
      setAssetUrls([]);
      return;
    }
    void api<ProductAsset[]>(`/products/${selectedProductId}/assets`)
      .then((assets) => {
        setProductAssets(assets ?? []);
        setAssetUrls((current) =>
          current.filter((assetId) =>
            (assets ?? []).some((asset) => asset.id === assetId),
          ),
        );
      })
      .catch(() => setProductAssets([]));
  }, [selectedProductId]);
  async function compilePrompt() {
    if (!selectedProductId || !idea.trim()) {
      setMessage("选择产品并输入创意后才能生成 Prompt");
      return;
    }
    try {
      const compiled = await api<{
        promptText: string;
        negativePrompt: string;
        memoryVersion: number;
      }>(`/products/${selectedProductId}/prompt/compile`, {
        method: "POST",
        bodyJson: {
          idea,
          type,
          ...(skillId ? { skillId } : {}),
          ...(aspectRatio ? { aspectRatio } : {}),
        },
      });
      setPromptPreview(compiled.promptText);
      setNegativePrompt(compiled.negativePrompt);
      setMemoryVersion(compiled.memoryVersion);
      setMessage("已引用产品记忆");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Prompt 预览失败");
    }
  }

  async function uploadExtraReferences(
    event: React.ChangeEvent<HTMLInputElement>,
  ) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length) return;
    if (!selectedProductId) {
      setMessage("请先选择产品，再添加额外参考图");
      return;
    }
    if (!supportsReferenceImages) {
      setMessage("当前模型不支持参考图");
      return;
    }
    setReferenceUploading(true);
    setMessage("");
    try {
      const created: ProductAsset[] = [];
      for (const file of files) {
        const formData = new FormData();
        formData.set("file", file);
        formData.set("type", "GENERATION_REFERENCE");
        formData.set("view", "custom");
        created.push(
          await upload<ProductAsset>(
            `/products/${selectedProductId}/assets`,
            formData,
          ),
        );
      }
      setProductAssets((current) => [...created, ...current]);
      setAssetUrls((current) => [
        ...new Set([...current, ...created.map((asset) => asset.id)]),
      ]);
      setAssetPickerOpen(true);
      setMessage(`已添加 ${created.length} 张额外参考图`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "参考图上传失败");
    } finally {
      setReferenceUploading(false);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedProductId) return setMessage("请先选择产品");
    if (!profileId) return setMessage("请先在系统管理中配置模型");
    const count = Number(imageCount);
    const duration = Number(videoDuration);
    if (
      type === "IMAGE" &&
      (!Number.isInteger(count) || count < 1 || count > maxImageCount)
    ) {
      return setMessage(`图片数量必须是 1-${maxImageCount} 张`);
    }
    if (
      type === "VIDEO" &&
      (!Number.isInteger(duration) || !durationOptions.includes(duration))
    ) {
      return setMessage("请选择当前模型支持的视频时长");
    }
    setSubmitting(true);
    setMessage("");
    try {
      const options: Record<string, unknown> = {
        ...(aspectRatio ? { aspectRatio } : {}),
        ...(skillId ? { skillId } : {}),
        ...(type === "IMAGE" ? { count } : { duration }),
      };
      const task = await api<Task>("/generation-tasks", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        bodyJson: {
          productId: selectedProductId,
          modelProfileId: profileId,
          type,
          idea,
          inputAssets: assetUrls,
          options,
        },
      });
      onCreated(task);
      setPreviewTask(task);
      setWatchedTaskId(task.id);
      setMessage("任务已进入队列");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "任务提交失败");
    } finally {
      setSubmitting(false);
    }
  }
  const visibleProfiles = profiles.filter((profile) => {
    const capability = profile.capability ?? {};
    return capability[type === "IMAGE" ? "image" : "video"] === true;
  });
  const selectedProfile = visibleProfiles.find(
    (profile) => profile.id === profileId,
  );
  const capability = (selectedProfile?.capability ?? {}) as ModelCapability;
  const ratioOptions = getModelAspectRatios(capability, type);
  const maxImageCount = Math.max(1, Number(capability.maxCount) || 4);
  const durationOptions =
    Array.isArray(capability.durationOptions) &&
    capability.durationOptions.length
      ? capability.durationOptions
      : [5, 10, 15];
  const supportsReferenceImages = capability.referenceImage !== false;
  useEffect(() => {
    if (!selectedProfile) return;
    const nextRatios = getModelAspectRatios(capability, type);
    setAspectRatio((current) =>
      current && nextRatios.includes(current) ? current : nextRatios[0] || "",
    );
    if (type === "VIDEO") {
      setVideoDuration((current) => {
        const numeric = Number(current);
        return numeric && durationOptions.includes(numeric)
          ? current
          : String(durationOptions[0] ?? 5);
      });
    } else {
      setImageCount((current) => {
        const numeric = Number(current);
        return numeric >= 1 && numeric <= maxImageCount ? current : "1";
      });
    }
  }, [capability, durationOptions, maxImageCount, selectedProfile, type]);
  const currentProduct = products.find(
    (product) => product.id === selectedProductId,
  );
  const visibleTasks = tasks.filter((task) => task.type === type);
  return (
    <div className={`generation-workbench generation-${type.toLowerCase()}`}>
      <aside className="generation-control-rail">
        <div className="generation-rail-heading">
          <span className="generation-rail-icon">
            {type === "IMAGE" ? "✦" : "▶"}
          </span>
          <div>
            <span className="eyebrow">
              {type === "IMAGE" ? "IMAGE" : "VIDEO"}
            </span>
            <strong>{type === "IMAGE" ? "图片创作" : "视频创作"}</strong>
          </div>
        </div>
        <div className="generation-control-body">
          <label className="compact-label">
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
          <div className="selected-product-chip">
            <span className="product-avatar small">
              {currentProduct?.name?.slice(0, 1) || "?"}
            </span>
            <span>
              <strong>{currentProduct?.name || "未选择产品"}</strong>
              <small>
                {currentProduct?.brand || "产品中心配置"} · 自动引用 Product
                Memory
              </small>
            </span>
          </div>
          <button
            type="button"
            className={`asset-reference-trigger ${assetUrls.length ? "selected" : ""}`}
            onClick={() => setAssetPickerOpen((current) => !current)}
          >
            <span>▧</span>
            <span>
              <strong>产品参考素材</strong>
              <small>
                {assetUrls.length
                  ? `已选择 ${assetUrls.length} 个角度`
                  : `${productAssets.length} 个素材可引用`}
              </small>
            </span>
            <span>›</span>
          </button>
          {assetPickerOpen && (
            <div className="asset-reference-picker">
              <div className="asset-reference-picker-header">
                <span>选择本次生成要带入的产品素材</span>
                <button
                  type="button"
                  title="关闭素材选择"
                  aria-label="关闭素材选择"
                  onClick={() => setAssetPickerOpen(false)}
                >
                  ×
                </button>
              </div>
              {productAssets.length ? (
                <div className="asset-reference-list">
                  {productAssets.map((asset) => {
                    const checked = assetUrls.includes(asset.id);
                    return (
                      <label
                        className={`asset-reference-item ${checked ? "selected" : ""}`}
                        key={asset.id}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={!supportsReferenceImages}
                          onChange={() =>
                            setAssetUrls((current) =>
                              checked
                                ? current.filter((id) => id !== asset.id)
                                : [...current, asset.id],
                            )
                          }
                        />
                        <span className="asset-reference-preview">
                          {asset.mimeType.startsWith("video/") ? (
                            <video src={asset.url} muted />
                          ) : (
                            <img
                              src={asset.url}
                              alt={asset.originalName || "产品素材"}
                            />
                          )}
                        </span>
                        <span className="asset-reference-copy">
                          <strong>{asset.view || "未标记视角"}</strong>
                          <small>{asset.type}</small>
                        </span>
                      </label>
                    );
                  })}
                </div>
              ) : (
                <p className="asset-reference-empty">
                  当前产品还没有上传参考素材，请到产品中心补充多角度图片。
                </p>
              )}
              <label className="button ghost compact-button file-button asset-reference-upload">
                {referenceUploading ? "上传中..." : "添加额外参考图"}
                <input
                  type="file"
                  multiple
                  accept="image/*,video/*"
                  disabled={referenceUploading || !supportsReferenceImages}
                  onChange={(event) => void uploadExtraReferences(event)}
                />
              </label>
              {!supportsReferenceImages && (
                <p className="asset-reference-empty">
                  当前模型未开启参考图能力，请切换模型或在系统配置中开启。
                </p>
              )}
            </div>
          )}
          <label className="compact-label">
            模型
            <select
              value={profileId}
              onChange={(event) => setProfileId(event.target.value)}
              disabled={!visibleProfiles.length}
            >
              <option value="">
                {visibleProfiles.length ? "选择模型" : "暂无可用模型"}
              </option>
              {visibleProfiles.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name} · {profile.provider?.name || "Gateway"}
                </option>
              ))}
            </select>
          </label>
          {(modelLoadError || !visibleProfiles.length) && (
            <div className="generation-model-empty">
              <strong>
                {modelLoadError
                  ? "模型配置读取失败"
                  : type === "IMAGE"
                    ? "暂无可用图片模型"
                    : "暂无可用视频模型"}
              </strong>
              <span>请到“系统配置 → 模型供应商”添加并启用对应能力的模型。</span>
            </div>
          )}
          <div className="generation-control-divider" />
          <label className="compact-label">
            创作 Skill
            <select
              value={skillId}
              onChange={(event) => setSkillId(event.target.value)}
              disabled={!skills.length}
            >
              <option value="">
                {skills.length ? "不使用 Skill" : "暂无可用 Skill"}
              </option>
              {skills.map((skill) => (
                <option key={skill.id} value={skill.id}>
                  {skill.name} · {skill.mediaType}
                </option>
              ))}
            </select>
          </label>
          {type === "IMAGE" ? (
            <>
              <label className="compact-label">
                画面比例
                <select
                  value={aspectRatio}
                  onChange={(event) => setAspectRatio(event.target.value)}
                  disabled={!ratioOptions.length}
                >
                  {ratioOptions.length ? (
                    ratioOptions.map((ratio) => (
                      <option value={ratio} key={ratio}>
                        {ratio}
                      </option>
                    ))
                  ) : (
                    <option value="">模型未配置画幅</option>
                  )}
                </select>
              </label>
              <div className="range-field">
                <div className="range-field-heading">
                  <span>生成数量</span>
                  <output>{imageCount || "1"} 张</output>
                </div>
                <input
                  type="range"
                  min={1}
                  max={maxImageCount}
                  step={1}
                  value={Math.min(
                    maxImageCount,
                    Math.max(1, Number(imageCount) || 1),
                  )}
                  onChange={(event) => setImageCount(event.target.value)}
                />
                <input
                  type="number"
                  min={1}
                  max={maxImageCount}
                  value={imageCount}
                  onChange={(event) => setImageCount(event.target.value)}
                  aria-label="生成图片数量"
                />
                <small>当前模型最多 {maxImageCount} 张</small>
              </div>
            </>
          ) : (
            <>
              <label className="compact-label">
                时长
                <select
                  value={videoDuration}
                  onChange={(event) => setVideoDuration(event.target.value)}
                >
                  {durationOptions.map((duration) => (
                    <option value={duration} key={duration}>
                      {duration} 秒
                    </option>
                  ))}
                </select>
              </label>
              <label className="compact-label">
                画幅
                <select
                  value={aspectRatio}
                  onChange={(event) => setAspectRatio(event.target.value)}
                  disabled={!ratioOptions.length}
                >
                  {ratioOptions.length ? (
                    ratioOptions.map((ratio) => (
                      <option value={ratio} key={ratio}>
                        {ratio}
                      </option>
                    ))
                  ) : (
                    <option value="">模型未配置画幅</option>
                  )}
                </select>
              </label>
            </>
          )}
          <div className="generation-rail-status">
            <span className="status-dot" />
            <span>产品记忆已连接</span>
          </div>
        </div>
        <button
          type="button"
          className="generation-rail-history"
          onClick={() =>
            setPreviewTask(
              visibleTasks.find((task) => task.assets?.length) ?? null,
            )
          }
        >
          <span>◷</span>
          <span>查看全部历史</span>
          <span>{visibleTasks.length}</span>
        </button>
      </aside>
      <section className="generation-center">
        <div className="generation-center-header">
          <div>
            <span className="eyebrow">CREATIVE STUDIO</span>
            <h2>{type === "IMAGE" ? "为产品生成图片" : "为产品生成视频"}</h2>
          </div>
          <div className="generation-view-switcher" aria-label="创作模式">
            <span className="generation-mode-active">
              {type === "IMAGE" ? "图片模式" : "视频模式"}
            </span>
            <span>{previewTask ? "已选结果" : "等待生成"}</span>
          </div>
        </div>
        <div className="generation-preview-stage" aria-live="polite">
          {previewTask?.assets?.length ? (
            <div
              className={`generation-preview-grid ${previewTask.assets.length > 1 ? "multi" : ""}`}
            >
              {previewTask.assets.map((asset) =>
                asset.mimeType.startsWith("video/") ? (
                  <video key={asset.id} src={asset.url} controls />
                ) : (
                  <img key={asset.id} src={asset.url} alt="生成结果预览" />
                ),
              )}
            </div>
          ) : (
            <div className="generation-empty-preview">
              <div className="preview-orbit">
                <span>{type === "IMAGE" ? "✦" : "▶"}</span>
              </div>
              <strong>
                {currentProduct
                  ? "生成结果会在这里预览"
                  : "先选择产品，再开始创作"}
              </strong>
              <span>
                {currentProduct
                  ? "历史结果会在下方持续沉淀，可点击卡片切换预览"
                  : "产品中心的资料与规则会自动带入 Prompt"}
              </span>
            </div>
          )}
        </div>
        <form className="generation-prompt-composer" onSubmit={submit}>
          <div className="composer-topline">
            <span className="composer-label">创意描述</span>
            {memoryVersion && (
              <span className="memory-version">
                Product Memory v{memoryVersion}
              </span>
            )}
          </div>
          <textarea
            value={idea}
            onChange={(event) => setIdea(event.target.value)}
            rows={3}
            placeholder={
              type === "IMAGE"
                ? "例如：生成一组高级汽车产品主图，棚拍柔光，保留真实材质"
                : "例如：生成一个高级汽车广告视频，镜头从车灯推进到整车"
            }
          />
          <div className="composer-actions">
            <button
              className="button ghost compact-button"
              type="button"
              onClick={() => void compilePrompt()}
            >
              ✦ 生成 Prompt 预览
            </button>
            <button
              className="button primary generation-submit"
              disabled={submitting || !profileId}
            >
              {submitting
                ? "提交中..."
                : type === "IMAGE"
                  ? "生成图片"
                  : "生成视频"}
            </button>
          </div>
          {message && (
            <div
              className={`composer-message ${message.includes("失败") ? "error" : "success"}`}
            >
              {message}
            </div>
          )}
          {(promptPreview || negativePrompt) && (
            <details className="prompt-disclosure" open>
              <summary>查看已合并的 Prompt 与禁止规则</summary>
              <div className="prompt-disclosure-body">
                <p>{promptPreview || "尚未生成正向 Prompt"}</p>
                <small>{negativePrompt || "暂无禁止规则"}</small>
              </div>
            </details>
          )}
        </form>
        <div className="generation-history-board">
          <div className="history-board-heading">
            <div>
              <span className="eyebrow">GENERATED LIBRARY</span>
              <h3>{type === "IMAGE" ? "图片生成与历史" : "视频生成与历史"}</h3>
            </div>
            <span className="toolbar-note">点击卡片查看预览与编号</span>
          </div>
          <div className="history-board-grid">
            {visibleTasks.length ? (
              visibleTasks.map((task) => (
                <button
                  type="button"
                  key={task.id}
                  className={`history-board-card ${previewTask?.id === task.id ? "selected" : ""}`}
                  onClick={() => setPreviewTask(task)}
                >
                  <div className="history-board-preview">
                    {task.assets?.[0] ? (
                      task.assets[0].mimeType.startsWith("video/") ? (
                        <video src={task.assets[0].url} muted />
                      ) : (
                        <img src={task.assets[0].url} alt={task.idea} />
                      )
                    ) : (
                      <span>{task.status}</span>
                    )}
                  </div>
                  <div className="history-board-copy">
                    <strong>{task.historyCode || "待分配编号"}</strong>
                    <span>{task.idea}</span>
                    <StatusBadge status={task.status} />
                  </div>
                </button>
              ))
            ) : (
              <div className="history-board-empty">
                <span>○</span>
                <p>还没有{type === "IMAGE" ? "图片" : "视频"}生成记录</p>
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  );
}

type CanvasNodeKind =
  | "product"
  | "memory"
  | "prompt"
  | "generation"
  | "result"
  | "reference"
  | "text"
  | "image"
  | "video"
  | "config";

type CanvasGraphSnapshot = {
  nodes: Node[];
  edges: Edge[];
};

const canvasNodeMeta: Record<
  CanvasNodeKind,
  { eyebrow: string; title: string; detail: string; tone: string }
> = {
  product: {
    eyebrow: "SOURCE",
    title: "产品中心",
    detail: "绑定产品、SKU 与多角度素材",
    tone: "blue",
  },
  memory: {
    eyebrow: "MEMORY",
    title: "产品记忆",
    detail: "品牌视觉、事实与禁止规则",
    tone: "violet",
  },
  prompt: {
    eyebrow: "PROMPT",
    title: "Prompt Engine",
    detail: "将创意编译为可执行 Prompt",
    tone: "amber",
  },
  generation: {
    eyebrow: "MODEL",
    title: "生成任务",
    detail: "图片 / 视频模型网关",
    tone: "green",
  },
  result: {
    eyebrow: "OUTPUT",
    title: "结果画廊",
    detail: "回到历史并沉淀可复用素材",
    tone: "rose",
  },
  reference: {
    eyebrow: "ASSET",
    title: "参考素材",
    detail: "把产品图片或视频带入当前创作",
    tone: "blue",
  },
  text: {
    eyebrow: "TEXT",
    title: "创意说明",
    detail: "记录镜头、场景和提示词片段",
    tone: "amber",
  },
  image: {
    eyebrow: "IMAGE",
    title: "图片结果",
    detail: "在画布中整理可复用的图片结果",
    tone: "green",
  },
  video: {
    eyebrow: "VIDEO",
    title: "视频结果",
    detail: "在画布中整理可复用的视频结果",
    tone: "rose",
  },
  config: {
    eyebrow: "CONFIG",
    title: "生成配置",
    detail: "绑定产品、模型和生成参数",
    tone: "violet",
  },
};

function CanvasNode({ data, type }: NodeProps) {
  const nodeType = (data.kind || type || "product") as CanvasNodeKind;
  const meta = canvasNodeMeta[nodeType] ?? canvasNodeMeta.product;
  const title =
    typeof data.title === "string"
      ? data.title
      : typeof data.label === "string" && data.label.includes("·")
        ? data.label.split("·")[0].trim()
        : meta.title;
  const detail = typeof data.detail === "string" ? data.detail : meta.detail;
  return (
    <div className={`flow-business-node flow-node-${meta.tone}`}>
      <Handle type="target" position={Position.Left} />
      <span className="flow-node-eyebrow">{meta.eyebrow}</span>
      <strong>{title}</strong>
      <span>{detail}</span>
      <Handle type="source" position={Position.Right} />
    </div>
  );
}

function CanvasView({
  selectedProductId,
  products,
  tasks,
  onExit,
  onProductChange,
}: {
  selectedProductId: string;
  products: Product[];
  tasks: Task[];
  onExit: () => void;
  onProductChange: (id: string) => void;
}) {
  const [nodes, setNodes] = useNodesState(starterNodes);
  const [edges, setEdges] = useEdgesState(starterEdges);
  const [instance, setInstance] = useState<ReactFlowInstance | null>(null);
  const [canvasId, setCanvasId] = useState("");
  const [message, setMessage] = useState("");
  const [tool, setTool] = useState<"select" | "pan">("select");
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [showInspector, setShowInspector] = useState(true);
  const [backgroundMode, setBackgroundMode] = useState<"dots" | "lines">(
    "dots",
  );
  const [selectedNodeId, setSelectedNodeId] = useState("");
  const [savedAt, setSavedAt] = useState("");
  const [history, setHistory] = useState<
    Array<{ nodes: Node[]; edges: Edge[] }>
  >([]);
  const [future, setFuture] = useState<Array<{ nodes: Node[]; edges: Edge[] }>>(
    [],
  );
  const loadedRef = useRef(false);
  const nodesRef = useRef<Node[]>(starterNodes);
  const edgesRef = useRef<Edge[]>(starterEdges);
  const historyRef = useRef<CanvasGraphSnapshot[]>([]);
  const futureRef = useRef<CanvasGraphSnapshot[]>([]);
  const dragSnapshotRef = useRef<CanvasGraphSnapshot | null>(null);
  const pendingViewportRef = useRef<{
    x: number;
    y: number;
    zoom: number;
  } | null>(null);
  const nodeTypes = useMemo(
    () => ({
      canvas: CanvasNode,
      input: CanvasNode,
      default: CanvasNode,
      output: CanvasNode,
    }),
    [],
  );
  const cloneGraph = useCallback((graph: CanvasGraphSnapshot) => {
    return {
      nodes: graph.nodes.map((node) => ({
        ...node,
        data: { ...node.data },
        position: { ...node.position },
      })),
      edges: graph.edges.map((edge) => ({ ...edge })),
    };
  }, []);
  const graphEquals = useCallback(
    (left: CanvasGraphSnapshot, right: CanvasGraphSnapshot) =>
      JSON.stringify(left) === JSON.stringify(right),
    [],
  );
  const commitGraph = useCallback(
    (
      nextNodes: Node[],
      nextEdges: Edge[],
      previousGraph: CanvasGraphSnapshot = {
        nodes: nodesRef.current,
        edges: edgesRef.current,
      },
    ) => {
      const nextGraph = cloneGraph({ nodes: nextNodes, edges: nextEdges });
      const previous = cloneGraph(previousGraph);
      if (graphEquals(previous, nextGraph)) return;
      const nextHistory = [
        ...historyRef.current.slice(-19),
        { nodes: previous.nodes, edges: previous.edges },
      ];
      historyRef.current = nextHistory;
      futureRef.current = [];
      setHistory(nextHistory);
      setFuture([]);
      nodesRef.current = nextGraph.nodes;
      edgesRef.current = nextGraph.edges;
      setNodes(nextGraph.nodes);
      setEdges(nextGraph.edges);
    },
    [cloneGraph, graphEquals, setEdges, setNodes],
  );
  const handleNodesChange = useCallback(
    (changes: NodeChange[]) => {
      const nextNodes = applyNodeChanges(changes, nodesRef.current);
      if (changes.some((change) => change.type === "remove")) {
        const removedIds = new Set(
          changes
            .filter(
              (change): change is Extract<NodeChange, { type: "remove" }> =>
                change.type === "remove",
            )
            .map((change) => change.id),
        );
        const nextEdges = edgesRef.current.filter(
          (edge) =>
            !removedIds.has(edge.source) && !removedIds.has(edge.target),
        );
        commitGraph(nextNodes, nextEdges);
        setSelectedNodeId("");
        return;
      }
      if (changes.some((change) => change.type === "select")) {
        setSelectedNodeId(nextNodes.find((node) => node.selected)?.id ?? "");
      }
      nodesRef.current = nextNodes;
      setNodes(nextNodes);
    },
    [commitGraph, setNodes],
  );
  const handleEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      const nextEdges = applyEdgeChanges(changes, edgesRef.current);
      if (changes.some((change) => change.type === "remove")) {
        commitGraph(nodesRef.current, nextEdges);
        return;
      }
      edgesRef.current = nextEdges;
      setEdges(nextEdges);
    },
    [commitGraph, setEdges],
  );
  const onConnect = useCallback(
    (params: Connection) => {
      const nextEdges = addEdge(
        {
          ...params,
          animated: true,
          style: { stroke: "#9a8cff", strokeWidth: 2 },
        },
        edgesRef.current,
      );
      commitGraph(nodesRef.current, nextEdges);
    },
    [commitGraph],
  );
  const rememberGraph = useCallback(
    (nextNodes: Node[], nextEdges: Edge[]) => {
      commitGraph(nextNodes, nextEdges);
    },
    [commitGraph],
  );
  const createNode = useCallback(
    (kind: CanvasNodeKind) => {
      const position = instance?.screenToFlowPosition({
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
      }) ?? { x: 420, y: 260 };
      const meta = canvasNodeMeta[kind];
      const id = `${kind}-${Date.now()}`;
      const nextNode: Node = {
        id,
        type: "canvas",
        position: { x: position.x - 105, y: position.y - 55 },
        data: {
          kind,
          title: meta.title,
          detail: meta.detail,
          label: `${meta.title} · ${meta.eyebrow}`,
        },
      };
      rememberGraph([...nodesRef.current, nextNode], edgesRef.current);
      setSelectedNodeId(id);
      setAddMenuOpen(false);
    },
    [instance, rememberGraph],
  );
  const deleteSelectedNode = useCallback(() => {
    if (!selectedNodeId) return;
    const nextNodes = nodesRef.current.filter(
      (node) => node.id !== selectedNodeId,
    );
    const nextEdges = edgesRef.current.filter(
      (edge) =>
        edge.source !== selectedNodeId && edge.target !== selectedNodeId,
    );
    rememberGraph(nextNodes, nextEdges);
    setSelectedNodeId("");
  }, [rememberGraph, selectedNodeId]);
  const duplicateSelectedNode = useCallback(() => {
    const selected = nodesRef.current.find(
      (node) => node.id === selectedNodeId,
    );
    if (!selected) return;
    const id = `${selected.id}-copy-${Date.now()}`;
    const copy: Node = {
      ...selected,
      id,
      position: {
        x: selected.position.x + 40,
        y: selected.position.y + 40,
      },
      selected: false,
    };
    rememberGraph([...nodesRef.current, copy], edgesRef.current);
    setSelectedNodeId(id);
  }, [rememberGraph, selectedNodeId]);
  const undo = useCallback(() => {
    const previous = historyRef.current.at(-1);
    if (!previous) return;
    const currentGraph = cloneGraph({
      nodes: nodesRef.current,
      edges: edgesRef.current,
    });
    const nextHistory = historyRef.current.slice(0, -1);
    const nextFuture = [...futureRef.current, currentGraph];
    historyRef.current = nextHistory;
    futureRef.current = nextFuture;
    setHistory(nextHistory);
    setFuture(nextFuture);
    const restored = cloneGraph(previous);
    nodesRef.current = restored.nodes;
    edgesRef.current = restored.edges;
    setNodes(restored.nodes);
    setEdges(restored.edges);
    setSelectedNodeId("");
  }, [cloneGraph, setEdges, setNodes]);
  const redo = useCallback(() => {
    const next = futureRef.current.at(-1);
    if (!next) return;
    const currentGraph = cloneGraph({
      nodes: nodesRef.current,
      edges: edgesRef.current,
    });
    const nextHistory = [...historyRef.current, currentGraph];
    const nextFuture = futureRef.current.slice(0, -1);
    historyRef.current = nextHistory;
    futureRef.current = nextFuture;
    setHistory(nextHistory);
    setFuture(nextFuture);
    const restored = cloneGraph(next);
    nodesRef.current = restored.nodes;
    edgesRef.current = restored.edges;
    setNodes(restored.nodes);
    setEdges(restored.edges);
    setSelectedNodeId("");
  }, [cloneGraph, setEdges, setNodes]);
  useEffect(() => {
    if (instance && pendingViewportRef.current) {
      instance.setViewport(pendingViewportRef.current);
      pendingViewportRef.current = null;
    }
  }, [instance]);
  useEffect(() => {
    if (loadedRef.current) return;
    loadedRef.current = true;
    void api<
      Array<{
        id: string;
        nodes: Node[];
        edges: Edge[];
        viewport?: { x: number; y: number; zoom: number };
        settings?: { backgroundMode?: "dots" | "lines" } | null;
      }>
    >("/canvas")
      .then((value) => {
        const first = value?.[0];
        if (!first) return;
        setCanvasId(first.id);
        if (first.nodes?.length) {
          const loadedNodes = first.nodes.map((node) => ({
            ...node,
            data: { ...node.data },
            position: { ...node.position },
          }));
          nodesRef.current = loadedNodes;
          setNodes(loadedNodes);
        }
        if (first.edges?.length) {
          const loadedEdges = first.edges.map((edge) => ({ ...edge }));
          edgesRef.current = loadedEdges;
          setEdges(loadedEdges);
        }
        if (first.viewport) {
          const viewport = {
            x: Number(first.viewport.x ?? 0),
            y: Number(first.viewport.y ?? 0),
            zoom: Number(first.viewport.zoom ?? 1),
          };
          if (instance) instance.setViewport(viewport);
          else pendingViewportRef.current = viewport;
        }
        const settings = first.settings;
        if (settings?.backgroundMode)
          setBackgroundMode(settings.backgroundMode);
      })
      .catch(() => undefined);
  }, [instance, setEdges, setNodes]);
  const onNodeDragStart = useCallback(() => {
    dragSnapshotRef.current = cloneGraph({
      nodes: nodesRef.current,
      edges: edgesRef.current,
    });
  }, [cloneGraph]);
  const onNodeDragStop = useCallback(
    (_event: MouseEvent | TouchEvent, node: Node) => {
      const previous = dragSnapshotRef.current;
      dragSnapshotRef.current = null;
      const nextNodes = nodesRef.current.map((current) =>
        current.id === node.id
          ? { ...current, position: { ...node.position } }
          : current,
      );
      if (previous) commitGraph(nextNodes, edgesRef.current, previous);
    },
    [commitGraph],
  );
  const selectNode = useCallback(
    (nodeId: string) => {
      const nextNodes = nodesRef.current.map((node) => ({
        ...node,
        selected: node.id === nodeId,
      }));
      nodesRef.current = nextNodes;
      setNodes(nextNodes);
      setSelectedNodeId(nodeId);
    },
    [setNodes],
  );
  const clearNodeSelection = useCallback(() => {
    const nextNodes = nodesRef.current.map((node) => ({
      ...node,
      selected: false,
    }));
    nodesRef.current = nextNodes;
    setNodes(nextNodes);
    setSelectedNodeId("");
  }, [setNodes]);
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.matches("input, textarea, select")) return;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redo();
        else undo();
      } else if (
        (event.ctrlKey || event.metaKey) &&
        event.key.toLowerCase() === "y"
      ) {
        event.preventDefault();
        redo();
      } else if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        deleteSelectedNode();
      } else if (
        (event.ctrlKey || event.metaKey) &&
        event.key.toLowerCase() === "d"
      ) {
        event.preventDefault();
        duplicateSelectedNode();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [deleteSelectedNode, duplicateSelectedNode, redo, undo]);
  async function save() {
    setMessage("");
    try {
      const payload = {
        name: "Commerce Studio Infinite Canvas",
        productId: selectedProductId || undefined,
        nodes,
        edges,
        viewport: instance?.getViewport() ?? { x: 0, y: 0, zoom: 1 },
        settings: { backgroundMode },
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
      setSavedAt(new Date().toLocaleTimeString());
      setMessage("已保存");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Canvas 保存失败");
    }
  }
  const selectedNode = nodes.find((node) => node.id === selectedNodeId);
  const recentResults = tasks.filter((task) => task.assets?.length).slice(0, 4);
  return (
    <div className="infinite-workbench">
      <header className="infinite-topbar">
        <button className="canvas-brand" onClick={onExit} title="返回工作台">
          <span className="brand-mark">CS</span>
          <span>
            <strong>Commerce Studio</strong>
            <small>Infinite Canvas</small>
          </span>
        </button>
        <div className="canvas-project-name">
          <span className="eyebrow">PROJECT</span>
          <strong>产品视觉工作流</strong>
          {savedAt && <small>最后保存 {savedAt}</small>}
        </div>
        <div className="canvas-top-actions">
          {message && <span className="toolbar-message">{message}</span>}
          <button
            className="button ghost canvas-exit-button"
            type="button"
            title="退出 Infinite Canvas"
            onClick={onExit}
          >
            返回工作台
          </button>
          <button
            className={`canvas-icon-button ${showInspector ? "active" : ""}`}
            title="打开节点检查器"
            aria-label="打开节点检查器"
            onClick={() => setShowInspector((current) => !current)}
          >
            ☷
          </button>
          <button
            className="button canvas-save-button"
            onClick={() => void save()}
          >
            保存画布
          </button>
        </div>
      </header>
      <aside className="canvas-left-rail">
        <div className="canvas-tool-group">
          <button
            className={`canvas-rail-button ${tool === "select" ? "active" : ""}`}
            title="选择工具"
            aria-label="选择工具"
            onClick={() => setTool("select")}
          >
            ↖
          </button>
          <button
            className={`canvas-rail-button ${tool === "pan" ? "active" : ""}`}
            title="平移画布"
            aria-label="平移画布"
            onClick={() => setTool("pan")}
          >
            ✋
          </button>
        </div>
        <div className="canvas-rail-divider" />
        <button
          className={`canvas-rail-button ${addMenuOpen ? "active" : ""}`}
          title="添加产品节点"
          aria-label="添加产品节点"
          onClick={() => setAddMenuOpen((current) => !current)}
        >
          +
        </button>
        {addMenuOpen && (
          <div className="canvas-add-menu">
            <span>添加节点</span>
            {(
              [
                "product",
                "memory",
                "prompt",
                "generation",
                "result",
                "reference",
                "text",
                "config",
              ] as CanvasNodeKind[]
            ).map((kind) => (
              <button
                key={kind}
                type="button"
                className="canvas-add-menu-item"
                onClick={() => createNode(kind)}
              >
                <span
                  className={`canvas-node-dot ${canvasNodeMeta[kind].tone}`}
                />
                {canvasNodeMeta[kind].title}
              </button>
            ))}
          </div>
        )}
        <button
          className="canvas-rail-button"
          title="撤销"
          aria-label="撤销"
          disabled={!history.length}
          onClick={undo}
        >
          ↶
        </button>
        <button
          className="canvas-rail-button"
          title="重做"
          aria-label="重做"
          disabled={!future.length}
          onClick={redo}
        >
          ↷
        </button>
        <button
          className="canvas-rail-button"
          title="聚焦全部节点"
          aria-label="聚焦全部节点"
          onClick={() => instance?.fitView({ padding: 0.24, duration: 350 })}
        >
          ⛶
        </button>
        <button
          className={`canvas-rail-button ${backgroundMode === "dots" ? "active" : ""}`}
          title="切换画布背景"
          aria-label="切换画布背景"
          onClick={() =>
            setBackgroundMode((current) =>
              current === "dots" ? "lines" : "dots",
            )
          }
        >
          ·
        </button>
        <div className="canvas-rail-spacer" />
        <div className="canvas-zoom-readout">
          <span>∞</span>
          <small>Canvas</small>
        </div>
      </aside>
      <main
        className={`infinite-canvas-stage ${showInspector ? "with-inspector" : ""}`}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={handleNodesChange}
          onEdgesChange={handleEdgesChange}
          onConnect={onConnect}
          onInit={setInstance}
          onNodeDragStart={onNodeDragStart}
          onNodeDragStop={onNodeDragStop}
          onNodeClick={(_, node) => selectNode(node.id)}
          onPaneClick={clearNodeSelection}
          nodeTypes={nodeTypes}
          panOnDrag={tool === "pan"}
          selectionOnDrag={tool === "select"}
          fitView
          fitViewOptions={{ padding: 0.24 }}
          minZoom={0.12}
          maxZoom={2}
        >
          <Background
            color={backgroundMode === "dots" ? "#aa9fff" : "#2d3153"}
            gap={28}
            size={backgroundMode === "dots" ? 1.4 : 1}
            variant={
              backgroundMode === "dots"
                ? BackgroundVariant.Dots
                : BackgroundVariant.Lines
            }
          />
          <Controls showInteractive={false} position="bottom-left" />
          <MiniMap
            position="bottom-right"
            nodeColor={(node) => {
              const kind = String(node.data?.kind ?? node.id) as CanvasNodeKind;
              return node.data?.kind
                ? `var(--flow-${canvasNodeMeta[kind]?.tone ?? "blue"})`
                : "#6470ad";
            }}
          />
        </ReactFlow>
        <div className="canvas-floating-prompt">
          <span className="canvas-floating-icon">✦</span>
          <div>
            <strong>把产品记忆带进画布</strong>
            <small>点击节点查看配置，连接节点组织生成流程</small>
          </div>
          <button
            className="canvas-floating-action"
            title="打开图片创作"
            aria-label="打开图片创作"
            onClick={onExit}
          >
            ↗
          </button>
        </div>
      </main>
      {showInspector && (
        <aside className="canvas-inspector">
          <div className="canvas-inspector-header">
            <div>
              <span className="eyebrow">INSPECTOR</span>
              <h2>工作流配置</h2>
            </div>
            <button
              className="canvas-close-button"
              title="关闭检查器"
              aria-label="关闭检查器"
              onClick={() => setShowInspector(false)}
            >
              ×
            </button>
          </div>
          <label className="canvas-compact-field">
            <span>当前产品</span>
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
          <div className="canvas-inspector-section">
            <span className="section-label">节点</span>
            <div className="canvas-node-list">
              {nodes.map((node) => {
                const kind = String(
                  node.data?.kind ?? node.id,
                ) as CanvasNodeKind;
                const meta = canvasNodeMeta[kind] ?? canvasNodeMeta.product;
                return (
                  <button
                    key={node.id}
                    className={`canvas-node-list-item ${node.id === selectedNodeId ? "selected" : ""}`}
                    onClick={() => selectNode(node.id)}
                  >
                    <span className={`canvas-node-dot ${meta.tone}`} />
                    <span>
                      <strong>{meta.title}</strong>
                      <small>{meta.eyebrow}</small>
                    </span>
                    <span>›</span>
                  </button>
                );
              })}
            </div>
          </div>
          {selectedNode && (
            <div className="canvas-selected-node">
              <span className="section-label">选中节点</span>
              <strong>
                {
                  (
                    canvasNodeMeta[
                      String(
                        selectedNode.data?.kind ?? selectedNode.id,
                      ) as CanvasNodeKind
                    ] ?? canvasNodeMeta.product
                  ).title
                }
              </strong>
              <p>节点参数保存在 Canvas 文档中，敏感密钥由服务端配置管理。</p>
              <div className="canvas-selected-actions">
                <button
                  type="button"
                  className="canvas-inspector-action"
                  onClick={duplicateSelectedNode}
                >
                  复制节点
                </button>
                <button
                  type="button"
                  className="canvas-inspector-action danger"
                  onClick={deleteSelectedNode}
                >
                  删除节点
                </button>
                <button
                  type="button"
                  className="canvas-inspector-action"
                  onClick={() =>
                    instance?.fitView({
                      nodes: [selectedNode],
                      padding: 0.35,
                      duration: 350,
                    })
                  }
                >
                  聚焦节点
                </button>
              </div>
            </div>
          )}
          <div className="canvas-inspector-section">
            <div className="canvas-inspector-heading">
              <span className="section-label">最近结果</span>
              <span className="count-badge">{recentResults.length}</span>
            </div>
            <div className="canvas-results-list">
              {recentResults.length ? (
                recentResults.map((task) => (
                  <div className="canvas-result-row" key={task.id}>
                    <span className="canvas-result-thumb">
                      {task.assets?.[0]?.mimeType.startsWith("video/")
                        ? "▶"
                        : "✦"}
                    </span>
                    <span>
                      <strong>{task.idea}</strong>
                      <small>
                        {task.product?.name || "产品"} ·{" "}
                        {task.type === "VIDEO" ? "视频" : "图片"}
                      </small>
                    </span>
                  </div>
                ))
              ) : (
                <p className="canvas-empty-copy">
                  生成结果会在这里形成可复用的工作流素材。
                </p>
              )}
            </div>
          </div>
        </aside>
      )}
    </div>
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
  const [historyCode, setHistoryCode] = useState("");
  const [searchedTasks, setSearchedTasks] = useState<Task[] | null>(null);
  const [searchMessage, setSearchMessage] = useState("");
  const [searching, setSearching] = useState(false);
  const displayedTasks = searchedTasks ?? tasks;

  async function searchHistory(event: React.FormEvent) {
    event.preventDefault();
    const normalized = historyCode.trim();
    if (!normalized) {
      setSearchedTasks(null);
      setSearchMessage("");
      return;
    }
    if (!/^\d{7}$/.test(normalized)) {
      setSearchMessage("请输入完整的 7 位数字编号");
      return;
    }
    setSearching(true);
    setSearchMessage("");
    try {
      const result = await api<Task[]>(
        `/generation-tasks?historyCode=${encodeURIComponent(normalized)}&take=20`,
      );
      setSearchedTasks(result ?? []);
      setSearchMessage(
        result?.length ? "已定位到对应生成记录" : "没有找到对应生成记录",
      );
    } catch (error) {
      setSearchMessage(error instanceof Error ? error.message : "查询失败");
    } finally {
      setSearching(false);
    }
  }

  function clearSearch() {
    setHistoryCode("");
    setSearchedTasks(null);
    setSearchMessage("");
  }

  return (
    <div className="tasks-page">
      <PageHeader
        eyebrow="GENERATION HISTORY"
        title="生成历史"
        description="按 7 位生成编号定位图片或视频任务，查看实时状态与输出资产。"
        aside={
          <span className="page-heading-count">
            {displayedTasks.length} 条记录
          </span>
        }
      />
      <div className="two-column tasks-layout">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">HISTORY</span>
              <h3>任务列表</h3>
            </div>
            <span className="count-badge">{displayedTasks.length}</span>
          </div>
          <form className="history-search" onSubmit={searchHistory}>
            <div className="history-search-input">
              <input
                value={historyCode}
                onChange={(event) =>
                  setHistoryCode(
                    event.target.value.replace(/\D/g, "").slice(0, 7),
                  )
                }
                inputMode="numeric"
                maxLength={7}
                placeholder="输入 7 位生成编号精准查询"
                aria-label="输入 7 位生成编号"
              />
              <button className="button primary small" disabled={searching}>
                {searching ? "查询中..." : "精准查询"}
              </button>
              {searchedTasks !== null && (
                <button
                  className="button ghost small"
                  type="button"
                  onClick={clearSearch}
                >
                  清除
                </button>
              )}
            </div>
            {searchMessage && (
              <span
                className={`history-search-message ${
                  searchMessage.includes("没有") ||
                  searchMessage.includes("失败")
                    ? "error"
                    : "success"
                }`}
              >
                {searchMessage}
              </span>
            )}
          </form>
          <div className="task-list">
            {displayedTasks.length === 0 && (
              <EmptyState
                text={
                  searchedTasks !== null
                    ? "没有匹配的生成记录"
                    : "还没有生成任务"
                }
              />
            )}
            {displayedTasks.map((task) => (
              <button
                className={`task-row ${activeTask?.id === task.id ? "selected" : ""}`}
                key={task.id}
                onClick={() => onSelect(task)}
              >
                <div>
                  <strong>{task.idea}</strong>
                  <span>
                    {task.historyCode || "待分配编号"} ·{" "}
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
          <span>生成编号</span>
          <strong className="mono">
            {currentTask.historyCode || "待分配"}
          </strong>
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
  icon,
  label,
  active,
  onClick,
  badge,
}: {
  icon: string;
  label: string;
  active: boolean;
  onClick: () => void;
  badge?: string;
}) {
  return (
    <button
      className={`nav-item ${active ? "active" : ""}`}
      onClick={onClick}
      title={label}
    >
      <span className="nav-icon" aria-hidden="true">
        {icon}
      </span>
      <span className="nav-label">{label}</span>
      {badge && <span className="nav-badge">{badge}</span>}
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

function AdminLoadingState({ text }: { text: string }) {
  return (
    <div className="admin-loading" role="status" aria-live="polite">
      <span className="admin-loading-spinner" aria-hidden="true" />
      <span>{text}</span>
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
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  disabled?: boolean;
}) {
  return (
    <label>
      {label}
      <textarea
        rows={4}
        disabled={disabled}
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

function parseCommaList(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseNumberList(value: string) {
  return parseCommaList(value)
    .map((item) => Number(item))
    .filter((item) => Number.isInteger(item) && item > 0);
}

function normalizeSkillType(value: unknown): "IMAGE" | "VIDEO" | "BOTH" {
  const normalized = String(value ?? "BOTH")
    .trim()
    .toUpperCase();
  if (normalized.includes("IMAGE") && normalized.includes("VIDEO"))
    return "BOTH";
  if (
    normalized === "IMAGE" ||
    normalized === "IMG" ||
    normalized === "PICTURE"
  )
    return "IMAGE";
  if (normalized === "VIDEO" || normalized === "VID") return "VIDEO";
  return "BOTH";
}

function slugifySkillCode(value: string) {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || `skill-${Date.now()}`
  );
}

function getModelAspectRatios(
  capability: ModelCapability,
  type: "IMAGE" | "VIDEO",
) {
  const specific =
    type === "IMAGE"
      ? capability.imageAspectRatios
      : capability.videoAspectRatios;
  const values = specific?.length ? specific : capability.aspectRatios;
  return Array.isArray(values)
    ? values.filter((item): item is string => typeof item === "string")
    : [];
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
    image: "图片创作",
    video: "视频创作",
    canvas: "Infinite Canvas",
    tasks: "生成历史",
    account: "个人中心",
    admin: "系统配置",
  }[view];
}

function adminTabTitle(tab: AdminTab) {
  return {
    users: "用户管理",
    roles: "角色权限",
    teams: "部门管理",
    menus: "菜单权限",
    settings: "系统设置",
    providers: "模型供应商",
    skills: "Skill 配置",
    audit: "审计日志",
  }[tab];
}
