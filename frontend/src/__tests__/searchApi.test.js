import { afterEach,it,expect,vi } from 'vitest';
import { searchEvidence } from '../api/search';
afterEach(()=>vi.unstubAllGlobals());
it.each([undefined,[],[1],[1,2]])('request scope %j',async documentIds=>{
 const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify({code:0,data:{results:[]}})));vi.stubGlobal('fetch',fetch);
 await searchEvidence({query:'  alpha ',documentIds});const body=JSON.parse(fetch.mock.calls[0][1].body);
 expect(body).toEqual({query:'alpha',mode:'hybrid',...(documentIds?.length?{document_ids:documentIds}:{})});
});
it.each([[200,'no_eligible_documents'],[422,'empty_document_scope']])('preserves scope envelope %s',async(status,code)=>{
 const scope={mode:'explicit',requested_document_ids:[3],eligible_document_ids:[],excluded_documents:[{document_id:3,reason:'not_ready'}]};
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({code:1,message:'None of the selected documents are currently searchable.',data:{error_type:code,scope}}),{status})));
 await expect(searchEvidence({query:'alpha',documentIds:[3]})).rejects.toMatchObject({http_status:status,business_code:1,error_code:code,scope,data:{scope},response_message:'None of the selected documents are currently searchable.'});
});
