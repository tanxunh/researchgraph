import { Link } from 'react-router-dom';
import { EmptyState, SectionCard } from '../components/ui';
export function NotFound() { return <SectionCard><EmptyState title="Page not found" description="This address is not part of your research workspace." action={<Link to="/">Return to Overview</Link>} /></SectionCard>; }
