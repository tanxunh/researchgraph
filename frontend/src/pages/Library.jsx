import { useCallback, useRef, useState } from 'react';
import { Alert, Button, Table, Upload } from 'antd';
import { InboxOutlined } from '@ant-design/icons';
import { Link } from 'react-router-dom';
import { PageHeader, SectionCard, EmptyState, ErrorState, LoadingState, StatusBadge } from '../components/ui';
import { UploadJob } from '../components/JobViews';
import { libraryApi, validateUpload, timeLabel } from '../api/library';
import { useResource } from '../hooks/useResource';
export default function Library() {
 const load=useCallback(signal=>libraryApi.documents({signal}),[]);
 const {data,loading,error,refresh}=useResource(load);
 const [uploads,setUploads]=useState([]),[uploadError,setUploadError]=useState(null),[validation,setValidation]=useState('');
 const [sending,setSending]=useState(false);const lock=useRef(false),area=useRef();
 const terminal=useCallback(job=>{if(job.status==='succeeded')refresh();},[refresh]);
 async function submit({file,onSuccess,onError}) {
  const invalid=validateUpload(file);if(invalid){setValidation(invalid);onError?.(new Error(invalid));return;}
  if(lock.current){onError?.(new Error('Upload already in progress'));return;}
  lock.current=true;setSending(true);setUploadError(null);setValidation('');
  try {const accepted=await libraryApi.upload(file);if(!accepted?.job_id)throw new Error('Missing job ID');
   setUploads(rows=>[...rows,{accepted,filename:file.name}]);onSuccess?.(accepted);
  }catch(e){setUploadError(e);onError?.(e);}finally{lock.current=false;setSending(false);}
 }
 function focusUpload(){area.current?.scrollIntoView?.({behavior:'smooth'});area.current?.querySelector('button')?.focus();}
 return <div className="page-stack"><PageHeader title="Library" description="Your papers, ready for research." actions={<Button onClick={focusUpload}>Upload Papers</Button>}/>
 <SectionCard title="Upload papers"><div ref={area}><Upload.Dragger multiple={false} disabled={sending} showUploadList={false} accept=".pdf,.docx,.txt,.md,.markdown" customRequest={submit}><p><InboxOutlined aria-hidden="true"/></p><p>{sending ? 'Uploading file...' : 'Drop a paper here, or select a file'}</p><p className="muted">PDF, DOCX, TXT or Markdown. Up to 8 MiB per file. Upload one file at a time.</p></Upload.Dragger></div>{validation && <Alert type="warning" message={validation}/ >}{uploadError && <><p>Upload failed. No accepted job has been confirmed. Check Jobs before resubmitting after a timeout.</p><ErrorState error={uploadError}/></>}
 {uploads.length>0 && <section aria-label="Recent uploads"><h3>Recent uploads</h3>{uploads.map(item=><UploadJob key={item.accepted.job_id} {...item} onTerminal={terminal}/>)}</section>}<p className="shell-note">Indexing continues on the server. Open <Link to="/jobs">Jobs</Link> to recover all tasks after refreshing or leaving this page.</p></SectionCard>
 <SectionCard title="Papers" extra={<Button onClick={refresh} loading={loading}>Refresh library</Button>}>
 {error ? <><p>Library is unavailable. Your existing papers have not been removed.</p><ErrorState error={error} onRetry={refresh}/></> : loading && !data ? <LoadingState label="Loading documents..."/> : data?.length===0 ? <EmptyState title="No papers yet." description="Upload your first paper to build a research workspace." action={<Button onClick={focusUpload}>Upload Papers</Button>}/> : <Table loading={loading} rowKey="id" dataSource={data || []} scroll={{x:850}} columns={[
 {title:'Title',dataIndex:'title',render:(title,row)=><Link to={`/library/${row.id}`}>{title}</Link>},
 {title:'Type',dataIndex:'source_type'},{title:'Pages',render:()=> <span title="The document API does not provide total pages">Not provided</span>},
 {title:'Version',dataIndex:'current_version'},{title:'Chunks',dataIndex:'chunk_count'},
 {title:'Status',dataIndex:'status',render:status=><StatusBadge status={status}/>},{title:'Updated',dataIndex:'updated_at',render:timeLabel},
 {title:'Action',render:(_,row)=><Link aria-label={`Open ${row.title}`} to={`/library/${row.id}`}>Open</Link>},]}/>}</SectionCard></div>;
}
