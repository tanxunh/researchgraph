import { useCallback } from 'react';
import { Breadcrumb, Button, Descriptions, Table, Tabs, Tag } from 'antd';
import { Link, useParams } from 'react-router-dom';
import { PageHeader, SectionCard, StatusBadge, LoadingState, ErrorState } from '../components/ui';
import { libraryApi, timeLabel } from '../api/library';
import { useResource } from '../hooks/useResource';
export default function DocumentDetail(){
 const {documentId}=useParams();
 const load=useCallback(async signal=>{const [document,versions]=await Promise.all([libraryApi.document(documentId,{signal}),libraryApi.versions(documentId,{signal})]);return {document,versions};},[documentId]);
 const {data,loading,error,refresh}=useResource(load);
 const doc=data?.document;
 return <div className="page-stack"><Breadcrumb items={[{title:<Link to="/library">Library</Link>},{title:'Document detail'}]}/><PageHeader title={doc?.title || 'Document Detail'} description="Document metadata and version history." actions={<Button onClick={refresh} loading={loading}>Refresh document</Button>}/>
 {error ? <ErrorState error={error} onRetry={refresh}/> : !data ? <LoadingState label="Loading document and versions..."/> : <SectionCard><Tabs items={[
 {key:'overview',label:'Overview',children:<Descriptions column={{xs:1,md:2}} items={[{key:'status',label:'Status',children:<StatusBadge status={doc.status}/>},{key:'type',label:'Type',children:doc.source_type},{key:'pages',label:'Pages',children:'Not provided by the document API'},{key:'chunks',label:'Chunks',children:doc.chunk_count},{key:'version',label:'Current Version',children:doc.current_version},{key:'created',label:'Created',children:timeLabel(doc.created_at)},{key:'updated',label:'Updated',children:timeLabel(doc.updated_at)}]}/>},
 {key:'versions',label:'Versions',children:<Table scroll={{x:600}} rowKey="id" dataSource={data.versions} columns={[{title:'Version',dataIndex:'version'},{title:'Status',render:(_,v)=><Tag color={v.is_current?'green':'default'}>{v.is_current?'Current':v.is_pending?'Pending':'Historical'}</Tag>},{title:'Created',dataIndex:'created_at',render:timeLabel}]} pagination={false}/>} ]}/></SectionCard>}</div>;
}
