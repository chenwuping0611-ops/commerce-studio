export interface ApiEnvelope<T> {
  data: T;
  meta?: Record<string, unknown>;
}

export async function api<T>(
  path: string,
  init: RequestInit & { bodyJson?: unknown } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  if (init.bodyJson !== undefined) {
    headers.set("content-type", "application/json");
    init.body = JSON.stringify(init.bodyJson);
  }
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  const payload = (await response.json().catch(() => ({}))) as {
    data?: T;
    error?: { message?: string; code?: string };
  };
  if (!response.ok) {
    throwApiError(payload.error, response.status);
  }
  return payload.data as T;
}

export async function upload<T>(path: string, formData: FormData): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    method: "POST",
    body: formData,
    credentials: "include",
  });
  const payload = (await response.json().catch(() => ({}))) as {
    data?: T;
    error?: { message?: string };
  };
  if (!response.ok) {
    throwApiError(payload.error, response.status);
  }
  return payload.data as T;
}

function throwApiError(
  error: { message?: string; code?: string } | undefined,
  status: number,
): never {
  const message = error?.message ?? `请求失败（${status}）`;
  const code = error?.code;
  throw new Error(
    code && !message.includes(code) ? `${message} [${code}]` : message,
  );
}

export function streamGeneration(
  taskId: string,
  onMessage: (event: MessageEvent) => void,
) {
  const eventTypes = [
    "generation.queued",
    "generation.cancel_requested",
    "generation.cancelled",
    "generation.provider_submitted",
    "generation.progress",
    "generation.retry_waiting",
    "generation.succeeded",
    "generation.failed",
    "heartbeat",
  ];
  let closed = false;
  let reconnectTimer: number | undefined;
  let source: EventSource | undefined;

  const connect = () => {
    if (closed) return;
    source = new EventSource(
      `/events/generation/${encodeURIComponent(taskId)}`,
      {
        withCredentials: true,
      },
    );
    const handleEvent = (event: Event) => {
      onMessage(event as MessageEvent);
    };
    for (const eventType of eventTypes) {
      source.addEventListener(eventType, handleEvent);
    }
    source.onmessage = handleEvent;
    source.onerror = () => {
      source?.close();
      if (!closed && reconnectTimer === undefined) {
        reconnectTimer = window.setTimeout(() => {
          reconnectTimer = undefined;
          connect();
        }, 3000);
      }
    };
  };

  connect();
  return () => {
    closed = true;
    if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
    source?.close();
  };
}
