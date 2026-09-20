// @vitest-environment jsdom
import React from 'react';
import { beforeEach,afterEach,it,expect,vi } from 'vitest';
import { render,screen,fireEvent,cleanup,waitFor,within,act } from '@testing-library/react';
import { MemoryRouter, Routes, Route, Link } from 'react-router-dom';
import { readFileSync } from 'node:fs';
const styles = readFileSync('src/styles.css', 'utf8');
import SearchWorkspace from '../pages/SearchWorkspace';
import { libraryApi } from '../api/library';
import { searchEvidence } from '../api/search';
import { normalizeApiError,ApiClientError } from '../api/errors';
vi.mock('../api/library',()=>({libraryApi:{documents:vi.fn()}}));
vi.mock('../api/search',()=>({searchEvidence:vi.fn()}));
const papers=[{id:1,title:'Paper One',status:'ready'},{id:2,title:'Paper Two',status:'ready'},{id:3,title:'Indexing paper',status:'processing'}];
const evidence=(id=1)=>({document:{id,title:`Paper ${id}`,version:4,source_uri:'C:/private/paper.pdf'},document_version_id:44+id,chunk_id:`immutable-${id}`,text:`Evidence passage ${id}`,location:{page_number:7,section_title:'Methods'}});
const explicit=(excluded=[])=>({mode:'explicit',requested_document_ids:[1,...excluded.map(x=>x.document_id)],eligible_document_ids:[1],excluded_documents:excluded});
beforeEach(()=>{vi.resetAllMocks();window.matchMedia=vi.fn(q=>({matches:q.includes('min-width'),media:q,addListener:vi.fn(),removeListener:vi.fn(),addEventListener:vi.fn(),removeEventListener:vi.fn()}));const style=window.getComputedStyle.bind(window);vi.spyOn(window,'getComputedStyle').mockImplementation(el=>style(el));libraryApi.documents.mockResolvedValue(papers);searchEvidence.mockResolvedValue({scope:{mode:'global'},results:[evidence()]});});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
async function mount(){render(<MemoryRouter><SearchWorkspace/></MemoryRouter>);await waitFor(()=>expect(screen.getByRole('combobox').disabled).toBe(false));await act(async()=>{});}
function submit(){fireEvent.change(screen.getByLabelText('Search query'),{target:{value:'  Alpha  '}});fireEvent.submit(screen.getByLabelText('Search query').closest('form'));}
async function choose(title){fireEvent.mouseDown(screen.getByRole('combobox'));fireEvent.click(await screen.findByText(title,{selector:'.ant-select-item-option-content'}));}
it('initial state disables empty query and guards native submit',async()=>{await mount();expect(screen.getByText('Search your indexed papers.')).toBeTruthy();expect(screen.getByRole('button',{name:'Search',exact:true}).disabled).toBe(true);fireEvent.submit(screen.getByLabelText('Search query').closest('form'));expect(searchEvidence).not.toHaveBeenCalled();expect(screen.getByText('Enter a search query.')).toBeTruthy();});
it('native form submission uses current query and global scope',async()=>{await mount();submit();await screen.findByText('Evidence passage 1');expect(searchEvidence).toHaveBeenCalledWith({query:'  Alpha  ',documentIds:[]},expect.anything());expect(screen.getByRole('button',{name:'Search',exact:true}).type).toBe('submit');});
it.each([1,2])('submits %s selected ready papers',async count=>{await mount();await choose('Paper One');if(count===2)await choose('Paper Two');submit();await waitFor(()=>expect(searchEvidence).toHaveBeenCalledWith(expect.objectContaining({documentIds:count===1?[1]:[1,2]}),expect.anything()));},15000);
it('only ready options are selectable',async()=>{await mount();fireEvent.mouseDown(screen.getByRole('combobox'));await screen.findByText('Paper One',{selector:'.ant-select-item-option-content'});expect(screen.queryByText('Indexing paper')).toBeNull();});
it('loading prevents duplicate submission',async()=>{let resolve;searchEvidence.mockReturnValue(new Promise(r=>resolve=r));await mount();submit();submit();expect(screen.getByText('Searching your research library...')).toBeTruthy();expect(searchEvidence).toHaveBeenCalledTimes(1);await act(async()=>resolve({results:[],scope:{mode:'global'}}));});
it('valid scope no hits is distinct from no eligible',async()=>{searchEvidence.mockResolvedValue({results:[],scope:explicit()});await mount();submit();await screen.findByText('No evidence found for this query in the selected documents.');expect(screen.queryByText('None of the selected papers are ready for search.')).toBeNull();});
it.each(['not_ready','not_found'])('no eligible %s retains scope warning',async reason=>{const scope={...explicit([{document_id:2,reason}]),eligible_document_ids:[]};searchEvidence.mockRejectedValue(normalizeApiError(null,{http_status:200,payload:{code:1,data:{error_type:'no_eligible_documents',scope}}}));await mount();submit();await screen.findByText('None of the selected papers are ready for search.');expect(screen.queryByText('No evidence found for this query in the selected documents.')).toBeNull();expect(screen.getByText(reason==='not_ready'?'Selected papers are still indexing or unavailable.':'One or more selected papers no longer exist.')).toBeTruthy();});
it.each(['not_ready','not_found'])('partial scope shows exclusions %s',async reason=>{searchEvidence.mockResolvedValue({results:[evidence()],scope:explicit([{document_id:99,reason}])});await mount();submit();await screen.findByText('Searching 1 of 2 selected papers.');expect(screen.getByText('1 selected paper was excluded.')).toBeTruthy();expect(screen.getByText(new RegExp(`Document #99.*${reason==='not_ready'?'not ready':'not found'}`))).toBeTruthy();});
it.each([['empty_document_scope',422],['backend_unavailable',503],['network_error',null],['server_error',500]])('error %s is not no-results',async(code,status)=>{searchEvidence.mockRejectedValue(new ApiClientError(code,status));await mount();submit();await screen.findByText(new ApiClientError(code).message);expect(screen.queryByText('No evidence found for this query in the selected documents.')).toBeNull();});
it('panel binds exact locator and navigates document, never source path',async()=>{searchEvidence.mockResolvedValue({results:[evidence(1),evidence(2)],scope:{mode:'global'}});await mount();submit();await screen.findByText('Evidence passage 2');fireEvent.click(screen.getByRole('button',{name:'View Evidence 2'}));const panel=screen.getByRole('complementary',{name:'Evidence details'});const p=within(panel);expect(p.getByText('immutable-2')).toBeTruthy();expect(p.getByText('46')).toBeTruthy();expect(p.getByText('4')).toBeTruthy();expect(p.getByText('7')).toBeTruthy();expect(p.getByText('Methods')).toBeTruthy();expect(p.getByRole('link').getAttribute('href')).toBe('/library/2');expect(panel.textContent).not.toContain('C:/private');expect(searchEvidence).toHaveBeenCalledTimes(1);fireEvent.click(p.getByRole('button',{name:'Close Evidence'}));expect(screen.queryByRole('complementary')).toBeNull();});
it('missing section is graceful',async()=>{const row=evidence();row.location.section_title=null;searchEvidence.mockResolvedValue({results:[row],scope:{mode:'global'}});await mount();submit();await screen.findByText('Page 7');fireEvent.click(screen.getByRole('button',{name:'View Evidence 1'}));expect(within(screen.getByRole('complementary')).getByText('Not provided')).toBeTruthy();});

it('route re-entry fetches newly ready documents from server',async()=>{
 libraryApi.documents.mockResolvedValueOnce(papers).mockResolvedValue([...papers,{id:4,title:'New ready paper',status:'ready'}]);
 render(<MemoryRouter initialEntries={['/search']}><Link to="/library">Leave search</Link><Link to="/search">Enter search</Link><Routes><Route path="/search" element={<SearchWorkspace/>}/><Route path="/library" element={<p>Library route</p>}/></Routes></MemoryRouter>);
 await waitFor(()=>expect(screen.getByRole('combobox').disabled).toBe(false));
 await choose('Paper One');expect(libraryApi.documents).toHaveBeenCalledTimes(1);
 fireEvent.click(screen.getByRole('link',{name:'Leave search'}));fireEvent.click(screen.getByRole('link',{name:'Enter search'}));
 await waitFor(()=>expect(screen.getByRole('combobox').disabled).toBe(false));await choose('New ready paper');
 expect(libraryApi.documents).toHaveBeenCalledTimes(2);expect(screen.queryByText('Indexing paper')).toBeNull();
},15000);

it('focus refreshes authoritative ready options without duplicate or runaway requests',async()=>{
 let now=1000;vi.spyOn(Date,'now').mockImplementation(()=>now);
 Object.defineProperty(document,'hidden',{configurable:true,value:false});
 let resolve;libraryApi.documents.mockResolvedValueOnce(papers).mockImplementationOnce(()=>new Promise(r=>resolve=r));
 await mount();expect(libraryApi.documents).toHaveBeenCalledTimes(1);
 fireEvent.focus(window);expect(libraryApi.documents).toHaveBeenCalledTimes(1);
 now=2100;fireEvent.focus(window);expect(libraryApi.documents).toHaveBeenCalledTimes(2);
 now=4000;for(let i=0;i<10;i++)fireEvent.focus(window);
 expect(libraryApi.documents).toHaveBeenCalledTimes(2);
 await act(async()=>resolve([...papers,{id:4,title:'Focus ready paper',status:'ready'}]));
 await choose('Focus ready paper');expect(screen.queryByText('Indexing paper')).toBeNull();
 expect(libraryApi.documents).toHaveBeenCalledTimes(2);
 cleanup();now=8000;fireEvent.focus(window);expect(libraryApi.documents).toHaveBeenCalledTimes(2);
},15000);

it.each([true,false])('long evidence retains complete content and responsive layout, desktop=%s',async desktop=>{
 window.matchMedia=vi.fn(q=>({matches:desktop?q.includes('min-width'):q.includes('max-width'),media:q,addListener:vi.fn(),removeListener:vi.fn(),addEventListener:vi.fn(),removeEventListener:vi.fn()}));
 const style=document.createElement('style');style.textContent=styles;document.head.append(style);
 try {
  const row=evidence();row.document.title='LongTitle'.repeat(100);row.text='LongEvidence'.repeat(300);row.chunk_id='LongLocator'.repeat(100);
  searchEvidence.mockResolvedValue({results:[row],scope:{mode:'global'}});await mount();submit();await screen.findByRole('button',{name:'View Evidence 1'});
  fireEvent.click(screen.getByRole('button',{name:'View Evidence 1'}));
  const panel=await screen.findByRole(desktop?'complementary':'dialog');
  expect(within(panel).getByText(row.text).textContent).toBe(row.text);
  expect(within(panel).getByRole('link').textContent).toBe(row.document.title);
  expect(getComputedStyle(within(panel).getByText(row.text)).overflowWrap).toBe('anywhere');
  expect(getComputedStyle(within(panel).getByText(row.text)).overflow).not.toBe('hidden');
  expect(getComputedStyle(within(panel).getByText(row.chunk_id)).overflowWrap).toBe('anywhere');
  expect(getComputedStyle(within(panel).getByRole('link').parentElement).overflowWrap).toBe('anywhere');
  if(desktop){expect(getComputedStyle(panel).minWidth).toBe('0');expect(document.querySelector('.search-workspace.has-evidence')).toBeTruthy();}
  else expect(screen.queryByRole('complementary')).toBeNull();
  // JSDOM has no geometry: verify the actual desktop/narrow grid contracts, not fake bounding boxes.
  const rules=[...style.sheet.cssRules];
  expect(rules.filter(r=>r.selectorText?.split(',').map(s=>s.trim()).includes('.search-workspace.has-evidence')).at(-1).style.getPropertyValue('grid-template-columns')).toBe('minmax(0, 1fr) minmax(320px, 380px)');
  const narrow=rules.filter(r=>r.conditionText==='(max-width: 991px)')
    .flatMap(r=>[...r.cssRules]).filter(r=>r.selectorText==='.search-workspace.has-evidence').at(-1);
  expect(narrow.style.getPropertyValue('grid-template-columns').replace(/\s/g,'')).toBe('minmax(0,1fr)');
 } finally {style.remove();}
},15000);
