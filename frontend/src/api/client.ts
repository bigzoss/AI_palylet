export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export const BASE = "/api/v1";
export async function api<T = any>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(BASE + path, {
    ...init,
    headers: {
      ...(init.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...init.headers,
    },
  });
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/")) {
      window.dispatchEvent(new Event("auth-expired"));
    }
    const value = await response.json().catch(() => ({}));
    throw new ApiError(
      response.status,
      value.message || `请求失败（${response.status}）`,
    );
  }
  return response.json();
}
export const post = <T = any>(path: string, value: unknown = {}) =>
  api<T>(path, { method: "POST", body: JSON.stringify(value) });
export const patch = (path: string, value: unknown) =>
  api(path, { method: "PATCH", body: JSON.stringify(value) });
export const mediaUrl = (id: string) =>
  `${BASE}/media/${encodeURIComponent(id)}/content`;
export const taskBody = (extra = {}) => ({
  idempotency_key: crypto.randomUUID(),
  ...extra,
});
