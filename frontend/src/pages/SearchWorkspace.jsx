import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Input, Select } from 'antd';
import { Link } from 'react-router-dom';
import { searchEvidence } from '../api/search';
import { useReadyDocuments } from '../hooks/useReadyDocuments';
import { EmptyState, PageHeader, ErrorState, LoadingState } from '../components/ui';
import EvidencePanel, { EvidenceDetails } from '../components/EvidencePanel';

function ScopeNotice({ scope, documents }) {
  if (scope?.mode !== 'explicit') return null;
  const excluded = scope.excluded_documents || [];
  const message = scope.eligible_document_ids.length
    ? `Searching ${scope.eligible_document_ids.length} of ${scope.requested_document_ids.length} selected papers.`
    : `0 of ${scope.requested_document_ids.length} selected papers are searchable.`;
  return <div className="scope-notice"><Alert type={excluded.length ? 'warning' : 'info'} showIcon message={message} description={excluded.length ? <>
    <p>{excluded.length} selected {excluded.length===1?'paper was':'papers were'} excluded.</p>
    <details><summary>Excluded papers</summary><ul>{excluded.map(item=><li key={item.document_id}>
      {documents.find(d=>d.id===item.document_id)?.title || `Document #${item.document_id}`} — {item.reason==='not_found'?'not found':'not ready'}
    </li>)}</ul></details></> : null}/></div>;
}

export default function SearchWorkspace() {
  const docs = useReadyDocuments();
  const [query,setQuery] = useState(''), [documentIds,setDocumentIds] = useState([]);
  const [result,setResult] = useState(null), [error,setError] = useState(null);
  const [loading,setLoading] = useState(false), [validation,setValidation] = useState('');
  const [selected,setSelected] = useState(null);
  const request = useRef(null), input = useRef(null), scopeInput = useRef(null), trigger = useRef(null);
  useEffect(()=>()=>request.current?.abort(),[]);
  async function submit(event) {
    event.preventDefault();
    if(request.current) return;
    if(!query.trim()){setValidation('Enter a search query.');input.current?.focus();return;}
    const controller = new AbortController();request.current=controller;
    setValidation('');setLoading(true);setResult(null);setError(null);setSelected(null);
    try { const data = await searchEvidence({query,documentIds},{signal:controller.signal});
      if(!controller.signal.aborted)setResult(data);
    } catch(e){if(!controller.signal.aborted)setError(e);}
    finally {if(!controller.signal.aborted){setLoading(false);request.current=null;}}
  }
  const papers=docs.data || [], ready=papers.filter(d=>d.status==='ready');
  const scope=result?.scope || error?.scope;
  const noEligible=error?.error_code==='no_eligible_documents';
  function closeEvidence(){setSelected(null);trigger.current?.focus();}
  const changeScope=<Button onClick={()=>scopeInput.current?.focus()}>Change document scope</Button>;
  return <div className="page-stack"><PageHeader title="Search" description="Search across your research library."/>
    <form className="search-form" onSubmit={submit}>
      <div><label htmlFor="research-query">Search query</label><Input id="research-query" ref={input} value={query} onChange={e=>setQuery(e.target.value)} disabled={loading} aria-invalid={!!validation} aria-describedby={validation?'query-error':undefined}/>
      {validation && <p id="query-error" role="alert">{validation}</p>}</div>
      <div><label htmlFor="document-scope">Document scope</label><Select id="document-scope" ref={scopeInput} aria-label="Document scope" mode="multiple" allowClear showSearch optionFilterProp="label" placeholder="All ready documents" value={documentIds} onChange={setDocumentIds} disabled={loading || docs.loading || !!docs.error} loading={docs.loading}
        maxTagCount={0} maxTagPlaceholder={()=>`${documentIds.length} papers selected`} options={ready.map(d=>({value:d.id,label:d.title}))}/></div>
      <Button htmlType="submit" type="primary" loading={loading} disabled={loading || !query.trim()}>Search</Button>
    </form>
    {docs.error && <ErrorState error={docs.error} onRetry={docs.refresh}/>}
    <ScopeNotice scope={scope} documents={papers}/>
    <div className={`search-workspace ${selected?'has-evidence':''}`}><section className="search-results" aria-label="Search results" aria-busy={loading}>
      {loading ? <LoadingState label="Searching your research library..."/> : noEligible ? <Alert type="warning" showIcon message="None of the selected papers are ready for search." description={<>
        {scope?.excluded_documents?.some(d=>d.reason==='not_ready') && <p>Selected papers are still indexing or unavailable.</p>}
        {scope?.excluded_documents?.some(d=>d.reason==='not_found') && <p>One or more selected papers no longer exist.</p>}{changeScope}</>}/> : error ? <ErrorState error={error}/> : !result ? <EmptyState compact title="Search your indexed papers." description="Search returns traceable evidence, not generated answers."/> : !result.results.length ? <div className="search-empty"><h2>No evidence found for this query in the selected documents.</h2><Button onClick={()=>input.current?.focus()}>Try another query</Button>{changeScope}</div> : <>
        <h2>Top matching evidence <span className="muted">· {result.results.length} shown</span></h2>
        <p className="muted">Results are ranked by retrieval relevance and may not directly answer the query.</p>
        <ol className="evidence-results">{result.results.map((row,index)=><li key={`${row.document.id}:${row.document_version_id}:${row.chunk_id}`} className={selected===row?'selected':''}>
          <h3><Link to={`/library/${row.document.id}`}>{row.document.title || papers.find(d=>d.id===row.document.id)?.title || 'Untitled paper'}</Link></h3>
          <p className="muted">Page {row.location?.page_number ?? 'not provided'}{row.location?.section_title && ` · ${row.location.section_title}`}</p>
          <p className="result-snippet">{row.text}</p>
          <Button onClick={e=>{trigger.current=e.currentTarget;setSelected(row);}} aria-label={`View Evidence ${index+1}`} aria-pressed={selected===row}>View Evidence</Button>
          <EvidenceDetails evidence={row}/>
        </li>)}</ol></>}
    </section><EvidencePanel evidence={selected} onClose={closeEvidence}/></div>
  </div>;
}
