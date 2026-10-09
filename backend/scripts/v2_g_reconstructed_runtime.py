"""Evaluation-only frozen retrieval adapter; no production registration."""
from contextlib import contextmanager
from unittest.mock import patch

class FrozenRetrievalAdapter:
    def __init__(self, pipeline, documents):
        self.pipeline, self.documents = pipeline, documents
        self.calls, self.admissions = [], []

    def translate(self, row):
        ids = row['reranked']
        assert len(ids) == len(set(ids)) == 10
        scores = dict(zip(row['reranked20'], row['reranker_scores']))
        results = []
        for rank, sid in enumerate(ids, 1):
            source = self.pipeline.rows[sid]
            meta = source['metadata']
            doc = self.documents[meta['document_id']]
            assert doc['version_id'] == meta['document_version_id']
            results.append(dict(chunk_id=sid, text=source['document'], document=dict(doc),
                document_version_id=meta['document_version_id'],
                chunk_occurrence_id=meta['document_chunk_id'], source_type='pdf',
                source_snapshot_available=True,
                location=dict(ordinal=meta['chunk_index'], page_number=meta['page_number'],
                              section_title=meta.get('section_title') or None),
                scores=dict(reranker_score=scores[sid]), rank=rank))
        return dict(mode='hybrid', results=results, retrieval_backend='FROZEN_V2_RETRIEVAL')

    def search(self, question, *, mode='hybrid', top_k=10, rerank=True, document_ids=None):
        if mode != 'hybrid':
            raise ValueError('Only the frozen hybrid route is permitted')
        row = self.pipeline.run(dict(query_id='RUNTIME_CALL', query_type='synthetic', query=question))
        result = self.translate(row)
        self.calls.append(dict(call_id=len(self.calls)+1, actual_query=question,
            requested_scope=document_ids, requested_top_k=top_k, requested_rerank=rerank,
            effective_scope='global', effective_final_k=10, pipeline_output=row,
            returned_results=result['results']))
        return result

    def resolve(self, keys):
        output = {}
        for version_id, sid in keys:
            row = self.pipeline.rows.get(sid)
            if row is None or row['metadata']['document_version_id'] != version_id:
                continue
            meta = row['metadata']; doc = self.documents[meta['document_id']]
            output[(version_id, sid)] = dict(
                document=dict(id=doc['id'], title=doc['title'], source_uri=doc['source_uri']),
                version=dict(id=version_id, number=doc['version']), chunk_id=sid,
                chunk_occurrence_id=meta['document_chunk_id'], text=row['document'],
                location=dict(ordinal=meta['chunk_index'], page_number=meta['page_number'],
                              section_title=meta.get('section_title') or None))
        return output

def registry_class():
    from app.services.runtime.tools import ToolRegistry, ToolDefinition, SearchInput, SearchOutput
    from app.services.generation.evidence_builder import EvidenceBuilder
    class EvaluationToolRegistry(ToolRegistry):
        def __init__(self, retrieval, resolver, *, max_evidence=5):
            super().__init__(retrieval, resolver, max_evidence=max_evidence)
            builder = EvidenceBuilder(max_count=max_evidence)
            def search(data):
                raw = retrieval.search(data.query, mode=data.retrieval_mode, top_k=data.top_k,
                                       rerank=False, document_ids=data.document_scope)
                scoped = [r for r in raw['results'] if data.document_scope is None
                          or r['document']['id'] in data.document_scope]
                admitted = builder.build({**raw, 'results': scoped})
                retrieval.admissions.append(dict(call_id=len(retrieval.calls),
                    document_scope=data.document_scope, max_evidence=max_evidence,
                    max_characters=builder.max_characters,
                    global_top10=[r['chunk_id'] for r in raw['results']],
                    scope_eligible=[r['chunk_id'] for r in scoped],
                    admitted=[e.model_dump() for e in admitted], backfill=False))
                return admitted
            self.evaluation_search = ToolDefinition('search_evidence',
                'Frozen global Top10 followed by explicit scoped admission.',
                SearchInput, SearchOutput, search)
        def get(self, name):
            return self.evaluation_search if name == 'search_evidence' else super().get(name)
    return EvaluationToolRegistry

@contextmanager
def evaluation_tool_binding():
    """Serial evaluation only; restore the production factory on exit."""
    from app.services.research import workflow
    with patch.object(workflow, 'ToolRegistry', registry_class()):
        yield

class RecordingLLM:
    def __init__(self, client):
        self.client, self.calls = client, []
    async def generate(self, prompt, system_prompt=None):
        record = dict(prompt=prompt, system_prompt=system_prompt)
        self.calls.append(record)
        try:
            response = await self.client.generate(prompt, system_prompt)
            record['response'] = response
            return response
        except Exception as exc:
            record['error_type'] = getattr(exc, 'error_type', type(exc).__name__)
            raise
