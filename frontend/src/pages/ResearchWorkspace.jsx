import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Input, Select, Tag } from 'antd';
import { Link } from 'react-router-dom';
import { runResearchTask } from '../api/research';
import { citationEvidence } from '../api/qa';
import { ApiClientError } from '../api/errors';
import { useReadyDocuments } from '../hooks/useReadyDocuments';
import { EmptyState, PageHeader, LoadingState, ErrorState, StatusBadge } from '../components/ui';
import EvidencePanel from '../components/EvidencePanel';
import CitedAnswer from '../components/CitedAnswer';

const fieldLabels={research_problem:'Research problem',system_scenario:'System scenario',method:'Method',optimization_objective:'Optimization objective',optimization_variables:'Optimization variables',experimental_setting:'Experimental setting',baselines:'Baselines',main_findings:'Main findings'};
const fieldLabel=value=>fieldLabels[value] || value;
function Failure({ result }) {
  const errors=result.errors || [];
  const reason=errors.includes('fact_document_mismatch') ? 'Generated facts violated evidence ownership validation.'
    : errors.includes('citation_validation_failed') ? 'Generated report failed citation validation.'
    : errors.some(code=>['research_budget_exceeded','budget_exceeded'].includes(code)) ? 'The configured research budget was exceeded.'
    : errors.some(code=>code.startsWith('llm_')||code.startsWith('model_')||code==='invalid_model_response') ? 'The model request could not be completed.'
    : errors.some(code=>code.startsWith('tool_')) ? 'A research tool could not complete its operation.'
    : 'The research workflow could not return a validated report.';
  return <Alert type="warning" showIcon message="Research report was not returned." description={<><p>{reason}</p><p>The system rejected the report instead of returning unverified content.</p><details><summary>Execution details</summary><p>Run ID: {result.run_id || 'Not provided'}</p><ul>{errors.map((code,i)=><li key={i}><code>{code}</code></li>)}</ul></details></>}/>;
}

function Report({ result, submitted, papers, selected, onSelect }) {
  const {report,coverage}=result;
  const citations=result.citations || [];
  const title=id=>citations.find(c=>c.document_id===id)?.document_title || papers.find(d=>d.id===id)?.title || `Document #${id}`;
  const covered=coverage?.covered || [],missing=coverage?.missing || [];
  const documents=[...new Set([...submitted,...report.comparison.map(c=>c.document_id)])];
  const fields=[...new Set([...report.comparison.map(c=>c.field),...covered.map(c=>c.field),...missing.map(c=>c.field)])];
  const cited=text=><CitedAnswer answer={text} citations={citations} selectedId={selected?.citationLabel} onSelect={onSelect}/>;
  return <>
    <div className="research-result-heading"><h2>{result.status==='partial'?'Partial Research Result':'Research Complete'}</h2><StatusBadge status={result.status}/></div>
    {result.status==='partial' && <p>Only evidence-supported fields are shown.</p>}
    <p className="muted">{submitted.length} selected papers · {citations.length} citations</p>
    <h3>Summary</h3>{cited(report.summary)}
    <h3>Comparison</h3>
    <div className="comparison-scroll" role="region" aria-label="Paper comparison" tabIndex={0}><table className="research-comparison" style={{minWidth:180+documents.length*240}}>
      <caption className="sr-only">Evidence-grounded comparison by paper and field</caption>
      <thead><tr><th scope="col">Field</th>{documents.map(id=><th scope="col" key={id}><Link to={`/library/${id}`}>{title(id)}</Link></th>)}</tr></thead>
      <tbody>{fields.map(field=><tr key={field}><th scope="row">{fieldLabel(field)}</th>{documents.map(id=>{
        const cells=report.comparison.filter(c=>c.document_id===id&&c.field===field);
        return <td key={id}>{cells.length ? cells.map((cell,index)=><div key={index}>{cell.status==='insufficient_evidence' && <Tag color="warning">Insufficient evidence</Tag>}{cited(cell.value)}</div>)
          : <span className="muted">{missing.some(c=>c.document_id===id&&c.field===field)?'Missing evidence':'Not reported'}</span>}</td>;
      })}</tr>)}</tbody>
    </table></div>
    {coverage && <section aria-label="Coverage"><h3>Coverage</h3><p>{covered.length} / {covered.length+missing.length} research cells covered</p><div className="research-coverage">{[['Covered',covered],['Missing',missing]].map(([label,cells])=><div className={label==='Missing'?'muted':undefined} key={label}><h4>{label}</h4>{cells.length ? <ul>{cells.map((cell,i)=><li key={i}>{cell.document_id==null?'Unspecified paper':title(cell.document_id)} — {fieldLabel(cell.field)}</li>)}</ul> : <p>None</p>}</div>)}</div></section>}
    {!!report.limitations?.length && <section aria-label="Limitations"><h3>Limitations</h3><ul>{report.limitations.map((text,i)=><li key={i}>{cited(text)}</li>)}</ul></section>}
    <details><summary>Execution details</summary><p>Run ID: {result.run_id}</p>{result.retry_count!=null && <p>Coverage refinements: {result.retry_count}</p>}</details>
  </>;
}

export default function ResearchWorkspace() {
  const docs=useReadyDocuments();
  const [question,setQuestion]=useState(''),[documentIds,setDocumentIds]=useState([]),[submitted,setSubmitted]=useState([]);
  const [result,setResult]=useState(null),[error,setError]=useState(null),[selected,setSelected]=useState(null),[loading,setLoading]=useState(false),[validation,setValidation]=useState('');
  const request=useRef(null),trigger=useRef(null);
  useEffect(()=>()=>request.current?.abort(),[]);
  async function submit(event) {
    event.preventDefault();if(request.current)return;
    if(documentIds.length<2||documentIds.length>10){setValidation('Select between two and ten ready papers.');return;}
    if(!question.trim()){setValidation('Enter a research question.');return;}
    if(question.trim().length>4000){setValidation('Keep the research question within 4000 characters.');return;}
    const controller=new AbortController();request.current=controller;
    setLoading(true);setValidation('');setResult(null);setSelected(null);setError(null);setSubmitted([...documentIds]);
    try {
      const data=await runResearchTask({question,documentIds},{signal:controller.signal});
      if(controller.signal.aborted)return;
      if(!['completed','partial','failed'].includes(data.status))throw new ApiClientError('invalid_response');
      if(data.status!=='failed' && (!data.report?.summary?.trim() || !Array.isArray(data.report.comparison)))throw new ApiClientError('invalid_response');
      setResult(data);
    }catch(e){if(!controller.signal.aborted)setError(e);}
    finally{if(!controller.signal.aborted){setLoading(false);request.current=null;}}
  }
  return <div className="page-stack research-page"><PageHeader title="Research" description="Compare findings across your papers with traceable evidence."/>
    <form className="research-setup" onSubmit={submit}>
      <div><label htmlFor="research-documents">Documents</label><Select id="research-documents" aria-label="Documents" mode="multiple" showSearch optionFilterProp="label" allowClear maxCount={10} maxTagCount={2}
        placeholder="Select two to ten ready papers" value={documentIds} onChange={setDocumentIds} disabled={loading||docs.loading||!!docs.error} loading={docs.loading}
        options={(docs.data||[]).filter(d=>d.status==='ready').map(d=>({value:d.id,label:d.title}))}/></div>
      <div><label htmlFor="research-question">Research Question</label><Input.TextArea id="research-question" value={question} onChange={e=>setQuestion(e.target.value)} disabled={loading} rows={4} maxLength={4000}
        placeholder="Compare these papers in terms of system design, methods, optimization objectives, decision variables and major findings."/></div>
      {validation && <p role="alert">{validation}</p>}
      <Button type="primary" htmlType="submit" disabled={loading || documentIds.length<2 || !question.trim()} loading={loading}>Run Research</Button>
    </form>
    {docs.error && <ErrorState error={docs.error} onRetry={docs.refresh}/>}
    <div className={`search-workspace research-workspace ${selected?'has-evidence':''}`}><section className="search-results" aria-label="Research result" aria-busy={loading}>
      {loading ? <><LoadingState label="Executing bounded research workflow..."/><p>Research Agent is working. This may take a little longer than grounded QA.</p></>
      : error ? <ErrorState error={error}/> : result?.status==='failed' ? <Failure result={result}/>
      : result ? <Report result={result} submitted={submitted} papers={docs.data||[]} selected={selected} onSelect={(citation,element)=>{trigger.current=element;setSelected(citationEvidence(citation));}}/>
      : <EmptyState compact title="Select papers and run a cross-document research task." description="Select at least two ready papers and define your research question."/>}
    </section><EvidencePanel evidence={selected} onClose={()=>{setSelected(null);trigger.current?.focus();}}/></div>
  </div>;
}
