import { AlertCircle, ArrowUpRight, Check, CircleHelp, LoaderCircle, ShieldAlert, Sparkles } from 'lucide-react';
import { useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { api, ApiError } from '../api/client';
import { useApp } from '../context/AppContext';
import type { Recommendation } from '../types';

export function PageHeader({ eyebrow, title, description, action }: { eyebrow: string; title: string; description?: string; action?: ReactNode }) {
  return <header className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1>{description && <p>{description}</p>}</div>{action && <div className="header-action">{action}</div>}</header>;
}

export function Notice({ tone = 'info', children }: { tone?: 'info' | 'error' | 'success'; children: ReactNode }) {
  const Icon = tone === 'error' ? AlertCircle : tone === 'success' ? Check : CircleHelp;
  return <div className={`notice notice-${tone}`} role={tone === 'error' ? 'alert' : 'status'}><Icon size={17} aria-hidden="true"/><div>{children}</div></div>;
}

export function LoadingState({ label = 'Connecting to Aranya' }: { label?: string }) {
  return <div className="loading-state" role="status"><LoaderCircle size={18} className="spin" aria-hidden="true"/><span>{label}</span></div>;
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><span className="empty-mark"><Sparkles size={17}/></span><div><strong>{title}</strong><p>{detail}</p></div></div>;
}

export function Field({ label, hint, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const id = props.id || `field-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  return <label className="field" htmlFor={id}><span>{label}</span><input {...props} id={id}/>{hint && <small>{hint}</small>}</label>;
}

export function TextAreaField({ label, hint, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint?: string }) {
  const id = props.id || `field-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  return <label className="field" htmlFor={id}><span>{label}</span><textarea {...props} id={id}/>{hint && <small>{hint}</small>}</label>;
}

export function SelectField({ label, children, ...props }: SelectHTMLAttributes<HTMLSelectElement> & { label: string; children: ReactNode }) {
  const id = props.id || `select-${label.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`;
  return <label className="field" htmlFor={id}><span>{label}</span><select {...props} id={id}>{children}</select></label>;
}

export function ActionButton({ children, busy, variant = 'primary', ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; variant?: 'primary' | 'secondary' | 'quiet' }) {
  return <button {...props} className={`button button-${variant} ${props.className || ''}`} disabled={props.disabled || busy}>{busy && <LoaderCircle size={16} className="spin"/>}{children}</button>;
}

export function FarmRequired() {
  const { farmId } = useApp();
  if (farmId) return null;
  return <Notice tone="info">Choose your farm ID in the sidebar to connect this workflow. Aranya does not create or assign farms here.</Notice>;
}

export function RecommendationCard({ recommendation }: { recommendation: Recommendation }) {
  const { farmId } = useApp();
  const [feedback, setFeedback] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [feedbackError, setFeedbackError] = useState('');
  const confidence = Math.max(0, Math.min(100, Math.round((recommendation.confidence || 0) * 100)));
  async function record(followed: boolean, outcome: string) {
    if (!farmId) return;
    setFeedback('sending'); setFeedbackError('');
    try { await api.outcome(farmId, recommendation.source_agent, followed, outcome); setFeedback('sent'); }
    catch (error) { setFeedback('error'); setFeedbackError(error instanceof ApiError ? error.message : 'Feedback could not be recorded.'); }
  }
  return <article className={`recommendation severity-${recommendation.severity?.toLowerCase()}`}>
    <div className="rec-topline"><span className="signal"><span className="signal-dot"/>{recommendation.severity} · {recommendation.urgency}</span><span className="confidence">{confidence}% confidence</span></div>
    <h2>{recommendation.problem}</h2>
    <div className="rec-action"><span className="rec-label">Recommended action</span><p>{recommendation.recommended_action}</p></div>
    {recommendation.reasoning && <details className="rec-details"><summary>Reasoning and evidence <ArrowUpRight size={14}/></summary><p>{recommendation.reasoning}</p>{recommendation.evidence?.length > 0 && <ul>{recommendation.evidence.map((e, i) => <li key={`${e.source}-${i}`}><span>{e.description}</span><small>{e.source} · {Math.round(e.confidence * 100)}%</small></li>)}</ul>}</details>}
    {recommendation.monitoring_plan && <div className="rec-footnote"><strong>Next check</strong><span>{recommendation.monitoring_plan}</span></div>}
    {recommendation.escalate_to_expert && <Notice tone="error"><strong>Expert review recommended.</strong> {recommendation.escalation_reason}</Notice>}
    {recommendation.alternatives?.length ? <details className="rec-details"><summary>Other options</summary><ul>{recommendation.alternatives.map((a) => <li key={a}>{a}</li>)}</ul></details> : null}
    <div className="feedback-block"><span className="rec-label">Did you follow this advice? What happened?</span>{feedback === 'sent' ? <div className="feedback-done"><Check size={15}/> Feedback recorded</div> : <div className="feedback-actions"><button disabled={!farmId || feedback === 'sending'} onClick={() => record(true, 'improved')}>Followed · helped</button><button disabled={!farmId || feedback === 'sending'} onClick={() => record(true, 'no_change')}>No change</button><button disabled={!farmId || feedback === 'sending'} onClick={() => record(true, 'worsened')}>Worsened</button><button disabled={!farmId || feedback === 'sending'} onClick={() => record(false, 'no_change')}>Did not follow</button></div>}{feedback === 'sending' && <small role="status">Recording feedback…</small>}{feedback === 'error' && <Notice tone="error">{feedbackError}</Notice>}{!farmId && <small>Choose a farm to record feedback.</small>}</div>
  </article>;
}

export function WorkflowResult({ result, error, loading, onRetry }: { result: Recommendation | null; error: string; loading: boolean; onRetry?: () => void }) {
  if (loading) return <div className="processing"><div className="processing-orbit"><span/><span/><span/></div><div><span className="eyebrow">Analysis in progress</span><strong>Reading the evidence</strong><p>Aranya is evaluating the submitted information.</p></div></div>;
  if (error) return <div><Notice tone="error">{error}</Notice>{onRetry && <ActionButton variant="secondary" onClick={onRetry}>Try again</ActionButton>}</div>;
  if (result) return <RecommendationCard recommendation={result}/>;
  return null;
}

export function apiError(error: unknown) { return error instanceof ApiError ? error.message : 'The request could not be completed. Please try again.'; }

export function ExpertOnlyNote() { return <div className="expert-note"><ShieldAlert size={16}/> Consultation resolution is restricted to expert and administrator accounts by the server.</div>; }
