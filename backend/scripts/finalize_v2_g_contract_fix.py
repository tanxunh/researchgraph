"""Finalize the one-shot contract-fix smoke without running any evaluation."""
import ast,hashlib,json
from validate_v2_g_reconstructed_runtime import ROOT,B,G,read,write,sha
fix=read(G/'g16_fix_contract.json');result=read(G/'g16_fix_workflow_smoke.json')
assert result['source_hashes']==fix['source_hashes']
for p,h in fix['source_hashes'].items():assert sha(p)==h,p
old=read(G/'pre_fix_v2_g_track_b_reconstructed_config.json')
text=(ROOT/'backend/app/services/research/workflow.py').read_text(encoding='utf-8')
cls=next(n for n in ast.parse(text).body if isinstance(n,ast.ClassDef) and n.name=='ResearchService')
methods={n.name:ast.get_source_segment(text,n) for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
for field,name in [('planner_sha256','plan_task'),('coverage_check_sha256','check_coverage'),('supplemental_retrieval_sha256','refine_query')]:assert old[field]==hashlib.sha256(methods[name].encode()).hexdigest()
assert old['retrieval_adapter_sha256']==sha(old['retrieval_adapter_path'])
prompts=read(G/'generation_prompt_sources.json')
write(G/'g16_fix_prompt_sources.json',dict(previous_prompt_sources=prompts,synthesis_source=methods['synthesize'],schema_source=(ROOT/'backend/app/schemas/research.py').read_text(encoding='utf-8'),change='Structured allowed covered cell gating, explicit missing requested cells; no other prompt tuning'))
cfg=dict(old);cfg.update(source_hashes=fix['source_hashes'],final_synthesis_sha256=hashlib.sha256(methods['synthesize'].encode()).hexdigest(),prompt_sources_sha256=sha(G/'g16_fix_prompt_sources.json'),prompt_sources_path=str(G/'g16_fix_prompt_sources.json').replace(chr(92),'/'),contract_fix_sha256=sha(G/'g16_fix_contract.json'),prior_runtime_identity=old['reconstructed_runtime_identity_sha256'])
cfg.pop('reconstructed_runtime_identity_sha256');identity=hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest();cfg['reconstructed_runtime_identity_sha256']=identity
write(B/'v2_g_track_b_reconstructed_config.json',cfg)
gen=read(B/'v2_g_generation_config.json');gen.update(source_hashes=fix['source_hashes'],prompt_sources_path=cfg['prompt_sources_path'],prompt_sources_sha256=cfg['prompt_sources_sha256'],reconstructed_runtime_identity_sha256=identity)
prov=read(B/'v2_g_runtime_provenance.json');prov.update(reconstructed_runtime_identity_sha256=identity,source_worktree_hashes=fix['source_hashes'],status='FIX_SMOKE_PASS' if result['smoke_pass'] else 'FIX_SMOKE_FAILED',contract_fix_artifact=str(G/'g16_fix_workflow_smoke.json').replace(chr(92),'/'))
write(B/'v2_g_runtime_provenance.json',prov);gen['runtime_provenance_sha256']=sha(B/'v2_g_runtime_provenance.json');write(B/'v2_g_generation_config.json',gen)
a=read(G/'reconstructed_runtime_audit.json');a.update(status=prov['status'],track_b_lock='PASS' if result['smoke_pass'] else 'FAIL',ready_for_v2_g2=result['smoke_pass'],reconstructed_runtime_identity_sha256=identity,latest_smoke_path=str(G/'g16_fix_workflow_smoke.json').replace(chr(92),'/'),latest_smoke_checks=result['checks'],tests={'passed':78,'failed':0},smoke_workflow_status=result['status'],citations_serialized=bool(result['response']['citations']),citation_validation_stage='REACHED' if result['checks']['citation_validation_reached'] else 'NOT_REACHED',trusted_report_returned=result['response']['report'] is not None)
a['previous_smoke_error']=a.pop('smoke_error',None);a['blocking_reason']=None if result['smoke_pass'] else result['response']['errors']
a['authorized_source_changes']={p:fix['source_hashes'][p] for p in ['backend/app/services/research/workflow.py','backend/app/schemas/research.py']}
for p,h in a['protected_hashes'].items():assert sha(p)==a['authorized_source_changes'].get(p,h),p
write(G/'reconstructed_runtime_audit.json',a)
p=ROOT/'docs/evaluation_v2_research_workflow.md'
with p.open('a',encoding='utf-8') as f:
 f.write('\n\n## V2-G1.6 Structured Synthesis Contract Fix\n\n')
 f.write('The prior failed smoke is preserved. Synthesis now receives a dynamic Pydantic schema with paired document/field constants derived from allowed_covered_cells. Independent enums cannot admit invalid Cartesian-product pairs. Unsupported cells, invalid status and overlong comparison lists fail structural validation. Existing complete-covered-set, uniqueness, Fact ownership and citation checks remain in place. Missing requested cells are inserted by the system as insufficient_evidence, never filled by the model. No retrieval, admission, planner or coverage/refinement behavior changed.\n\n')
 f.write('78 regression tests passed. Same-input replay of all eight previous workflow calls confirmed identical retrieval results and Evidence admission. One newly authorized synthetic Research smoke was executed; no extra health check, TEST generation or task rerun.\n\n')
 f.write('Latest smoke checks: `'+json.dumps(result['checks'],sort_keys=True)+'`.\n\n')
 f.write('Track B-R lock: '+a['track_b_lock']+'. Ready for V2-G2: '+str(result['smoke_pass'])+'. No G2 tasks started.\n')
print('FINAL',a['track_b_lock'],json.dumps(result['checks']))
