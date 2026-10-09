from types import SimpleNamespace
import pytest
from app.services.evaluation.ann_reproducibility import replay_checkpoint,persist_experimental_graph

def segment():
    return SimpleNamespace(_curr_batch=SimpleNamespace(_ids_to_records={'b':{'log_offset':11,'record':{'id':'b'}}}),_id_to_seq_id={'a':10},_id_to_label={'a':1},_max_seq_id=11,_batch_size=100)

def test_pending_tail_is_not_claimed_persisted():
    assert replay_checkpoint(segment())==10

def test_pending_update_rejected():
    s=segment();s._id_to_label['b']=2
    with pytest.raises(ValueError):replay_checkpoint(s)

def test_persist_uses_graph_checkpoint_and_restores_runtime(tmp_path):
    s=segment();seen=[];s._persist=lambda:seen.append(s._max_seq_id)
    assert persist_experimental_graph(s,tmp_path/'copy',tmp_path)==10
    assert seen==[10] and s._max_seq_id==11

def test_live_path_cannot_be_checkpointed(tmp_path):
    with pytest.raises(ValueError):persist_experimental_graph(segment(),tmp_path,tmp_path/'allowed')

def test_failed_persist_restores_memory_sequence(tmp_path):
    s=segment()
    def fail():raise RuntimeError('disk')
    s._persist=fail
    with pytest.raises(RuntimeError):persist_experimental_graph(s,tmp_path/'copy',tmp_path)
    assert s._max_seq_id==11
