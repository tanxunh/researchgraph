import { apiClient } from './client';

export async function runResearchTask({ question, documentIds }, options = {}) {
  try {
    const response = await apiClient.post('/api/research/tasks', {
      question: question.trim(), document_ids: documentIds,
    }, { timeout: 600000, ...options, includeResponse: true });
    return { ...response.data, response_metadata: {
      http_status: response.http_status, business_code: response.business_code, message: response.message,
    } };
  } catch (error) {
    if(error.business_code===1 && error.data?.status==='failed') {
      // Business rejection is a product result, never a trusted report.
      return { ...error.data, report: null, citations: [], response_metadata: {
        http_status: error.http_status, business_code: error.business_code, message: error.message,
      } };
    }
    throw error;
  }
}
