import { apiClient } from './client';
export const libraryApi = {
  documents: (options) => apiClient.get('/api/documents',options),
  document: (id,options) => apiClient.get(`/api/documents/${id}`,options),
  versions: (id,options) => apiClient.get(`/api/documents/${id}/versions`,options),
  jobs: (params,options) => apiClient.get('/api/index-jobs',{...options,params}),
  job: (id,options) => apiClient.get(`/api/index-jobs/${id}`,options),
  retry: id => apiClient.post(`/api/index-jobs/${id}/retry`),
  upload: file => { const body=new FormData();body.append('file',file);return apiClient.post('/api/documents/import/file/async',body); },
};
export function validateUpload(file) {
  if (!/\.(pdf|docx|txt|md|markdown)$/i.test(file.name)) return 'Unsupported file. Choose PDF, DOCX, TXT or Markdown.';
  if (!file.size) return 'Empty file. Choose a file containing readable text.';
  if (file.size>8*1024*1024) return 'File exceeds the backend limit of 8 MiB.';
  return null;
}
export const activeJob = job => ['queued','running'].includes(job?.status);
export const stageLabel = stage => ({queued:'Queued',starting:'Starting',fetching:'Fetching source',saving_source:'Saving source',parsing:'Parsing document',chunking:'Chunking',embedding:'Building search index',indexing:'Building search index',publishing:'Publishing version',completed:'Completed'})[stage] || stage || 'Not yet reported';
export const timeLabel = value => value ? new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : value+'Z').toLocaleString() : '—';
