import { afterEach,it,expect,vi } from 'vitest';
import { askGroundedQuestion } from '../api/qa';
afterEach(()=>vi.unstubAllGlobals());
it.each([undefined,[],[1],[1,2]])('QA scope %j preserves response data',async documentIds=>{
 const data={status:'answered',answer:'Answer [C1]',citations:[{citation_id:'C1'}],citation_validation:{valid:true},evidence_count:1};
 const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify({code:0,message:'success',data})));vi.stubGlobal('fetch',fetch);
 const result=await askGroundedQuestion({question:'  question  ',documentIds});
 expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({question:'question',mode:'hybrid',...(documentIds?.length?{document_ids:documentIds}:{})});
 expect(result).toMatchObject({...data,response_metadata:{http_status:200,business_code:0,message:'success'}});
});
it('HTTP 200 citation rejection remains a business error',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({code:1,message:'private stack',data:{error_type:'citation_validation_failed',citation_validation:{valid:false,invalid_citation_ids:['C999']},answer:'untrusted'}}))));
 await expect(askGroundedQuestion({question:'question'})).rejects.toMatchObject({http_status:200,business_code:1,error_code:'citation_validation_failed',data:{citation_validation:{valid:false,invalid_citation_ids:['C999']}}});
});
