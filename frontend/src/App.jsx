import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ArrowDown, ArrowUp, BookOpen, CalendarDays, Check,
  Euro, FileText, Fingerprint, Heart,
  LoaderCircle, LogOut, Menu, MessageCircle, Plus, RefreshCw,
  ShieldCheck, Stethoscope, Wallet, X,
} from 'lucide-react';
import { apiRequest, apiStreamRequest } from './api.js';
import { BookingCard, ReceiptCard } from './BookingWidgets.jsx';
import MyBookings from './MyBookings.jsx';
import { CopyButton, ProfileInfo } from './ChatInteractions.jsx';

const SESSION_KEY = 'salus-session';
const uid = () => crypto.randomUUID();

// A browser refresh can happen while Ollama is answering. Poll the read-only
// snapshot until the existing operation finishes; never repeat its POST.
async function waitForSnapshot(id, signal) {
  for (;;) {
    try { return await apiRequest(`/api/sessions/${id}`, { signal }); }
    catch (error) {
      if (error.status !== 409 || signal?.aborted) throw error;
      await new Promise((resolve, reject) => {
        const cancel = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
        const timer = setTimeout(() => { signal?.removeEventListener('abort', cancel); resolve(); }, 1200);
        signal?.addEventListener('abort', cancel, { once: true });
      });
    }
  }
}
const quickQuestions = [
  { icon: CalendarDays, title: 'Prenota una visita', text: 'Vorrei prenotare una prima visita.' },
  { icon: Stethoscope, title: 'Medici disponibili', text: 'Quali medici ci sono per Cardiologia?' },
  { icon: Euro, title: 'Tariffe delle visite', text: 'Quali sono le tariffe delle prime visite e dei controlli?' },
  { icon: FileText, title: 'Documenti necessari', text: 'Quali documenti devo portare per una visita?' },
  { icon: Wallet, title: 'Pagamenti e referti', text: 'Come posso pagare e dove trovo i miei referti?' },
];

function Mark({ small = false }) {
  return <span className={`brand-mark ${small ? 'brand-mark-small' : ''}`} aria-hidden="true"><Plus strokeWidth={2.4} /><span className="brand-seed" /></span>;
}

function Modal({ children, open, onClose, label, wide = false, closeDisabled = false }) {
  const dialog = useRef(null);
  useEffect(() => {
    const node = dialog.current;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);
  return <dialog ref={dialog} className={`modal ${wide ? 'modal-wide' : ''}`} aria-label={label}
    onCancel={(event) => { event.preventDefault(); if (!closeDisabled) onClose(); }}
    onClick={(event) => { if (event.target === event.currentTarget && !closeDisabled) onClose(); }}>
    <div className="modal-inner">
      {!wide && <button type="button" className="icon-button modal-close" aria-label="Chiudi finestra" onClick={onClose} disabled={closeDisabled}><X size={20} /></button>}
      {children}
    </div>
  </dialog>;
}

function LoginForm({ busy, error, onSubmit }) {
  const [code, setCode] = useState('');
  const [validation, setValidation] = useState('');
  return <div className="login-content">
    <h2>Accedi</h2>
    <p>Inserisci il tuo codice fiscale.</p>
    <form onSubmit={(event) => {
      event.preventDefault();
      if (!/^[A-Z0-9]{16}$/.test(code.trim().toUpperCase())) { setValidation('Inserisci un codice fiscale di 16 lettere e numeri.'); return; }
      setValidation(''); onSubmit(code.trim().toUpperCase());
    }}>
      <label htmlFor="fiscal-code">Codice fiscale</label>
      <div className={`login-input ${validation || error ? 'input-error' : ''}`}><Fingerprint size={18} /><input id="fiscal-code" name="codice_fiscale" value={code} onChange={(event) => setCode(event.target.value.toUpperCase())} autoComplete="off" autoCapitalize="characters" spellCheck={false} maxLength={16} placeholder="16 lettere e numeri" required disabled={busy} aria-describedby={validation || error ? 'login-error' : 'login-help'} aria-invalid={!!(validation || error)} /></div>
      {(validation || error) && <p className="field-error" id="login-error" role="alert">{validation || error}</p>}
      <p className="field-hint" id="login-help">Usa il codice registrato in accettazione.</p>
      <button className="button button-primary login-submit" disabled={busy}>{busy ? <><LoaderCircle className="spin" size={16} /> Accesso in corso…</> : 'Accedi'}</button>
    </form>
    <p className="login-note">Il codice fiscale identifica l’anagrafica, non verifica l’identità.</p>
    <details className="demo-access"><summary>Stai provando il progetto?</summary><p>Il database contiene pazienti di fantasia.</p><button type="button" onClick={() => { setCode('RSSMRA90A01H501X'); setValidation(''); }} disabled={busy}>Usa Mario Rossi</button></details>
  </div>;
}

function Message({ message, onCopy }) {
  if (message.role === 'user') return <div className="message-row message-row-user"><div className="user-bubble">{message.content}</div></div>;
  return <article className="message-row assistant-message">
    <Mark small />
    <div className="assistant-content"><div className="message-author">Salus <span>· Assistente</span></div>
      <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ children, href }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a> }}>{message.content}</ReactMarkdown></div>
      <CopyButton text={message.content} onCopy={onCopy} />
    </div>
  </article>;
}

function Welcome({ onAsk, disabled }) {
  return <section className="welcome">
    <h1>Come posso aiutarti?</h1>
    <div className="suggestions" aria-label="Domande suggerite">{quickQuestions.map(({ icon: Icon, title, text }) => <button key={title} onClick={() => onAsk(text)} disabled={disabled}><Icon size={16} strokeWidth={1.6} />{title}</button>)}</div>
  </section>;
}

export default function App() {
  const [session, setSession] = useState(null);
  const [messages, setMessages] = useState([]);
  const [pending, setPending] = useState(null);
  const [receipts, setReceipts] = useState([]);
  const [receiptAnchors, setReceiptAnchors] = useState({});
  const [health, setHealth] = useState(null);
  const [healthLoading, setHealthLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [booting, setBooting] = useState(true);
  const [error, setError] = useState('');
  const [input, setInput] = useState('');
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [nextAction, setNextAction] = useState(null);
  const [bookingsOpen, setBookingsOpen] = useState(false);
  const [bookingsView, setBookingsView] = useState('all');
  const [endAction, setEndAction] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [toast, setToast] = useState('');
  const [showScroll, setShowScroll] = useState(false);
  const [progress, setProgress] = useState('');
  const busyRef = useRef(false);
  const scroller = useRef(null);
  const textarea = useRef(null);
  const shouldFollow = useRef(true);
  const mounted = useRef(true);
  const toastTimer = useRef(null);
  const sidebarRef = useRef(null);
  const lifetime = useRef(null);

  const notify = useCallback((text) => { setToast(text); clearTimeout(toastTimer.current); toastTimer.current = setTimeout(() => setToast(''), 4000); }, []);
  const refreshHealth = useCallback(async () => {
    setHealthLoading(true);
    try { setHealth(await apiRequest('/api/health')); }
    catch { setHealth({ status: 'unavailable', ai_ready: false, disconnected: true }); }
    finally { setHealthLoading(false); }
  }, []);

  const applySnapshot = useCallback((data) => {
    setSession({ session_id: data.session_id, patient: data.patient, preferences: data.preferences });
    setMessages(data.messages || []); setPending(data.pending || null);
    setReceipts(data.receipts || (data.receipt ? [data.receipt] : []));
    setReceiptAnchors(data.receipt_anchors || {});
  }, []);

  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    lifetime.current = controller;
    refreshHealth();
    const saved = sessionStorage.getItem(SESSION_KEY);
    if (saved) {
      waitForSnapshot(saved, controller.signal).then((data) => { if (mounted.current) applySnapshot(data); }).catch((e) => {
        if (e.name === 'AbortError') return;
        if (e.status === 404) sessionStorage.removeItem(SESSION_KEY);
        else setError('Non è stato possibile recuperare la conversazione. Riprova il collegamento prima di iniziarne una nuova.');
      }).finally(() => { if (mounted.current) setBooting(false); });
    } else setBooting(false);
    const interval = setInterval(refreshHealth, 45000);
    const online = () => refreshHealth();
    window.addEventListener('online', online);
    const offline = () => setHealth({ status: 'unavailable', ai_ready: false, disconnected: true });
    window.addEventListener('offline', offline);
    return () => { mounted.current = false; controller.abort(); clearInterval(interval); clearTimeout(toastTimer.current); window.removeEventListener('online', online); window.removeEventListener('offline', offline); };
  }, [refreshHealth, applySnapshot]);

  useEffect(() => {
    const drawer = sidebarRef.current;
    if (menuOpen && !drawer.open) drawer.showModal();
    if (!menuOpen && drawer.open) drawer.close();
  }, [menuOpen]);
  useEffect(() => {
    const viewport = window.visualViewport;
    const resize = () => document.documentElement.style.setProperty('--app-height', `${viewport ? viewport.height : window.innerHeight}px`);
    resize(); viewport?.addEventListener('resize', resize); window.addEventListener('resize', resize);
    return () => { viewport?.removeEventListener('resize', resize); window.removeEventListener('resize', resize); };
  }, []);
  const resizeComposer = useCallback(() => {
    const field = textarea.current;
    if (!field) return;
    field.style.height = '0px';
    field.style.height = `${Math.min(160, Math.max(40, field.scrollHeight))}px`;
  }, []);
  useLayoutEffect(resizeComposer, [input, resizeComposer]);
  useEffect(() => {
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(resizeComposer);
    if (textarea.current?.parentElement) observer?.observe(textarea.current.parentElement);
    window.addEventListener('resize', resizeComposer);
    return () => { observer?.disconnect(); window.removeEventListener('resize', resizeComposer); };
  }, [resizeComposer]);
  useLayoutEffect(() => { if (shouldFollow.current && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight; }, [messages, pending, receipts, busy, progress]);

  function askLogin(action = null) { setNextAction(action); setLoginError(''); setLoginOpen(true); setMenuOpen(false); }
  function showBookings(view = 'all') {
    setMenuOpen(false);
    setBookingsView(view);
    if (!session) { askLogin({ type: 'bookings', view }); return; }
    setBookingsOpen(true);
  }

  function consumeResult(data) {
    setMessages((previous) => [...previous, ...(data.messages || []).filter((msg) => !previous.some((old) => old.id === msg.id))]);
    setPending(data.pending || null);
    if (data.receipt) setReceipts((previous) => previous.some((r) => r.prenotazione_id === data.receipt.prenotazione_id) ? previous : [...previous, data.receipt]);
    if (data.receipt && (data.receipt_anchor || data.messages?.at(-1)?.id)) {
      setReceiptAnchors((previous) => ({ ...previous, [data.receipt.prenotazione_id]: data.receipt_anchor || data.messages.at(-1).id }));
    }
    setSession((previous) => previous ? { ...previous, preferences: data.preferences ?? previous.preferences } : previous);
  }

  async function recoverState(id) {
    try {
      const data = await waitForSnapshot(id, lifetime.current?.signal);
      applySnapshot(data);
      return true;
    } catch (e) {
      if (e.status === 404) {
        sessionStorage.removeItem(SESSION_KEY); setSession(null); setPending(null);
        setError('La sessione è terminata. Accedi di nuovo per continuare.');
      }
      return false;
    }
  }

  async function sendMessage(text, activeSession = session) {
    text = text.trim();
    if (!text || busyRef.current || pending) return;
    if (text === '/prenotazioni') {
      setInput('');
      setBookingsView('future');
      if (!activeSession) askLogin({ type: 'bookings', view: 'future' });
      else setBookingsOpen(true);
      return;
    }
    if (!activeSession) { askLogin({ type: 'message', text }); return; }
    if (text === '/esci' || text === '/fine') { setEndAction('logout'); return; }
    busyRef.current = true; setBusy(true); setProgress(''); setError(''); setInput(''); shouldFollow.current = true;
    setMessages((previous) => [...previous, { id: uid(), role: 'user', content: text }]);
    try { consumeResult(await apiStreamRequest(`/api/sessions/${activeSession.session_id}/messages/stream`, { method: 'POST', body: JSON.stringify({ message: text }) }, setProgress)); }
    catch (e) { setError(e.message); await recoverState(activeSession.session_id); }
    finally { busyRef.current = false; setBusy(false); setProgress(''); textarea.current?.focus(); }
  }

  async function confirmBooking(answer) {
    if (busyRef.current || !pending || !session) return;
    busyRef.current = true; setBusy(true); setProgress(''); setError(''); shouldFollow.current = true;
    setMessages((previous) => [...previous, { id: uid(), role: 'user', content: answer }]);
    try { consumeResult(await apiStreamRequest(`/api/sessions/${session.session_id}/confirm/stream`, { method: 'POST', body: JSON.stringify({ answer }) }, setProgress)); }
    catch (e) { setError(e.message); await recoverState(session.session_id); }
    finally { busyRef.current = false; setBusy(false); setProgress(''); }
  }

  async function signIn(code) {
    if (loginBusy) return;
    setLoginBusy(true); setLoginError('');
    try {
      const data = await apiRequest('/api/sessions', { method: 'POST', body: JSON.stringify({ codice_fiscale: code }) });
      setSession(data); sessionStorage.setItem(SESSION_KEY, data.session_id);
      setMessages([]); setReceipts([]); setReceiptAnchors({}); setPending(null); setError(''); setLoginOpen(false);
      const action = nextAction; setNextAction(null);
      if (action?.type === 'message') await sendMessage(action.text, data);
      else if (action?.type === 'bookings') { setBookingsView(action.view || 'all'); setBookingsOpen(true); }
      else textarea.current?.focus();
    } catch (e) { setLoginError(e.message); }
    finally { setLoginBusy(false); }
  }

  async function endConversation() {
    if (!session || busyRef.current) return;
    busyRef.current = true; setBusy(true); setError('');
    const oldSession = session; const action = endAction;
    try {
      await apiRequest(`/api/sessions/${session.session_id}`, { method: 'DELETE' });
      sessionStorage.removeItem(SESSION_KEY); setSession(null); setMessages([]); setPending(null); setReceipts([]); setReceiptAnchors({}); setInput(''); setEndAction(null);
      if (action === 'new') {
        const data = await apiRequest('/api/sessions', { method: 'POST', body: JSON.stringify({ codice_fiscale: oldSession.patient.codice_fiscale }) });
        setSession(data); sessionStorage.setItem(SESSION_KEY, data.session_id); notify('Una nuova conversazione, con le tue preferenze.');
      } else notify('Conversazione terminata. A presto!');
    } catch (e) { setEndAction(null); setError(e.message); }
    finally { busyRef.current = false; setBusy(false); }
  }

  async function copyMessage(text) {
    try { await navigator.clipboard.writeText(text); return true; }
    catch { notify('Copia non disponibile. Puoi selezionare il testo della risposta.'); return false; }
  }

  async function reconnect() {
    setError(''); await refreshHealth();
    const id = session?.session_id || sessionStorage.getItem(SESSION_KEY);
    if (id) await recoverState(id);
  }

  const locked = busy || booting;
  const patient = session?.patient;

  return <div className="app-shell">
    <a className="skip-link" href="#message-input">Vai al campo messaggio</a>
    <dialog id="main-sidebar" ref={sidebarRef} className="sidebar-dialog" aria-label="Navigazione principale"
      onCancel={(event) => { event.preventDefault(); setMenuOpen(false); }}
      onClick={(event) => { if (event.target === event.currentTarget) setMenuOpen(false); }}>
      <aside className="sidebar">
        <div className="sidebar-header">
          <a href="#" className="brand" onClick={(event) => { event.preventDefault(); setMenuOpen(false); }} aria-label="Salus Levante, assistente"><Mark /><span>salus levante<small>POLIAMBULATORIO</small></span></a>
          <button className="icon-button" aria-label="Chiudi menu" onClick={() => setMenuOpen(false)}><X size={19} /></button>
        </div>
        <nav className="main-nav" aria-label="Il tuo spazio">
          <button className="nav-item nav-active" aria-current="page" onClick={() => setMenuOpen(false)}><MessageCircle size={19} /><span>Il tuo assistente</span><span className="nav-active-dot" /></button>
          <button className="nav-item" onClick={() => { setMenuOpen(false); if (session) setEndAction('new'); else { setInput(''); textarea.current?.focus(); } }} disabled={locked}><Plus size={19} /><span>Nuova conversazione</span></button>
          <button className="nav-item" onClick={() => showBookings()} disabled={booting}><CalendarDays size={19} /><span>Le mie prenotazioni</span></button>
          <a className="nav-item" href="/api/services-document" target="_blank" rel="noopener noreferrer"><BookOpen size={19} /><span>Carta dei servizi</span><ArrowUp size={14} className="external-arrow" /></a>
        </nav>
        <div className="sidebar-middle">
          {session?.preferences && <section className="preferences-card" aria-label="Le tue preferenze"><div className="preferences-heading"><Heart size={15} /><h2>Le tue preferenze</h2></div><dl><div><dt>Medico</dt><dd>{session.preferences.medico}</dd></div><div><dt>Fascia oraria</dt><dd>{session.preferences.fascia}</dd></div></dl><p>Dall’ultima prenotazione.</p></section>}
        </div>
        <div className="sidebar-bottom">
          <div className="human-help"><span className="human-help-icon"><MessageCircle size={18} strokeWidth={1.6} /></span><div><strong>Parliamone di persona</strong><p>Per un aiuto, rivolgiti all’accettazione.</p></div></div>
          {patient ? <div className="patient-profile"><ProfileInfo key={patient.codice_fiscale} patient={patient} /><button className="icon-button" aria-label="Esci dalla sessione" title="Esci dalla sessione" onClick={() => { setEndAction('logout'); setMenuOpen(false); }} disabled={locked}><LogOut size={18} /></button></div> : <button className="sidebar-login" onClick={() => askLogin()} disabled={locked}><Fingerprint size={19} /><span>Accedi</span></button>}
        </div>
      </aside>
    </dialog>

    <div className="workspace">
      <button className="icon-button menu-toggle floating-menu" aria-label="Apri menu" aria-expanded={menuOpen} aria-controls="main-sidebar" onClick={() => setMenuOpen(true)}><Menu size={22} /></button>
      <div className="floating-account">
        <span className={`service-status ${health?.ai_ready ? 'status-ready' : 'status-offline'}`} role="status"><span />{health?.ai_ready ? 'Online' : 'Offline'}</span>
        {patient ? <ProfileInfo key={patient.codice_fiscale} patient={patient} compact /> : <button className="login-button" onClick={() => askLogin()} disabled={locked}>Accedi</button>}
      </div>
      <main className={`chat-column ${messages.length === 0 && !pending && !booting ? 'is-empty' : ''}`} aria-label="Assistente Salus">
        {health && !health.ai_ready && <div className="connection-banner" role="status"><span>Assistente offline. Le tue prenotazioni e la Carta dei Servizi restano disponibili.</span><button onClick={reconnect} disabled={busy || healthLoading}><RefreshCw size={14} className={healthLoading ? 'spin' : ''} />Ricollega</button></div>}
        <div ref={scroller} className="chat-scroll" onScroll={(event) => { const el = event.currentTarget; const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100; shouldFollow.current = nearBottom; setShowScroll(!nearBottom); }}>
          {booting ? <div className="boot-state" role="status"><LoaderCircle className="spin" /> Recupero la tua conversazione…</div> : <>
            {messages.length === 0 && !pending ? <Welcome onAsk={sendMessage} disabled={locked} /> : <div className="conversation">
              <div className="message-log" role="log" aria-label="Messaggi della conversazione" aria-live="polite" aria-relevant="additions text">{messages.map((message) => <Fragment key={message.id}><Message message={message} onCopy={copyMessage} />{receipts.filter((receipt) => receiptAnchors[receipt.prenotazione_id] === message.id).map((receipt) => <div className="inline-receipt" key={receipt.prenotazione_id}><ReceiptCard receipt={receipt} sessionId={session?.session_id} /></div>)}</Fragment>)}</div>
            </div>}
            {(pending || receipts.some((receipt) => !receiptAnchors[receipt.prenotazione_id])) && <div className="booking-results" aria-live="polite">{receipts.filter((receipt) => !receiptAnchors[receipt.prenotazione_id]).map((receipt) => <ReceiptCard key={receipt.prenotazione_id} receipt={receipt} sessionId={session?.session_id} />)}{pending && <BookingCard pending={pending} busy={busy} onConfirm={confirmBooking} />}</div>}
            {busy && <div className="thinking" role="status"><Mark small /><span><i /><i /><i /></span><span>{progress || (pending ? 'Completo la tua richiesta…' : 'Un momento, sto verificando…')}</span></div>}
          </>}
        </div>
        <div className="composer-area">
          {showScroll && <button className="scroll-bottom" aria-label="Vai agli ultimi messaggi" onClick={() => { shouldFollow.current = true; scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }); }}><ArrowDown size={18} /></button>}
          {error && <div className="error-banner" role="alert"><span>{error}</span><button className="icon-button" onClick={reconnect} aria-label="Ricollega e recupera la conversazione" disabled={busy}><RefreshCw size={17} /></button><button className="icon-button" onClick={() => setError('')} aria-label="Chiudi avviso"><X size={17} /></button></div>}
          {pending && <p className="pending-hint"><ShieldCheck size={15} />Controlla il riepilogo e scegli se confermare.</p>}
          <form className={`composer ${locked || pending ? 'composer-disabled' : ''}`} onSubmit={(event) => { event.preventDefault(); sendMessage(input); }}>
            <label className="sr-only" htmlFor="message-input">Scrivi a Salus</label>
            <textarea ref={textarea} id="message-input" rows={1} value={input} onChange={(event) => setInput(event.target.value)} placeholder={pending ? 'In attesa della tua conferma…' : 'Scrivi a Salus'} disabled={locked || !!pending} maxLength={5000} enterKeyHint="send" onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); sendMessage(input); } }} />
            <div className="composer-actions"><button type="submit" className="send-button" aria-label="Invia messaggio" disabled={!input.trim() || locked || !!pending}>{busy ? <LoaderCircle size={20} className="spin" /> : <ArrowUp size={21} />}</button></div>
          </form>
          <p className="medical-note"><ShieldCheck size={12} aria-hidden="true" /><span>Salus non dà consigli medici. <span className="emergency-note">Emergenze: <strong>112</strong>.</span></span></p>
        </div>
      </main>
    </div>

    <Modal open={loginOpen} onClose={() => { setLoginOpen(false); setNextAction(null); }} label="Accesso paziente" closeDisabled={loginBusy}><LoginForm key={loginOpen ? 'open' : 'closed'} busy={loginBusy} error={loginError} onSubmit={signIn} /></Modal>
    <Modal open={bookingsOpen && !!session} onClose={() => setBookingsOpen(false)} label="Le mie prenotazioni" wide>
      {bookingsOpen && session && <MyBookings sessionId={session.session_id} initialView={bookingsView} onClose={() => setBookingsOpen(false)} onAsk={(text) => { setBookingsOpen(false); if (pending) { setError('Conferma o rifiuta prima la visita in sospeso.'); return; } sendMessage(text); }} />}
    </Modal>
    <Modal open={!!endAction} onClose={() => setEndAction(null)} label={endAction === 'new' ? 'Nuova conversazione' : 'Termina conversazione'} closeDisabled={busy}>
      <div className="end-session">
        <h2>{endAction === 'new' ? 'Iniziare una nuova chat?' : 'Uscire dalla chat?'}</h2>
        <p>Se non hai completato la prenotazione, le informazioni andranno perse.</p>
        <div className="dialog-actions"><button className="button button-secondary" onClick={() => setEndAction(null)} disabled={busy}>Annulla</button><button className="button button-primary" onClick={endConversation} disabled={busy}>{busy && <LoaderCircle size={16} className="spin" />}{endAction === 'new' ? 'Nuova chat' : 'Esci'}</button></div>
      </div>
    </Modal>
    {toast && <div className="toast" role="status"><Check size={16} />{toast}</div>}
  </div>;
}
