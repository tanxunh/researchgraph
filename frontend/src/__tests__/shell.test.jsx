// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within, act } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import App from '../App';
import { apiClient } from '../api/client';
import { useBackendStatus } from '../hooks/useBackendStatus';
vi.mock('../api/client',()=>({apiClient:{get:vi.fn()}}));
vi.mock('../api/library',async importOriginal=>({...await importOriginal(),libraryApi:{
  documents:async()=>[],document:async()=>({title:'Document Detail',status:'ready'}),versions:async()=>[],
  jobs:async()=>({items:[],total:0,summary:{queued:0,running:0,succeeded:0,failed:0}}),
}}));
function viewport(width) {
  window.matchMedia=vi.fn(query=>({matches:query.includes('max-width') ? width<=Number(query.match(/\d+/)?.[0]||0) : width>=Number(query.match(/\d+/)?.[0]||0),media:query,addListener:vi.fn(),removeListener:vi.fn(),addEventListener:vi.fn(),removeEventListener:vi.fn(),dispatchEvent:vi.fn()}));
}
function mount(path='/'){window.history.replaceState({},'',path);return render(<BrowserRouter><App/></BrowserRouter>);}
beforeEach(()=>{viewport(1440);vi.clearAllMocks();apiClient.get.mockResolvedValue({status:'ok'});Object.defineProperty(document,'hidden',{configurable:true,value:false});
  // JSDOM has no pseudo-element layout; retain real element style calculation.
  const getStyle=window.getComputedStyle.bind(window);
  vi.spyOn(window,'getComputedStyle').mockImplementation(element=>getStyle(element));
});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.useRealTimers();});
describe('URL shell',()=>{
  it.each([['/','ResearchGraph'],['/library','Library'],['/search','Search'],['/ask','Ask'],['/research','Research'],['/jobs','Jobs'],['/library/42','Document Detail']])('direct loads and remounts %s',async(path,title)=>{
    let view=mount(path);expect(screen.getByRole('heading',{level:1,name:title})).toBeTruthy();view.unmount();
    mount(window.location.pathname);expect(screen.getByRole('heading',{level:1,name:title})).toBeTruthy();await screen.findByText('Backend Online');
    if(path.startsWith('/library')) expect(within(screen.getByRole('navigation',{name:'Main navigation'})).getByRole('link',{name:'Library',exact:true}).getAttribute('aria-current')).toBe('page');
  });
  it('navigation changes URL and active state',async()=>{mount();fireEvent.click(screen.getByRole('link',{name:'Library',exact:true}));expect(window.location.pathname).toBe('/library');expect(screen.getByRole('link',{name:'Library',exact:true}).getAttribute('aria-current')).toBe('page');expect(screen.queryByRole('link',{name:'Evaluation'})).toBeNull();await screen.findByText('Backend Online');},15000);
  it.each([['Upload Papers','/library'],['Ask a Question','/ask'],['Start Research','/research']])('CTA %s',async(name,path)=>{mount();fireEvent.click(screen.getByRole('link',{name}));expect(window.location.pathname).toBe(path);await screen.findByText('Backend Online');});
  it('404 offers return home',async()=>{mount('/missing');expect(screen.getByText('Page not found',{selector:'h3'})).toBeTruthy();fireEvent.click(screen.getByRole('link',{name:'Return to Overview'}));expect(window.location.pathname).toBe('/');await screen.findByText('Backend Online');});
  it('checking then offline retains main',async()=>{let reject;apiClient.get.mockReturnValue(new Promise((_,r)=>{reject=r;}));mount('/ask');expect(screen.getByText('Backend Checking')).toBeTruthy();await act(async()=>reject(new Error('offline')));expect(screen.getByText('Backend Offline')).toBeTruthy();expect(screen.getByRole('main')).toBeTruthy();});
  it.each([1440,1280,1024])('collapsible desktop at %s',async width=>{viewport(width);mount();fireEvent.click(screen.getByRole('button',{name:'Collapse sidebar'}));expect(screen.getByRole('button',{name:'Expand sidebar'})).toBeTruthy();expect(screen.getByRole('navigation',{name:'Main navigation'})).toBeTruthy();await screen.findByText('Backend Online');});
  it('mobile menu is a drawer',async()=>{viewport(600);mount();fireEvent.click(screen.getByRole('button',{name:'Open navigation'}));const dialog=await screen.findByRole('dialog');fireEvent.click(within(dialog).getByRole('link',{name:'Jobs'}));expect(window.location.pathname).toBe('/jobs');});
});
function Probe(){const s=useBackendStatus();return <span>{s}</span>;}
it('polling is bounded, pauses hidden and stops unmounted',async()=>{
  vi.useFakeTimers();const view=render(<Probe/>);await act(async()=>{});expect(apiClient.get).toHaveBeenCalledTimes(1);
  await act(async()=>{await vi.advanceTimersByTimeAsync(44999);});expect(apiClient.get).toHaveBeenCalledTimes(1);
  await act(async()=>{await vi.advanceTimersByTimeAsync(1);});expect(apiClient.get).toHaveBeenCalledTimes(2);
  Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));
  await act(async()=>{await vi.advanceTimersByTimeAsync(90000);});expect(apiClient.get).toHaveBeenCalledTimes(2);
  view.unmount();await act(async()=>{await vi.advanceTimersByTimeAsync(90000);});expect(apiClient.get).toHaveBeenCalledTimes(2);
});
