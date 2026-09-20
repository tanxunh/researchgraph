import { apiClient } from './client';

export async function askGroundedQuestion({ question, documentIds }, options = {}) {
  const response = await apiClient.post('/api/qa', {
    question: question.trim(), mode: 'hybrid',
    ...(documentIds?.length ? { document_ids: documentIds } : {}),
  }, { ...options, includeResponse: true });
  return { ...response.data, response_metadata: {
    http_status: response.http_status, business_code: response.business_code, message: response.message,
  } };
}

// Convert the exact Citation, not a retrieval candidate or an array position.
export function citationEvidence(citation) {
  return {
    citationLabel: citation.citation_id,
    document: { id: citation.document_id, title: citation.document_title, version: citation.document?.version },
    document_version_id: citation.document_version_id, chunk_id: citation.chunk_id,
    location: { page_number: citation.page, section_title: citation.section },
    text: citation.snippet, isSnippet: true,
  };
}
