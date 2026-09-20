import { useCallback, useState } from 'react';
import { Button, Select, Table, Tooltip } from 'antd';
import { Link } from 'react-router-dom';
import { PageHeader, SectionCard, StatusBadge, ErrorState, LoadingState, EmptyState, ConfirmAction } from '../components/ui';
import { JobFailure } from '../components/JobViews';
import { libraryApi, stageLabel, timeLabel } from '../api/library';
import { useResource } from '../hooks/useResource';
const pollDelay=data=>data.summary.queued+data.summary.running>0 ? 2500 : null;
export default function Jobs() {
 const [query,setQuery]=useState({page:1,page_size:20}),[retrying,setRetrying]=useState(null),[retryError,setRetryError]=useState(null);
 const load=useCallback(signal=>libraryApi.jobs(query,{signal}),[query]);
 const {data,loading,error,refresh}=useResource(load,pollDelay);
 async function retry(id){setRetrying(id);setRetryError(null);try{await libraryApi.retry(id);refresh();}catch(e){setRetryError(e);}finally{setRetrying(null);}}
 function filter(key,value){setQuery(q=>({...q,page:1,[key]:value}));}
 return <div className="page-stack"><PageHeader title="Jobs" description="Follow indexing and reprocessing work." actions={<Button onClick={refresh} loading={loading}>Refresh jobs</Button>}/>
 {data && <div className="job-summary" aria-label="Global job summary">{['queued','running','succeeded','failed'].map(status=><SectionCard key={status}><StatusBadge status={status}/><strong aria-label={`${status} jobs`}>{data.summary[status]}</strong></SectionCard>)}</div>}
 <SectionCard><div className="jobs-filters"><label>Status<Select aria-label="Status filter" allowClear placeholder="All statuses" value={query.status} onChange={v=>filter('status',v)} options={['queued','running','succeeded','failed'].map(value=>({value,label:value}))}/></label><label>Operation<Select aria-label="Operation filter" allowClear placeholder="All operations" value={query.operation} onChange={v=>filter('operation',v)} options={[{value:'async_import',label:'Import'},{value:'async_reprocess',label:'Reprocess'}]}/></label></div>
 {retryError && <ErrorState error={retryError}/>}{error ? <ErrorState error={error} onRetry={refresh}/> : loading&&!data ? <LoadingState label="Loading jobs..."/> : <Table loading={loading} rowKey="job_id" dataSource={data?.items || []} scroll={{x:1100}} locale={{emptyText:<EmptyState title="No indexing jobs yet." description="Upload a paper or change the filters."/>}} pagination={{current:query.page,pageSize:query.page_size,total:data?.total || 0,showSizeChanger:true,pageSizeOptions:[20,50,100],onChange:(page,page_size)=>setQuery(q=>({...q,page,page_size}))}} expandable={{rowExpandable:row=>row.status==='failed',expandedRowRender:row=><JobFailure job={row}/>}} columns={[
 {title:'Job',dataIndex:'job_id',render:id=><Tooltip title={`Job ${id}`}><span>#{String(id).slice(0,8)}</span></Tooltip>},
 {title:'Document',dataIndex:'document_id',render:id=>id ? <Link to={`/library/${id}`}>Open document</Link> : 'Awaiting document association'},
 {title:'Operation',dataIndex:'job_type',render:t=>t==='async_import'?'Import':'Reprocess'},
 {title:'Status',dataIndex:'status',render:s=><StatusBadge status={s}/>},{title:'Stage',dataIndex:'progress_stage',render:stageLabel},
 {title:'Attempts',dataIndex:'attempts'},{title:'Created',dataIndex:'created_at',render:timeLabel},{title:'Finished',dataIndex:'finished_at',render:timeLabel},
 {title:'Action',render:(_,row)=>row.status==='failed' ? <ConfirmAction title="Retry this failed indexing job?" onConfirm={()=>retry(row.job_id)} disabled={retrying!==null}><Button aria-label={`Retry job ${row.job_id}`} disabled={retrying!==null} loading={retrying===row.job_id}>Retry</Button></ConfirmAction> : null},]}/>}
 <p className="shell-note">Summary covers all async jobs, regardless of filters. Historical jobs may have no creation timestamp. Updates pause when the tab is hidden and stop when no jobs are queued or running.</p></SectionCard></div>;
}
