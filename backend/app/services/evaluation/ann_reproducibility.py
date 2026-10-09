"""Evaluation-only Chroma 0.5.23 checkpoint guard; never call on a live service."""
from contextlib import contextmanager
from pathlib import Path


def replay_checkpoint(segment):
    """Persisted HNSW progress must exclude the pending brute-force tail."""
    records=list(segment._curr_batch._ids_to_records.values())
    mapped=segment._id_to_seq_id
    if not mapped:raise ValueError('empty_hnsw_graph')
    checkpoint=max(mapped.values())
    for record in records:
        if record['record']['id'] in segment._id_to_label:
            raise ValueError('pending_update_or_delete_requires_separate_handling')
        if record['log_offset']<=checkpoint:
            raise ValueError('pending_record_not_after_graph_checkpoint')
    if len(records)>=segment._batch_size:raise ValueError('tail_would_rebuild_graph')
    if checkpoint>segment._max_seq_id:raise ValueError('checkpoint_ahead_of_log')
    return checkpoint


def persist_experimental_graph(segment, snapshot_path, allowed_root):
    path=Path(snapshot_path).resolve();root=Path(allowed_root).resolve()
    if path==root or root not in path.parents:raise ValueError('not_an_isolated_snapshot')
    checkpoint=replay_checkpoint(segment)
    previous=segment._max_seq_id
    try:
        segment._max_seq_id=checkpoint
        segment._persist()
    finally:
        segment._max_seq_id=previous
    return checkpoint
