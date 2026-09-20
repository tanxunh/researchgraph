import { Button, Alert } from 'antd';
import { Link } from 'react-router-dom';
import { StatusBadge, ErrorState } from './ui';
import { useJobPolling } from '../hooks/useJobPolling';
import { stageLabel } from '../api/library';
export function JobFailure({job}) {
 const code=job.error_type;
 const text=code==='process_interrupted'||code==='worker_interrupted' ? 'Worker interrupted. Inspect the job before retrying.' : code==='ParserError' ? 'The document could not be parsed.' : 'Indexing failed. Check the reported stage and retry after resolving the cause.';
 return <Alert type="error" showIcon message={text} description={<details><summary>Advanced details</summary><span>Error type: {code || 'Not reported'}</span><p>Stage: {stageLabel(job.progress_stage)}</p></details>}/>;
}
export function UploadJob({accepted,filename,onTerminal}) {
 const {job,error,refresh}=useJobPolling(accepted.job_id,onTerminal);
 const current=job || accepted;
 return <article className="upload-job"><strong>{filename}</strong><div className="job-state"><StatusBadge status={current.status}/><span>{job ? stageLabel(job.progress_stage) : accepted.status==='queued' ? 'Queued for indexing' : 'Job accepted'}</span><Link to="/jobs">View Jobs</Link>{job?.document_id && <Link to={`/library/${job.document_id}`}>Open document</Link>}</div>{error && <ErrorState error={error} onRetry={refresh}/ >}{job?.status==='failed' && <JobFailure job={job}/>}</article>;
}
