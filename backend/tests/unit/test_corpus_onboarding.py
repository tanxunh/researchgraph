from copy import deepcopy
import pytest
from scripts.onboard_real_corpus import assign_ids, validate_exports
from app.schemas.real_benchmark import ResearchQuery


def test_ids_deterministic_and_stable_on_addition():
    rows = [{'source_sha256': 'a'}, {'source_sha256': 'b'}, {'source_sha256': 'a'}]
    assign_ids(rows, [])
    assert [r['benchmark_document_id'] for r in rows] == ['P001', 'P002', 'P001']
    added = [{'source_sha256': 'c'}, {'source_sha256': 'b'}]
    assign_ids(added, rows)
    assert [r['benchmark_document_id'] for r in added] == ['P003', 'P002']


def exports():
    docs = [dict(benchmark_document_id='P001', document_id=1, document_version_id=2,
                 page_count=4, chunk_count=1, index_status='ready')]
    catalog = [dict(benchmark_document_id='P001', document_id=1, document_version_id=2,
                    chunk_id='stable', ordinal=0, page=1, section=None, text_preview='evidence preview')]
    return docs, catalog


def test_manifest_catalog_validation():
    docs, catalog = exports()
    validate_exports(docs, catalog)
    with pytest.raises(ValueError):
        validate_exports(docs, catalog*2)
    with pytest.raises(ValueError):
        validate_exports(docs, [])


@pytest.mark.parametrize('key,value', [('document_version_id', 99), ('page', 8), ('text_preview', 'x'*241)])
def test_catalog_rejects_bad_identity_location_and_preview(key,value):
    docs, catalog = exports()
    catalog[0][key] = value
    with pytest.raises(ValueError):
        validate_exports(docs, catalog)


def test_empty_gold_template_remains_pending():
    query = ResearchQuery(query_id='EXAMPLE_ONLY', question='Human question goes here', query_type='multi_hop',
                          language='en', gold_document_ids=[], gold_evidence=[], annotation_status='pending',
                          annotator='', annotation_notes='')
    assert query.gold_evidence == [] and query.annotation_status == 'pending'
