// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { readFileSync } from 'node:fs';
import EvidencePanel from '../components/EvidencePanel';
import { ErrorState, StatusBadge } from '../components/ui';
import { ApiClientError } from '../api/errors';
const css=readFileSync('src/styles.css','utf8');
let style;
beforeEach(()=>{
  style=document.createElement('style');style.textContent=css;document.head.append(style);
  const getStyle=window.getComputedStyle.bind(window);vi.spyOn(window,'getComputedStyle').mockImplementation(el=>getStyle(el));
});
afterEach(()=>{cleanup();style.remove();vi.restoreAllMocks();});
function viewport(width){window.matchMedia=vi.fn(query=>({matches:query.includes('max-width')?width<=Number(query.match(/\d+/)[0]):width>=Number(query.match(/\d+/)[0]),media:query,addListener:vi.fn(),removeListener:vi.fn(),addEventListener:vi.fn(),removeEventListener:vi.fn()}));}
it.each([1440,1280,1024,768])('Evidence uses readable side panel or Drawer at %s',async width=>{
  viewport(width);const onClose=vi.fn();const evidence={document:{id:27,title:'LongTitle'.repeat(100),version:2},document_version_id:42,chunk_id:'long-chunk-'.repeat(100),text:'Evidence '.repeat(500),location:{page_number:3}};
  render(<MemoryRouter><EvidencePanel evidence={evidence} onClose={onClose}/></MemoryRouter>);
  const panel=width>=1200?screen.getByRole('complementary'):await screen.findByRole('dialog');
  expect(within(panel).getByText(evidence.text.trim()).textContent).toBe(evidence.text);
  expect(getComputedStyle(within(panel).getByText(evidence.chunk_id)).overflowWrap).toBe('anywhere');
  expect(getComputedStyle(within(panel).getByRole('link').parentElement).overflowWrap).toBe('anywhere');
  if(width<1200)expect(screen.queryByRole('complementary')).toBeNull();
  fireEvent.click(within(panel).getByRole('button',{name:width>=1200?'Close Evidence':/close/i}));expect(onClose).toHaveBeenCalledTimes(1);
},15000);
it('shared responsive rules stack Search/Ask and keep table overflow local',()=>{
  const rules=[...style.sheet.cssRules];const narrow=rules.find(r=>r.conditionText==='(max-width: 1199px)');
  const grid=[...narrow.cssRules].find(r=>r.selectorText.includes('.research-workspace'));
  expect(grid.style.getPropertyValue('grid-template-columns')).toBe('minmax(0, 1fr)');
  expect([...narrow.cssRules].find(r=>r.selectorText.includes('.ask-form')).style.getPropertyValue('grid-template-columns')).toBe('minmax(0, 1fr)');
  render(<div className="comparison-scroll"><table className="research-comparison"><tbody><tr><td>LongToken</td></tr></tbody></table></div>);
  expect(getComputedStyle(screen.getByRole('table').parentElement).overflowX).toBe('auto');
  expect(getComputedStyle(screen.getByRole('cell')).overflowWrap).toBe('anywhere');
});
it('global offline has one banner and a quiet page-level unavailable state',()=>{
  render(<div><div className="offline-banner" role="status">Backend unavailable</div><main><ErrorState error={new ApiClientError('backend_unavailable')} onRetry={()=>{}}/></main></div>);
  // JSDOM does not implement :where specificity correctly against Ant's injected CSS.
  // Reattach the product stylesheet after injection to inspect the intended override.
  document.head.append(style);
  expect(screen.getAllByRole('status')).toHaveLength(1);
  expect(document.querySelectorAll('.ant-alert-error')).toHaveLength(0);
  const alert=document.querySelector('.connection-error');expect(getComputedStyle(alert).backgroundColor).toBe('rgba(0, 0, 0, 0)');
  expect(getComputedStyle(alert.querySelector('.ant-alert-icon')).display).toBe('none');
  expect(screen.getByRole('button',{name:'Try again'})).toBeTruthy();
});
it('completed is shared success and partial remains warning',()=>{
  render(<><StatusBadge status="succeeded"/><StatusBadge status="completed"/><StatusBadge status="partial"/></>);
  expect(screen.getAllByText('Completed').every(el=>el.classList.contains('ant-tag-success'))).toBe(true);
  expect(screen.getByText('Partial').classList.contains('ant-tag-warning')).toBe(true);
});
