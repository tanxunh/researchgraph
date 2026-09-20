import { Link } from 'react-router-dom';
import { FileSearchOutlined, LinkOutlined, ExperimentOutlined, ArrowRightOutlined } from '@ant-design/icons';
import { PageHeader, SectionCard } from '../components/ui';
export default function Overview() {
  return <div className="page-stack"><section className="intro"><PageHeader eyebrow="YOUR RESEARCH WORKSPACE" title="ResearchGraph" description="Evidence-grounded AI Research Assistant" /><p className="intro-copy">Upload research papers, ask grounded questions, and run evidence-backed cross-document research.</p><div className="cta-row"><Link className="action-link primary" to="/library">Upload Papers <ArrowRightOutlined aria-hidden="true" /></Link><Link className="action-link" to="/ask">Ask a Question</Link><Link className="action-link" to="/research">Start Research</Link></div></section>
    <div className="section-heading"><h2>From papers to supported findings</h2><p className="muted">Keep the evidence within reach.</p></div><div className="feature-grid">{[
      [FileSearchOutlined,'Grounded QA','Ask questions grounded in the papers you select. See the sources behind each answer.'],
      [LinkOutlined,'Traceable Evidence','Follow citations to a paper, page and immutable evidence version.'],
      [ExperimentOutlined,'Cross-document Research','Compare supported findings across papers, with explicit evidence gaps and limitations.'],
    ].map(([Icon,title,copy]) => <SectionCard key={title}><Icon className="feature-icon" aria-hidden="true" /><h3>{title}</h3><p className="muted">{copy}</p></SectionCard>)}</div>
    <div className="workflow-intro"><span className="eyebrow">HOW IT WORKS</span><p>Upload papers &rarr; Build your library &rarr; Ask and compare &rarr; Inspect the evidence</p></div>
  </div>;
}
