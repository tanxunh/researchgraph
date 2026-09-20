// @vitest-environment jsdom
import React from 'react';
import { beforeEach,afterEach,it,expect,vi } from 'vitest';
import { render,screen,fireEvent,cleanup,waitFor,act,renderHook,within } from '@testing-library/react';
import { MemoryRouter,Routes,Route } from 'react-router-dom';
import Library from '../pages/Library';
import Jobs from '../pages/Jobs';
import DocumentDetail from '../pages/DocumentDetail';
import { libraryApi,timeLabel,validateUpload } from '../api/library';
import { ApiClientError } from '../api/errors';
import { useJobPolling } from '../hooks/useJobPolling';
import { useResource } from '../hooks/useResource';
vi.mock('../api/library',async original=>({...await original(),libraryApi:{documents:vi.fn(),document:vi.fn(),versions:vi.fn(),jobs:vi.fn(),job:vi.fn(),upload:vi.fn(),retry:vi.fn()}}));
const paper={id:7,title:'Sample research paper',source_type:'pdf',current_version:1,chunk_count:3,status:'ready',updated_at:'2026-09-18T00:00:00'};
const job=(status='queued',id=12)=>({job_id:id,document_id:null,job_type:'async_import',status,progress_stage:status==='succeeded'?'completed':status,attempts:1,created_at:null,started_at:'1999-01-01T00:00:00',finished_at:null});
const result=(items=[job()],summary={queued:0,running:0,succeeded:0,failed:0})=>({items,page:1,page_size:20,total:60,summary});
beforeEach(()=>{
 vi.resetAllMocks();window.matchMedia=vi.fn(q=>({matches:false,media:q,addListener:vi.fn(),removeListener:vi.fn(),addEventListener:vi.fn(),removeEventListener:vi.fn()}));
 const style=window.getComputedStyle.bind(window);vi.spyOn(window,'getComputedStyle').mockImplementation(el=>style(el));
 Object.defineProperty(document,'hidden',{configurable:true,value:false});
 libraryApi.documents.mockResolvedValue([]);libraryApi.jobs.mockResolvedValue(result([]));
 libraryApi.upload.mockResolvedValue({job_id:12,status:'queued'});libraryApi.job.mockResolvedValue(job('succeeded'));
 libraryApi.document.mockResolvedValue(paper);libraryApi.versions.mockResolvedValue([{id:5,version:1,is_current:true,created_at:null}]);
});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.useRealTimers();});
function mount(Component){return render(<MemoryRouter><Component/></MemoryRouter>);}
it('Library loading then real empty state',async()=>{
 let resolve;libraryApi.documents.mockReturnValue(new Promise(r=>resolve=r));mount(Library);expect(screen.getByText('Loading documents...')).toBeTruthy();
 await act(async()=>resolve([]));expect(screen.getByText('No papers yet.')).toBeTruthy();
});
it('Library renders returned papers and real links',async()=>{libraryApi.documents.mockResolvedValue([paper]);mount(Library);expect(await screen.findByRole('link',{name:paper.title})).toBeTruthy();expect(screen.getByRole('link',{name:`Open ${paper.title}`}).getAttribute('href')).toBe('/library/7');});
it('Library network error is not empty',async()=>{libraryApi.documents.mockRejectedValue(new ApiClientError('network_error'));mount(Library);await screen.findByText(/Cannot reach the backend/);expect(screen.queryByText('No papers yet.')).toBeNull();});
it.each([['a.exe',2,'Unsupported'],['a.pdf',0,'Empty'],['a.pdf',9*1024*1024,'8 MiB']])('validates %s', (name,size,message)=>expect(validateUpload({name,size})).toContain(message));
it('upload gets job ID, reads job, and refreshes authoritative Documents',async()=>{
 libraryApi.documents.mockResolvedValueOnce([]).mockResolvedValue([paper]);
 libraryApi.job.mockResolvedValue({...job('succeeded'),document_id:7});const view=mount(Library);await screen.findByText('No papers yet.');
 const file=new File(['sample'],'safe.pdf',{type:'application/pdf'});
 fireEvent.change(view.container.querySelector('input[type=file]'),{target:{files:[file]}});
 await waitFor(()=>expect(libraryApi.upload).toHaveBeenCalledWith(file));
 await waitFor(()=>expect(libraryApi.job).toHaveBeenCalledWith(12,expect.anything()));
 expect(await screen.findByRole('link',{name:paper.title})).toBeTruthy();expect(libraryApi.documents.mock.calls.length).toBeGreaterThan(1);
});
it.each(['succeeded','failed'])('polling stops at %s',async terminal=>{
 vi.useFakeTimers();libraryApi.job.mockResolvedValueOnce(job()).mockResolvedValueOnce(job('running')).mockResolvedValueOnce(job(terminal));
 const done=vi.fn();renderHook(()=>useJobPolling(12,done));await act(async()=>{});
 await act(async()=>{await vi.advanceTimersByTimeAsync(1800);});await act(async()=>{await vi.advanceTimersByTimeAsync(1800);});
 expect(libraryApi.job).toHaveBeenCalledTimes(3);expect(done).toHaveBeenCalledTimes(1);
 await act(async()=>{await vi.advanceTimersByTimeAsync(20000);});expect(libraryApi.job).toHaveBeenCalledTimes(3);
});
it('unmount aborts requests and clears polling',async()=>{
 vi.useFakeTimers();libraryApi.job.mockResolvedValue(job());const view=renderHook(()=>useJobPolling(12));await act(async()=>{});
 view.unmount();await act(async()=>{await vi.advanceTimersByTimeAsync(10000);});expect(libraryApi.job).toHaveBeenCalledTimes(1);
});
it('Jobs restores from server on remount with global summary and null association',async()=>{
 libraryApi.jobs.mockResolvedValue(result([job()],{queued:50,running:8,succeeded:21,failed:3}));let view=mount(Jobs);
 await screen.findByText('Awaiting document association');expect(screen.getByLabelText('queued jobs').textContent).toBe('50');
 view.unmount();mount(Jobs);await screen.findByText('Awaiting document association');expect(libraryApi.jobs).toHaveBeenCalledTimes(2);
});
it('pagination sends server page',async()=>{mount(Jobs);await screen.findByText('No indexing jobs yet.');fireEvent.click(screen.getByTitle('2'));await waitFor(()=>expect(libraryApi.jobs).toHaveBeenLastCalledWith(expect.objectContaining({page:2,page_size:20}),expect.anything()));});
it.each([['Status filter','failed','status'],['Operation filter','Reprocess','operation']])('server filter %s',async(label,value,key)=>{
 mount(Jobs);await screen.findByText('No indexing jobs yet.');fireEvent.mouseDown(screen.getByRole('combobox',{name:label}));
 fireEvent.click(await screen.findByText(value,{selector:'.ant-select-item-option-content'}));
 await waitFor(()=>expect(libraryApi.jobs).toHaveBeenLastCalledWith(expect.objectContaining({page:1,[key]:key==='operation'?'async_reprocess':value}),expect.anything()));
});
it('only failed job offers confirmed retry, then refetch',async()=>{
 libraryApi.jobs.mockResolvedValue(result([job('failed',1),job('queued',2),job('running',3),job('succeeded',4)]));libraryApi.retry.mockResolvedValue({job_id:1,status:'queued'});
 mount(Jobs);const button=await screen.findByRole('button',{name:'Retry job 1'});expect(screen.queryByRole('button',{name:'Retry job 2'})).toBeNull();
 fireEvent.click(button);fireEvent.click(await screen.findByRole('button',{name:'Confirm'}));await waitFor(()=>expect(libraryApi.retry).toHaveBeenCalledWith(1));await waitFor(()=>expect(libraryApi.jobs.mock.calls.length).toBeGreaterThan(1));
},15000);
it('historical creation remains blank, never uses attempt timestamp',async()=>{libraryApi.jobs.mockResolvedValue(result([job()]));mount(Jobs);await screen.findByText('Awaiting document association');expect(timeLabel(null)).toBe('\u2014');expect(screen.queryByText(/1999/)).toBeNull();});
it('detail and Versions are fetched from APIs',async()=>{
 render(<MemoryRouter initialEntries={['/library/7']}><Routes><Route path="/library/:documentId" element={<DocumentDetail/>}/></Routes></MemoryRouter>);
 await screen.findByRole('heading',{name:paper.title});expect(libraryApi.document).toHaveBeenCalledWith('7',expect.anything());expect(libraryApi.versions).toHaveBeenCalledWith('7',expect.anything());
 fireEvent.click(screen.getByRole('tab',{name:'Versions'}));expect(await screen.findByText('Current',{selector:'.ant-tag'})).toBeTruthy();
});
it('list polling stops when global active summary reaches zero',async()=>{
 vi.useFakeTimers();const load=vi.fn().mockResolvedValueOnce(result([],{queued:1,running:0})).mockResolvedValue(result([]));const delay=data=>data.summary.queued+data.summary.running?2500:null;
 renderHook(()=>useResource(load,delay));await act(async()=>{});await act(async()=>{await vi.advanceTimersByTimeAsync(2500);});expect(load).toHaveBeenCalledTimes(2);
 await act(async()=>{await vi.advanceTimersByTimeAsync(10000);});expect(load).toHaveBeenCalledTimes(2);
});
