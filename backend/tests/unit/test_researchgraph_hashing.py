from app.services.indexing.hash_service import hash_text, normalize_entity_name, stable_chunk_id


def test_content_hash_is_stable_for_trimmed_text():
    assert hash_text("  ProtoNet uses miniImageNet.\n") == hash_text("ProtoNet uses miniImageNet.")


def test_stable_chunk_id_uses_document_and_hash():
    chunk_hash = hash_text("ProtoNet uses miniImageNet.")
    assert stable_chunk_id(7, chunk_hash) == stable_chunk_id(7, chunk_hash)
    assert stable_chunk_id(8, chunk_hash) != stable_chunk_id(7, chunk_hash)


def test_entity_normalization_is_predictable():
    assert normalize_entity_name(" ProtoNet, ") == "protonet"
