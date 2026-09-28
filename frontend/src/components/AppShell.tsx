import { Activity, Bell, BookOpen, BrainCircuit, CloudSun, Coins, LayoutDashboard, Leaf, LogOut, Menu, MessageCircle, ScanLine, Search, Sprout, Stethoscope, Tractor, X } from 'lucide-react';
import { useState } from 'react';
import type { LucideIcon } from 'lucide-react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { useApp } from '../context/AppContext';

const groups: { label: string; links: { to: string; text: string; Icon: LucideIcon; end?: boolean }[] }[] = [
  { label: 'OVERVIEW', links: [{ to: '/', text: 'Intelligence Center', Icon: LayoutDashboard, end: true }] },
  { label: 'PERCEPTION', links: [{ to: '/perception/crop', text: 'Crop scan', Icon: ScanLine }, { to: '/perception/livestock', text: 'Livestock scan', Icon: Stethoscope }, { to: '/perception/weather', text: 'Weather risk', Icon: CloudSun }, { to: '/perception/soil', text: 'Soil assessment', Icon: Sprout }] },
  { label: 'ANALYSIS', links: [{ to: '/analysis/history', text: 'Field history', Icon: Activity }, { to: '/analysis/economics', text: 'Field economics', Icon: Coins }, { to: '/analysis/market', text: 'Market intelligence', Icon: Search }] },
  { label: 'INTELLIGENCE', links: [{ to: '/intelligence/chat', text: 'Ask Aranya', Icon: MessageCircle }, { to: '/intelligence/research', text: 'Research', Icon: BookOpen }] },
  { label: 'ACTION', links: [{ to: '/action/planning', text: 'Planting window', Icon: Sprout }, { to: '/action/schemes', text: 'Scheme matching', Icon: Tractor }, { to: '/action/alerts', text: 'Alerts & consultations', Icon: Bell }] },
];

export function AppShell() {
  const { farmId, setFarmId, signOut } = useApp(); const [mobileMenu, setMobileMenu] = useState(false); const location = useLocation();
  return <div className="app-shell"><a className="skip-link" href="#main-content">Skip to main content</a>
    <aside className={`sidebar ${mobileMenu ? 'sidebar-open' : ''}`} aria-label="Main navigation"><div className="sidebar-top"><NavLink to="/" className="brand-lockup" onClick={() => setMobileMenu(false)}><span className="brand-emblem"><Leaf size={18}/></span><span>ARANYA<span className="brand-period">.</span><small>FARM INTELLIGENCE</small></span></NavLink><button className="icon-button mobile-close" onClick={() => setMobileMenu(false)} aria-label="Close navigation"><X size={20}/></button></div>
      <div className="farm-context"><label htmlFor="farm-context-input"><span className="eyebrow">ACTIVE FARM</span></label><div className="farm-context-input"><span className="farm-indicator"/><input id="farm-context-input" type="number" min="1" value={farmId || ''} placeholder="Enter farm ID" onChange={(e) => setFarmId(e.target.value ? Number(e.target.value) : null)}/></div><small>{farmId ? `Context · ${farmId}` : 'Required for farm data'}</small></div>
      <nav className="nav-groups">{groups.map((group) => <div className="nav-group" key={group.label}><span className="nav-group-title">{group.label}</span>{group.links.map(({ to, text, Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setMobileMenu(false)} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}><Icon size={17} strokeWidth={1.7}/><span>{text}</span></NavLink>)}</div>)}</nav>
      <div className="sidebar-bottom"><div className="connection-chip"><span className="live-dot"/><span>API · checked on request</span></div><button className="account-button" onClick={signOut}><span className="account-avatar">A</span><span><strong>Current session</strong><small>Sign out</small></span><LogOut size={16}/></button></div>
    </aside>
    {mobileMenu && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setMobileMenu(false)}/>}
    <div className="shell-main"><header className="mobile-header"><button className="icon-button" aria-label="Open navigation" onClick={() => setMobileMenu(true)}><Menu size={20}/></button><NavLink to="/" className="mobile-brand"><Leaf size={16}/> ARANYA</NavLink><span className="mobile-farm">{farmId ? `FARM ${farmId}` : 'NO FARM'}</span></header><main id="main-content" key={location.pathname}><Outlet/></main><nav className="mobile-nav" aria-label="Quick navigation"><NavLink to="/" end><LayoutDashboard size={18}/><span>Center</span></NavLink><NavLink to="/perception/crop"><ScanLine size={18}/><span>Scan</span></NavLink><NavLink to="/intelligence/chat"><BrainCircuit size={18}/><span>Ask</span></NavLink><NavLink to="/action/alerts"><Bell size={18}/><span>Alerts</span></NavLink></nav></div>
  </div>;
}
