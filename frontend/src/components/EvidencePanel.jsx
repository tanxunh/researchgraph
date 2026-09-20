import { useEffect, useRef } from 'react';
import { Button, Drawer, Grid } from 'antd';
import { Link } from 'react-router-dom';

export function EvidenceDetails({ evidence }) {
  return <details><summary>Advanced details</summary><dl className="evidence-metadata">
    <dt>document_id</dt><dd>{evidence.document?.id ?? 'Not provided'}</dd>
    <dt>document_version_id</dt><dd>{evidence.document_version_id ?? 'Not provided'}</dd>
    <dt>chunk_id</dt><dd>{evidence.chunk_id ?? 'Not provided'}</dd>
  </dl></details>;
}

export default function EvidencePanel({ evidence, onClose }) {
  const screens = Grid.useBreakpoint();
  const close = useRef(null);
  useEffect(() => { if (evidence && screens.xl) close.current?.focus(); }, [evidence, screens.xl]);
  if (!evidence) return null;
  const content = <>
    {evidence.citationLabel && <p className="citation-label">[{evidence.citationLabel}]</p>}
    <h3><Link to={`/library/${evidence.document.id}`}>{evidence.document.title || 'Untitled paper'}</Link></h3>
    <dl className="evidence-metadata">
      <dt>Version</dt><dd>{evidence.document.version ?? 'Not provided'}</dd>
      <dt>Page</dt><dd>{evidence.location?.page_number ?? 'Not provided'}</dd>
      <dt>Section</dt><dd>{evidence.location?.section_title || 'Not provided'}</dd>
    </dl>
    {evidence.isSnippet && <p className="muted">Cited evidence snippet</p>}
    <p className="evidence-text">{evidence.text}</p>
    <EvidenceDetails evidence={evidence}/>
  </>;
  return screens.xl ? <aside className="evidence-panel" aria-label="Evidence details" onKeyDown={e=>{if(e.key==='Escape')onClose();}}>
    <div className="heading-row"><h2>Evidence</h2><Button ref={close} onClick={onClose} aria-label="Close Evidence">Close</Button></div>{content}
  </aside> : <Drawer title="Evidence" open onClose={onClose} width="100%" className="evidence-drawer" closeIcon={<span aria-label="Close Evidence">×</span>}>{content}</Drawer>;
}
