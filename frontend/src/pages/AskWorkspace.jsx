import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Input, Select } from 'antd';
import { askGroundedQuestion, citationEvidence } from '../api/qa';
import { ApiClientError } from '../api/errors';
import { useReadyDocuments } from '../hooks/useReadyDocuments';
import { EmptyState, ErrorState, LoadingState, PageHeader } from '../components/ui';
import EvidencePanel from '../components/EvidencePanel';
import CitedAnswer from '../components/CitedAnswer';

const modelErrors = new Set(['llm_provider_error','llm_timeout','llm_network_error','llm_configuration_error','invalid_model_response']);
function QAError({ error }) {
  let title,description;
  if(error.error_code==='citation_validation_failed') {
    title='Answer not returned';
    description='The generated answer failed citation validation, so the system rejected it instead of returning an unverified response.';
  } else if(modelErrors.has(error.error_code)) {
    title='The answer could not be generated.';
    description='Your documents and index were not affected. You can submit the question again manually.';
  } else return <ErrorState error={error}/>;
  return <Alert type={error.error_code==='citation_validation_failed'?'warning':'error'} showIcon message={title} description={<><p>{description}</p><details><summary>Advanced details</summary><code>{error.error_code}{error.http_status && ` / HTTP ${error.http_status}`}</code></details></>}/>;
}

export default function AskWorkspace() {
  const docs=useReadyDocuments();
  const [question,setQuestion]=useState(''),[documentIds,setDocumentIds]=useState([]);
  const [result,setResult]=useState(null),[error,setError]=useState(null),[selected,setSelected]=useState(null);
  const [loading,setLoading]=useState(false),[validation,setValidation]=useState(''),[submittedScope,setSubmittedScope]=useState('');
  const request=useRef(null),input=useRef(null),scopeInput=useRef(null),trigger=useRef(null);
  useEffect(()=>()=>request.current?.abort(),[]);
  async function submit(event) {
    event.preventDefault();if(request.current)return;
    if(!question.trim()){setValidation('Enter a question.');input.current?.focus();return;}
    const controller=new AbortController();request.current=controller;
    setLoading(true);setValidation('');setResult(null);setSelected(null);setError(null);
    setSubmittedScope(documentIds.length?`${documentIds.length} selected papers`:'All ready papers');
    try {
      const data=await askGroundedQuestion({question,documentIds},{signal:controller.signal});
      if(controller.signal.aborted)return;
      if(!['answered','insufficient_evidence'].includes(data.status))throw new ApiClientError('invalid_response');
      if(data.status==='answered' && (data.citation_validation?.valid!==true || !data.answer?.trim() || !Array.isArray(data.citations) || !data.citations.length))throw new ApiClientError('invalid_response');
      setResult(data);
    } catch(e){if(!controller.signal.aborted)setError(e);}
    finally{if(!controller.signal.aborted){setLoading(false);request.current=null;}}
  }
  function closeEvidence(){setSelected(null);trigger.current?.focus();}
  return <div className="page-stack"><PageHeader title="Ask" description="Ask evidence-grounded questions across your research papers."/>
    <form className="search-form ask-form" onSubmit={submit}>
      <div><label htmlFor="qa-question">Question</label><Input.TextArea id="qa-question" ref={input} rows={4} value={question} disabled={loading} aria-invalid={!!validation}
        aria-describedby={validation?'question-error':undefined} onChange={e=>setQuestion(e.target.value)}
        onKeyDown={e=>{if(e.key==='Enter'&&(e.ctrlKey||e.metaKey))submit(e);}}/>
        {validation && <p role="alert" id="question-error">{validation}</p>}</div>
      <div><label htmlFor="qa-scope">Document scope</label><Select id="qa-scope" ref={scopeInput} aria-label="Document scope" mode="multiple" allowClear showSearch optionFilterProp="label"
        placeholder="All ready documents" value={documentIds} onChange={setDocumentIds} disabled={loading||docs.loading||!!docs.error} loading={docs.loading}
        maxTagCount={0} maxTagPlaceholder={()=>`${documentIds.length} papers selected`} options={(docs.data||[]).filter(d=>d.status==='ready').map(d=>({value:d.id,label:d.title}))}/></div>
      <Button htmlType="submit" type="primary" loading={loading} disabled={loading || !question.trim()}>Ask</Button>
    </form>
    {docs.error && <ErrorState error={docs.error} onRetry={docs.refresh}/>}
    <div className={`search-workspace ask-workspace ${selected?'has-evidence':''}`}><section className="search-results" aria-label="Answer workspace" aria-busy={loading}>
      {loading ? <LoadingState label="Generating grounded answer..."/> : error ? <QAError error={error}/> : result?.status==='insufficient_evidence' ?
        <Alert type="warning" showIcon message="Insufficient evidence" description={<><p>Not enough evidence was found in the selected papers to answer this question reliably.</p><Button onClick={()=>scopeInput.current?.focus()}>Change document scope</Button><Button onClick={()=>input.current?.focus()}>Edit the question</Button></>}/> : result?.status==='answered' ? <>
          <p className="muted">Scope: {submittedScope}</p><h2>Answer</h2>
          <CitedAnswer answer={result.answer} citations={result.citations} selectedId={selected?.citationLabel} onSelect={(citation,element)=>{trigger.current=element;setSelected(citationEvidence(citation));}}/>
          <details><summary>Answer details</summary><p>{result.citations.length} cited evidence snippets</p></details>
        </> : <EmptyState compact title="Ask an evidence-grounded question." description="Answers are grounded in cited evidence from your selected papers."/>}
    </section><EvidencePanel evidence={selected} onClose={closeEvidence}/></div>
  </div>;
}
