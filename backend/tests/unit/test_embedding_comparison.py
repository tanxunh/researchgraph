import numpy as np
import pytest
from app.services.evaluation.embedding_comparison import CONFIGS,validate_vectors,validate_payload,ann_diagnostic

def test_contracts_are_model_specific_and_isolated():
    q="Compare NOMA and FDMA."
    assert CONFIGS["en"].text(q,True)=="Represent this sentence for searching relevant passages: "+q
    assert CONFIGS["m3"].text(q,True)==q
    assert CONFIGS["zh"].text(q,True).startswith("为这个句子")
    assert all(c.text(q,False)==q for c in CONFIGS.values())
    assert len({str(c.identity("corpus",{})) for c in CONFIGS.values()})==3

def test_vector_identity_rejects_extra_duplicate_and_bad_vectors():
    validate_vectors(["a","b"],np.eye(2),["b","a"],2)
    for ids,x in [(["a","a"],np.eye(2)),(["a","c"],np.eye(2)),(["a","b"],np.zeros((2,2))),(["a","b"],[[1,0],[float("nan"),0]])]:
        with pytest.raises(ValueError):validate_vectors(ids,x,["a","b"],2)

def test_metadata_version_and_text_are_authoritative():
    expected={"c":{"metadata":{"document_id":1,"document_version_id":2},"document":"text"}}
    validate_payload(["c"],[expected["c"]["metadata"]],["text"],expected)
    with pytest.raises(ValueError):validate_payload(["c"],[{"document_id":1,"document_version_id":3}],["text"],expected)
    with pytest.raises(ValueError):validate_payload(["c"],[expected["c"]["metadata"]],["changed"],expected)

def test_ann_gate_catches_gold_gap_even_with_high_overlap():
    exact=[str(i) for i in range(100)]
    ann=exact[:49]+[exact[50],exact[49]]+exact[51:]
    result=ann_diagnostic([{"ids":ann,"exact":exact,"gold":["49"]}])
    assert result["Top50"]==.98 and result["ann_confound"]
    same=ann_diagnostic([{"ids":exact,"exact":exact,"gold":["49"]}])
    assert not same["ann_confound"]

