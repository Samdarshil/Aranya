import { ArrowRight, Bell, CloudSun, Leaf, ScanLine, Sprout } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import { useApp } from '../context/AppContext';
import type { Alert } from '../types';
import { ActionButton, apiError, EmptyState, LoadingState, Notice, PageHeader } from '../components/Ui';

export function OverviewPage() {
  const { farmId } = useApp();
  const [alerts, setAlerts] = useState<Alert[]>([]); const [loading, setLoading] = useState(false); const [error, setError] = useState('');
  const load = useCallback(async () => {
    if (!farmId) { setAlerts([]); setError(''); return; }
    setLoading(true); setError('');
    try { setAlerts(await api.alerts(farmId)); } catch (e) { setError(apiError(e)); } finally { setLoading(false); }
  }, [farmId]);
  useEffect(() => { void load(); }, [load]);
  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning.' : hour < 18 ? 'Good afternoon.' : 'Good evening.';
  return <div className="page-wrap">
    <PageHeader eyebrow="Aranya Intelligence Center" title={greeting} description="Here’s what Aranya can see across your farm right now." action={<span className="status-pill">Evidence first · No simulated data</span>}/>
    <section className="overview-intro"><div className="intro-orb"><span/><span/><span/></div><div><span className="eyebrow">Your farm, in focus</span><h2>{farmId ? `Farm ${farmId}` : 'Connect your farm context'}</h2><p>{farmId ? 'Signals and recommendations below are scoped to the selected farm.' : 'Add your farm ID in the sidebar. Aranya will use it to request farm-scoped information.'}</p></div><div className="intro-index"><span>01</span><span>FIELD CONTEXT</span></div></section>
    <div className="section-heading"><div><span className="eyebrow">Live signal</span><h2>What needs attention</h2></div><Link className="inline-link" to="/action/alerts">All alerts <ArrowRight size={15}/></Link></div>
    {!farmId ? <EmptyState title="No farm selected" detail="Enter a farm ID in the navigation to load alerts and use the analysis tools."/> : loading ? <LoadingState label="Checking current alerts"/> : error ? <Notice tone="error">{error} <button className="inline-button" onClick={() => void load()}>Retry</button></Notice> : alerts.length ? <div className="alert-list">{alerts.slice(0, 3).map((alert) => <div className="alert-row" key={alert.id}><span className="alert-glyph"><Bell size={17}/></span><div><span className="eyebrow">{alert.severity} · {alert.subject_ref || 'Farm alert'}</span><strong>{alert.problem}</strong><small>{alert.created_at}</small></div><Link aria-label={`View alerts for ${alert.problem}`} to="/action/alerts"><ArrowRight size={17}/></Link></div>)}</div> : <EmptyState title="No active alerts" detail="The alert feed is clear. New alerts appear here when the backend has actionable signals."/>}
    <div className="section-heading section-heading-gap"><div><span className="eyebrow">Explore the evidence</span><h2>Intelligence, by task</h2></div></div>
    <div className="center-grid">
      <Link className="center-card feature-card" to="/perception/crop"><span className="card-index">01 / PERCEPTION</span><span className="card-icon"><ScanLine size={19}/></span><h3>Read a crop</h3><p>Submit a field image for a visual screen and grounded recommendation.</p><span className="card-link">Start crop scan <ArrowRight size={15}/></span></Link>
      <Link className="center-card" to="/perception/weather"><span className="card-index">02 / ENVIRONMENT</span><span className="card-icon"><CloudSun size={19}/></span><h3>Conditions & soil</h3><p>Assess weather risk, then add soil measurements through the navigation.</p><span className="card-link">Review conditions <ArrowRight size={15}/></span></Link>
      <Link className="center-card" to="/analysis/economics"><span className="card-index">03 / ANALYSIS</span><span className="card-icon"><Sprout size={19}/></span><h3>Field economics</h3><p>Log costs or sales and request the current cycle’s calculation.</p><span className="card-link">Review a field <ArrowRight size={15}/></span></Link>
      <Link className="center-card" to="/intelligence/chat"><span className="card-index">04 / INTELLIGENCE</span><span className="card-icon"><Leaf size={19}/></span><h3>Ask Aranya</h3><p>Describe what you’re seeing and let the existing intent router respond.</p><span className="card-link">Start a conversation <ArrowRight size={15}/></span></Link>
    </div>
    <section className="center-note"><div><span className="eyebrow">Grounded by design</span><p>Aranya only shows information returned by its services. When a provider or history is unavailable, the interface says so instead of filling the gap with a guess.</p></div><ActionButton variant="quiet" onClick={() => void load()}>Refresh signals</ActionButton></section>
  </div>;
}
