"""Freeze G1.6 contract before smoke, finalize locks from recorded evidence."""
import ast,hashlib,json,subprocess
from validate_v2_g_reconstructed_runtime import ROOT,B,G,read,write,sha

def canonical(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
audit=read(G/'reconstructed_runtime_audit.json')
old=read(G/'g15_original_v2_g_runtime_provenance.json')
source={p:sha(p) for p in read(B/'v2_g_track_b_agent_config.json')['source_hashes']}
source['backend/scripts/v2_g_reconstructed_runtime.py']=sha('backend/scripts/v2_g_reconstructed_runtime.py')
source['backend/scripts/validate_v2_g_reconstructed_runtime.py']=sha('backend/scripts/validate_v2_g_reconstructed_runtime.py')
code=(ROOT/'backend/app/services/research/workflow.py').read_text(encoding='utf-8')
cls=next(n for n in ast.parse(code).body if isinstance(n,ast.ClassDef) and n.name=='ResearchService')
method_hashes={n.name:hashlib.sha256(ast.get_source_segment(code,n).encode()).hexdigest() for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
contract=dict(runtime_type='RECONSTRUCTED_EVALUATION_RUNTIME',agent_type='CURRENT_RESEARCHSERVICE_LANGGRAPH_SOURCE',
 track='TRACK_B_R',label='RECONSTRUCTED_RESEARCH_AGENT',retrieval_backend='FROZEN_V2_RETRIEVAL',
 retrieval_manifest_sha256=sha(B/'final_retrieval_manifest.json'),generation_provider='DeepSeek',generation_model_alias='deepseek-chat',
 planner_sha256=method_hashes['plan_task'],coverage_check_sha256=method_hashes['check_coverage'],
 supplemental_retrieval_sha256=method_hashes['refine_query'],final_synthesis_sha256=method_hashes['synthesize'],
 retrieval_adapter_path='backend/scripts/v2_g_reconstructed_runtime.py',retrieval_adapter_sha256=source['backend/scripts/v2_g_reconstructed_runtime.py'],
 runtime_package_snapshot_sha256=sha(G/'reconstructed_package_snapshot.json'),source_hashes=source,
 DEV_SELECTED=False,TEST_TUNED=False,source_commit=old['source_commit'],source_tree_identity=canonical(source),
 request_contract=read(B/'v2_g_track_b_agent_config.json')['task_request_rule'],
 budgets=read(B/'v2_g_track_b_agent_config.json')['source_default_budgets'],
 maximum_subqueries=dict(standalone_setting='SOURCE_UNBOUNDED',derived_maximum=16,reason='max8 subtasks, initial plus max1 refinement round; discovery at most1 additional call'),
 maximum_supplemental_calls=8,maximum_workflow_steps=11,langgraph_recursion_limit=20,
 scope_admission='HUMAN_APPROVED: global Top10 untouched; separate scope filter then existing max5/12000-char EvidenceBuilder. No backfill. Legacy rerank=False does not disable frozen reranker.',
 adapter_substitution='Evaluation-only serial patch of workflow.ToolRegistry factory; graph/planner/coverage/refinement/synthesis source unchanged. Resolve tool unchanged with immutable snapshot resolver.',
 generation_contract=dict(provider='https://api.deepseek.com/v1',model='deepseek-chat',temperature=.1,revision='MODEL_REVISION_NOT_PINNABLE',top_p='OMITTED_PROVIDER_DEFAULT',max_tokens='OMITTED_PROVIDER_DEFAULT'),
 prompt_sources_sha256=sha(G/'generation_prompt_sources.json'),
 smoke_request=dict(question='Describe the methods and optimization objectives of maritime UAV computation offloading in documents 2 and 7.',document_ids=[2,7]),
 benchmark_answers_allowed=False)
identity=canonical(contract);contract['reconstructed_runtime_identity_sha256']=identity
write(B/'v2_g_track_b_reconstructed_config.json',contract)
prov=dict(schema_version='v2-g-runtime-provenance.v2',source_commit=old['source_commit'],
 source_worktree_hashes=source,model_revision='MODEL_REVISION_NOT_PINNABLE',
 runtime_package_snapshot_path=str(G/'reconstructed_package_snapshot.json').replace(chr(92),'/'),
 runtime_package_snapshot_sha256=sha(G/'reconstructed_package_snapshot.json'),
 generation_call_path='ResearchService -> ModelGateway -> LLMClient -> HTTPX -> DeepSeek API',
 historical_reproducibility_claimed=False)
prov.update(historical_runtime_recoverable=False,historical_agent_datasource_compatible=False,
 evaluation_runtime_type='RECONSTRUCTED_EVALUATION_RUNTIME',runtime_type='RECONSTRUCTED_EVALUATION_RUNTIME',
 reconstruction_reason='HISTORICAL_DATASOURCE_NOT_BENCHMARK_COMPATIBLE',retrieval_backend='FROZEN_V2_RETRIEVAL',
 historical_provenance_archive=str(G/'g15_original_v2_g_runtime_provenance.json').replace('\\','/'),
 historical_provenance_archive_sha256=sha(G/'g15_original_v2_g_runtime_provenance.json'),
 historical_datasource=dict(documents=3,chunks=298,stable_chunk_overlap=0),
 reconstructed_datasource=dict(documents=30,chunks=3837,compatibility='FULL_MATCH'),
 reconstructed_contract_path=str(B/'v2_g_track_b_reconstructed_config.json').replace('\\','/'),
 reconstructed_runtime_identity_sha256=identity,status=audit['status'])
# Historical fields remain explicit historical observations in the archived original.
prov['historical_observations']=old
for k in ['retrieval_relation_to_V2','retrieval_routes','smoke_test','options_only','status_scope']:
 prov.pop(k,None)
write(B/'v2_g_runtime_provenance.json',prov)
gen=read(G/'g15_original_v2_g_generation_config.json')
gen.update(status='FROZEN_RECONSTRUCTED_CONTRACT',identity_basis='Explicitly approved reconstructed evaluation runtime',
 runtime_type='RECONSTRUCTED_EVALUATION_RUNTIME',runtime_prerequisites=['G1.6 recorded live smoke locks must pass'],
 executable=audit['generation_lock']=='PASS',runtime_provenance_sha256=sha(B/'v2_g_runtime_provenance.json'),
 reconstructed_runtime_identity_sha256=identity,source_hashes=source,LLM_API_KEY_present=audit.get('LLM_API_KEY_present',False))
gen['sdk']=dict(library='httpx',version='0.28.1',source='pinned reconstructed image package snapshot')
write(B/'v2_g_generation_config.json',gen)
audit['reconstructed_runtime_identity_sha256']=identity
write(G/'reconstructed_runtime_audit.json',audit)
print('RECONSTRUCTED_CONTRACT_FROZEN',identity)
