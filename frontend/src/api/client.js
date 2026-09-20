import { ApiClientError, normalizeApiError } from './errors';
export { ApiClientError, normalizeApiError } from './errors';
export const apiClient = {
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000', timeout: 120000,
  get: (path, options = {}) => request(path, { ...options, method: 'GET' }),
  post: (path, body, options = {}) => request(path, { ...options, method: 'POST', body }),
  patch: (path, body, options = {}) => request(path, { ...options, method: 'PATCH', body }),
  delete: (path, options = {}) => request(path, { ...options, method: 'DELETE' }),
};
async function request(path, options) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  if (options.signal?.aborted) controller.abort();
  const timeout = setTimeout(abort, options.timeout ?? apiClient.timeout);
  try {
    const base = new URL(apiClient.baseURL, globalThis.location?.origin || 'http://localhost');
    const url = new URL(path, base);
    Object.entries(options.params || {}).forEach(([key,value]) => {
      if (value == null || value === '') return;
      (Array.isArray(value) ? value : [value]).forEach(v => url.searchParams.append(key,String(v)));
    });
    const form = typeof FormData !== 'undefined' && options.body instanceof FormData;
    const response = await fetch(url.toString(), {
      method: options.method,
      headers: { ...(options.body != null && !form ? { 'Content-Type': 'application/json; charset=utf-8' } : {}), ...options.headers },
      body: options.body == null ? undefined : form ? options.body : JSON.stringify(options.body),
      signal: controller.signal,
    });
    let payload;
    try { payload = await response.json(); }
    catch { throw new ApiClientError(response.ok ? 'invalid_response' : response.status === 503 ? 'backend_unavailable' : 'server_error',response.status); }
    if (!response.ok || (payload?.code !== undefined && payload.code !== 0))
      throw normalizeApiError(null,{ http_status: response.status, payload });
    if (!payload || typeof payload !== 'object') throw new ApiClientError('invalid_response',response.status);
    if (options.includeResponse) return { http_status: response.status, business_code: payload.code, message: payload.message, data: payload.data };
    return typeof payload.code === 'number' ? payload.data : payload;
  } catch (error) { throw normalizeApiError(error,{ cancelled: options.signal?.aborted }); }
  finally { clearTimeout(timeout); options.signal?.removeEventListener('abort',abort); }
}
