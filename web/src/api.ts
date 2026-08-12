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
    throw new Error(payload.error?.message ?? `请求失败（${response.status}）`);
  }
  return payload.data as T;
}

export function streamGeneration(
  taskId: string,
  onMessage: (event: MessageEvent) => void,
) {
  const source = new EventSource(
    `/events/generation/${encodeURIComponent(taskId)}`,
    {
      withCredentials: true,
    },
  );
  source.onmessage = onMessage;
  source.onerror = () => {
    source.close();
  };
  return () => source.close();
}
