const messages = {
  empty_document_scope: 'Select at least one paper or choose All ready documents.',
  no_eligible_documents: 'None of the selected papers are ready for search.',
  unsupported_file: 'This file type is not supported.',
  job_failed: 'Indexing failed. Inspect the job stage before retrying.',
  insufficient_evidence: 'Not enough evidence was found in the selected documents.',
  citation_validation_failed: 'The response was rejected because its evidence references could not be validated.',
  fact_document_mismatch: 'The report was rejected because a fact used evidence from another document.',
  document_not_ready: 'This paper is still being indexed. Wait until it is ready.',
  graph_unavailable: 'Graph retrieval is unavailable. Use Hybrid search.',
  worker_interrupted: 'Indexing was interrupted. Inspect the job before retrying.',
  process_interrupted: 'Indexing was interrupted. Inspect the job before retrying.',
  network_error: 'Cannot reach the backend. Check your connection and try again.',
  backend_unavailable: 'The backend is unavailable. Please try again later.',
  timeout: 'The request timed out. Its server-side operation may still be running.',
  validation_error: 'Please check the request fields.',
  server_error: 'The server could not complete this request.',
  request_failed: 'The request could not be completed.',
  invalid_response: 'The backend returned an unexpected response.',
  cancelled: 'Request cancelled.',
};
const safeKeys = new Set(['code','status','error_type','error_code','errors','run_id','job_id',
  'document_id','citation_validation','valid','used_citation_ids','invalid_citation_ids',
  'missing_citation','warnings','detail','type','loc','scope','mode',
  'requested_document_ids','eligible_document_ids','excluded_documents','reason',
  'coverage','covered','missing','field','retry_count']);
function safeData(value, depth = 0) {
  if (depth > 5) return null;
  if (Array.isArray(value)) return value.slice(0,100).map(v => safeData(v,depth+1));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value)
    .filter(([key]) => safeKeys.has(key)).map(([key,v]) => [key,safeData(v,depth+1)]));
  if (typeof value === 'string') return /^[a-zA-Z0-9_.:\[\]-]{1,200}$/.test(value) ? value : '[redacted]';
  return typeof value === 'number' || typeof value === 'boolean' || value === null ? value : null;
}
export class ApiClientError extends Error {
  constructor(error_code, http_status = null, data = null) {
    super(messages[error_code] || messages.request_failed);
    this.name = 'ApiClientError';
    this.http_status = http_status;
    this.status = http_status;
    this.error_code = error_code;
    this.details = safeData(data);
    this.raw_safe_data = this.details;
  }
}
export function normalizeApiError(error, { http_status = null, payload, cancelled = false } = {}) {
  if (error instanceof ApiClientError) return error;
  if (payload !== undefined) {
    const data = payload?.data ?? payload;
    const detail = typeof payload?.detail === 'object' ? payload.detail : null;
    const supplied = data?.error_type || data?.error_code || data?.errors?.[0]
      || detail?.error_type || detail?.error_code
      || (typeof data?.error === 'string' ? data.error : null)
      || (messages[data?.status] ? data.status : null)
      || (typeof payload?.code === 'string' ? payload.code : null);
    const code = typeof supplied === 'string' && /^[a-z][a-z0-9_]{0,99}$/.test(supplied) ? supplied
      : http_status === 503 ? 'backend_unavailable' : http_status >= 500 ? 'server_error'
      : http_status === 422 ? 'validation_error' : 'request_failed';
    const normalized = new ApiClientError(code,http_status,{ ...data, ...(detail ? { detail } : {}) });
    normalized.business_code = payload?.code;
    normalized.data = normalized.details;
    normalized.scope = normalized.details?.scope;
    // Preserve known public scope messages, never arbitrary backend exception text.
    const publicMessages = ['None of the selected documents are currently searchable.',
      'Select at least one document or omit document_ids for global search.'];
    normalized.response_message = publicMessages.includes(payload?.message) ? payload.message : normalized.message;
    return normalized;
  }
  return new ApiClientError(error?.name === 'AbortError' ? (cancelled ? 'cancelled' : 'timeout') : 'network_error');
}
