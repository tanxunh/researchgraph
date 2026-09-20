import { expect, it, vi } from 'vitest';
import { apiClient } from '../api/client';
it.each(['insufficient_evidence','citation_validation_failed','fact_document_mismatch','document_not_ready','graph_unavailable','worker_interrupted'])('preserves %s and safe details',async code=>{
  global.fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify({code:1,message:'private backend message',data:{status:'failed',errors:[code],run_id:'run-123',api_key:'SECRET',payload:'private source',citation_validation:{valid:false,invalid_citation_ids:['C9']}}})));
  let caught;try{await apiClient.post('/api/research/tasks',{});}catch(e){caught=e;}
  expect(caught).toMatchObject({error_code:code,http_status:200,details:{errors:[code],run_id:'run-123',citation_validation:{invalid_citation_ids:['C9']}}});
  expect(JSON.stringify(caught)).not.toContain('SECRET');expect(JSON.stringify(caught)).not.toContain('private');
});
it('preserves safe FastAPI validation details',async()=>{
  global.fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify({detail:[{loc:['body','question'],type:'string_too_short',input:'secret input',msg:'private message'}]}),{status:422}));
  await expect(apiClient.post('/api/qa',{})).rejects.toMatchObject({http_status:422,error_code:'validation_error',details:{detail:[{loc:['body','question'],type:'string_too_short'}]}});
});
it('normalizes non-JSON server errors',async()=>{
  global.fetch=vi.fn().mockResolvedValue(new Response('<html>private stack</html>',{status:500}));
  await expect(apiClient.get('/health')).rejects.toMatchObject({http_status:500,error_code:'server_error'});
});
