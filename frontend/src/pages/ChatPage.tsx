import { ArrowUp, AudioLines, Bot, CircleUserRound, Mic, Paperclip } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { api } from '../api/client';
import { useApp } from '../context/AppContext';
import type { ChatReply } from '../types';
import { apiError, FarmRequired, Notice } from '../components/Ui';

type Message = { id: number; from: 'farmer' | 'aranya'; text: string; reply?: ChatReply; pending?: boolean; error?: boolean };

export function ChatPage() {
  const { farmId } = useApp(); const [messages, setMessages] = useState<Message[]>([]); const [text, setText] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState(''); const [audio, setAudio] = useState<File | null>(null);
  const sequence = useRef(0); const scroll = useRef<HTMLDivElement>(null);
  useEffect(() => { scroll.current?.scrollTo({ top: scroll.current.scrollHeight, behavior: 'smooth' }); }, [messages, busy]);
  async function send(event?: FormEvent) {
    event?.preventDefault(); const message = text.trim(); if (!message || !farmId || busy) return;
    const userMessage: Message = { id: ++sequence.current, from: 'farmer', text: message };
    const pending: Message = { id: ++sequence.current, from: 'aranya', text: 'Reading your question against available farm context…', pending: true };
    setMessages((items) => [...items, userMessage, pending]); setText(''); setBusy(true); setError('');
    try { const reply = await api.chat(farmId, message); setMessages((items) => items.map((m) => m.id === pending.id ? { ...m, pending: false, text: reply.message || reply.what_happened || 'Aranya returned a response.', reply } : m)); }
    catch (e) { const detail = apiError(e); setMessages((items) => items.map((m) => m.id === pending.id ? { ...m, pending: false, error: true, text: detail } : m)); setError(detail); }
    finally { setBusy(false); }
  }
  async function sendVoice() {
    if (!audio || !farmId || busy) return; setBusy(true); setError('');
    const farmerId = ++sequence.current;
    const pending: Message = { id: ++sequence.current, from: 'aranya', text: 'Processing your voice note…', pending: true };
    setMessages((items) => [...items, { id: farmerId, from: 'farmer', text: audio.name }, pending]);
    try { const reply = await api.voice(farmId, audio); setMessages((items) => items.map((m) => m.id === farmerId ? { ...m, text: reply.transcript || audio.name } : m.id === pending.id ? { ...m, pending: false, text: reply.message || reply.what_happened || 'Voice request processed.', reply } : m)); setAudio(null); }
    catch (e) { const detail = apiError(e); setError(detail); setMessages((items) => items.map((m) => m.id === pending.id ? { ...m, pending: false, error: true, text: detail } : m)); }
    finally { setBusy(false); }
  }
  return <div className="page-wrap chat-page"><div className="chat-heading"><div><div className="eyebrow">INTELLIGENCE / CONVERSATION</div><h1>Ask Aranya</h1><p>Questions are routed through the existing farm intelligence services.</p></div><span className="assistant-status"><span className="live-dot"/> Text interface</span></div><FarmRequired/>
      <section className="chat-panel" aria-label="Conversation with Aranya"><div className="chat-messages" ref={scroll} aria-live="polite" aria-relevant="additions text">{messages.length === 0 ? <div className="chat-empty"><div className="assistant-orb"><AudioLines size={24}/></div><span className="eyebrow">A farm-aware conversation</span><h2>What are you noticing?</h2><p>Ask about a field, planting timing, conditions, or an observation. Aranya will answer only through the services currently available.</p><div className="suggestion-list"><button onClick={() => setText('What is the current situation with my field?')}>Ask about a field</button><button onClick={() => setText('When is a good time to plant?')}>Ask about planting</button><button onClick={() => setText('What should I know about my farm?')}>Ask a farm question</button></div></div> : messages.map((m) => <article className={`chat-message ${m.from === 'farmer' ? 'from-farmer' : 'from-aranya'} ${m.error ? 'message-error' : ''}`} key={m.id}><span className="message-avatar">{m.from === 'farmer' ? <CircleUserRound size={17}/> : <Bot size={17}/>}</span><div className="message-content"><span className="eyebrow">{m.from === 'farmer' ? 'YOU' : 'ARANYA'}{m.pending ? ' · WORKING' : ''}</span><p>{m.text}</p>{m.reply?.detected_language && <small>Detected language: {m.reply.detected_language}</small>}{m.reply?.type === 'recommendation' && <div className="chat-response-card"><div className="severity-tag">Recommendation · {m.reply.how_urgent || 'review urgency'}</div><strong>{m.reply.what_happened}</strong><p>{m.reply.what_to_do}</p>{m.reply.confidence_pct !== undefined && <small>{m.reply.confidence_pct}% confidence</small>}{m.reply.why_it_matters && <details><summary>Why this recommendation</summary><p>{m.reply.why_it_matters}</p>{m.reply.evidence?.length ? <ul>{m.reply.evidence.map((item, i) => <li key={`${i}-${item}`}>{item}</li>)}</ul> : null}</details>}{m.reply.ask_an_expert && <Notice tone="error">Expert review recommended. {m.reply.escalation_reason}</Notice>}</div>}{m.reply?.audio_reply_base64 && <audio className="voice-reply" controls preload="none" aria-label="Aranya spoken reply" src={`data:audio/mpeg;base64,${m.reply.audio_reply_base64}`}/>}{m.reply?.type === 'history' && <div className="chat-response-card"><strong>{m.reply.scan_count ?? 0} recorded observation(s)</strong>{(m.reply.latest_status || m.reply.latest_risk_level) && <p>Latest status: {m.reply.latest_status || m.reply.latest_risk_level}</p>}{m.reply.latest_timestamp && <small>{m.reply.latest_timestamp}</small>}</div>}</div></article>)}{busy && <div className="chat-working" role="status"><span className="working-dot"/><span className="working-dot"/><span className="working-dot"/> Connecting to Aranya…</div>}</div>
      {error && <div className="chat-error"><Notice tone="error">{error} You can retry by sending the message again.</Notice></div>}
      <form className="chat-composer" onSubmit={(e) => void send(e)}><label className="attach-button" htmlFor="voice-note" title="Attach voice recording"><Paperclip size={17}/><span className="sr-only">Attach voice recording</span></label><input id="voice-note" type="file" accept="audio/*" capture hidden onChange={(e) => setAudio(e.target.files?.[0] || null)}/><div className="composer-input"><textarea aria-label="Message Aranya" rows={1} value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(); } }} placeholder="Ask about your farm…" disabled={!farmId || busy}/>{audio && <span className="audio-attachment"><Mic size={13}/>{audio.name}<button type="button" aria-label="Remove voice note" onClick={() => setAudio(null)}>×</button></span>}</div>{audio ? <button className="send-button" type="button" disabled={!farmId || busy} onClick={() => void sendVoice()} aria-label="Send voice note"><ArrowUp size={18}/></button> : <button className="send-button" type="submit" disabled={!farmId || !text.trim() || busy} aria-label="Send message"><ArrowUp size={18}/></button>}</form><div className="composer-footnote">Voice notes use Groq for transcription when configured. Aranya may reply with text if speech output is not configured.</div>
    </section>
  </div>;
}
