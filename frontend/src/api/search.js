import { apiClient } from './client';

export function searchEvidence({ query, documentIds }, options = {}) {
  return apiClient.post('/api/search', {
    query: query.trim(), mode: 'hybrid',
    ...(documentIds?.length ? { document_ids: documentIds } : {}),
  }, options);
}
