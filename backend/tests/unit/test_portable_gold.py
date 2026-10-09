from app.services.evaluation.portable_gold import normalize, matches, coverage, recalled_units

def anchor():
    return dict(anchor_id="q:g", document_id=1, document_version_id=7, page=2, section=None, anchor_text="A"*100, document_char_start=100, document_char_end=200, source_text_hash="h")
def chunk():
    return dict(document_id=1, document_version_id=7, page=2, text="A"*100, document_char_start=150, document_char_end=250, source_text_hash="h")
def test_half_span_and_identity():
    a,c=anchor(),chunk(); assert matches(a,c)
    c["document_char_start"]=151; assert not matches(a,c)
    c["document_char_start"]=0; c["document_char_end"]=300; assert coverage(a,c)==1
    c["document_version_id"]=8; assert not matches(a,c)
    c["document_version_id"]=7; c["source_text_hash"]="other"; assert not matches(a,c)
def test_normalization_preserves_identifiers():
    assert normalize(" AoI\r\n energy ")=="AoI energy"
    assert normalize("NOMA")!="noma"
    assert normalize("off-\nloading")=="off- loading"
def test_text_location_guard():
    a,c=anchor(),chunk(); a["document_char_start"]=a["document_char_end"]=None
    assert matches(a,c)
    c["page"]=3; assert not matches(a,c)
    c["page"]=2; a["ambiguous_text_location"]=True; assert not matches(a,c)
def test_multiple_matches_count_once():
    assert recalled_units([anchor()],{"q:g":["x","y"]},["x","y"])==1
    assert recalled_units([anchor()],{"q:g":["x","y"]},["z"])==0
