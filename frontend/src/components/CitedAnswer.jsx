export default function CitedAnswer({ answer, citations, selectedId, onSelect }) {
  const byId = new Map(citations.map(citation => [citation.citation_id, citation]));
  return <div className="grounded-answer">{answer.split(/\n\s*\n/).map((paragraph, index) =>
    <p key={index}>{paragraph.split(/(\[C[1-9][0-9]*\])/g).map((token, part) => {
      const citation = /^\[C[1-9][0-9]*\]$/.test(token) ? byId.get(token.slice(1,-1)) : null;
      return citation ? <button key={part} type="button" className="inline-citation"
        aria-label={`Open evidence ${citation.citation_id}`} aria-pressed={selectedId===citation.citation_id}
        onClick={event=>onSelect(citation,event.currentTarget)}>{token}</button> : token;
    })}</p>)}</div>;
}
