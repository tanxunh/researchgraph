import { afterEach,it,expect,vi } from 'vitest';
import { runResearchTask } from '../api/research';
afterEach(()=>vi.unstubAllGlobals());
it.each(['completed','partial'])('preserves %s structured response',async status=>{
 const data={run_id:'run-1',status,report:{summary:'Summary',comparison:[],limitations:[]},coverage:{covered:[],missing:[]},citations:[],retry_count:1,errors:[]};
 const fetch=vi.fn().mockResolvedValue(new Response(JSON.stringify({code:0,message:'success',data})));vi.stubGlobal('fetch',fetch);
 expect(await runResearchTask({question:'  Compare  ',documentIds:[27,28]})).toEqual({...data,response_metadata:{http_status:200,business_code:0,message:'success'}});
 expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({question:'Compare',document_ids:[27,28]});
});
it('HTTP 200 failed preserves diagnostics/coverage and suppresses unvalidated report',async()=>{
 const coverage={covered:[{document_id:27,field:'method'}],missing:[{document_id:28,field:'method'}]};
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify({code:1,data:{status:'failed',run_id:'run-2',report:{summary:'UNTRUSTED'},citations:[{citation_id:'C1'}],coverage,retry_count:1,errors:['fact_document_mismatch']}}))));
 expect(await runResearchTask({question:'Compare',documentIds:[27,28]})).toMatchObject({status:'failed',run_id:'run-2',report:null,citations:[],coverage,retry_count:1,errors:['fact_document_mismatch'],response_metadata:{http_status:200,business_code:1}});
});
it('transport failure stays an error and does not retry',async()=>{const fetch=vi.fn().mockRejectedValue(new TypeError('offline'));vi.stubGlobal('fetch',fetch);await expect(runResearchTask({question:'Compare',documentIds:[1,2]})).rejects.toMatchObject({error_code:'network_error'});expect(fetch).toHaveBeenCalledTimes(1);});
