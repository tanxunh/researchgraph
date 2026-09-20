import { useEffect, useState } from 'react';
import { Button, Drawer, Grid } from 'antd';
import { AppstoreOutlined, BookOutlined, SearchOutlined, MessageOutlined, ExperimentOutlined, UnorderedListOutlined, MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import BackendStatus from './BackendStatus';
import { useBackendStatus } from '../hooks/useBackendStatus';
const links = [['/','Overview',AppstoreOutlined],['/library','Library',BookOutlined],['/search','Search',SearchOutlined],['/ask','Ask',MessageOutlined],['/research','Research',ExperimentOutlined],['/jobs','Jobs',UnorderedListOutlined]];
export default function AppShell() {
  const [collapsed,setCollapsed] = useState(false), [open,setOpen] = useState(false);
  const screens = Grid.useBreakpoint(), mobile = screens.md === false;
  const location = useLocation(); const status = useBackendStatus();
  useEffect(() => { setOpen(false); },[location.pathname]);
  const title = location.pathname.startsWith('/library/') ? 'Document Detail' : links.find(([url]) => url === location.pathname)?.[1] || 'Page not found';
  function navigation(compact=false) {
    return <><NavLink to="/" className="wordmark" aria-label="ResearchGraph overview"><span className="brand-mark">R<span>G</span></span>{!compact && <strong>ResearchGraph</strong>}</NavLink><nav aria-label="Main navigation">{links.map(([url,label,Icon]) => <NavLink end={url==='/'} to={url} key={url} className={({isActive}) => `nav-link ${isActive ? 'active' : ''}`} title={compact ? label : undefined} aria-label={compact ? label : undefined}><Icon aria-hidden="true" />{!compact && <span>{label}</span>}</NavLink>)}</nav><div className="sidebar-footer"><BackendStatus status={status} /></div></>;
  }
  return <div className={`product-shell ${collapsed ? 'is-collapsed' : ''}`}><a href="#workspace" className="skip-link">Skip to content</a>
    {!mobile && <aside className="sidebar">{navigation(collapsed)}</aside>}
    <Drawer title="Workspace navigation" placement="left" width={256} open={mobile && open} onClose={() => setOpen(false)}>{navigation()}</Drawer>
    <div className="workspace-frame"><header className="topbar"><div className="topbar-title"><Button type="text" aria-label={mobile ? 'Open navigation' : collapsed ? 'Expand sidebar' : 'Collapse sidebar'} aria-expanded={mobile ? open : !collapsed} icon={collapsed || mobile ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => mobile ? setOpen(true) : setCollapsed(!collapsed)} /><span>{title}</span></div></header>
    {status === 'offline' && <div className="offline-banner" role="status">Backend unavailable. You can explore the workspace; connected features need the backend.</div>}
    <main id="workspace" tabIndex={-1}><Outlet /></main><footer className="workspace-footer">Evidence-grounded. Traceable to your papers.</footer></div></div>;
}
