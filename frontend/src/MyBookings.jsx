import { useEffect, useId, useState } from 'react';
import {
  ArrowRight, CalendarDays, Check, CircleAlert, Clock3, Download,
  History, LoaderCircle, RefreshCw, Stethoscope, X,
} from 'lucide-react';
import { apiRequest } from './api.js';
import './my-bookings.css';

const euros = new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR' });

function parseDate(value) {
  const date = new Date(String(value || '').replace(' ', 'T'));
  return Number.isNaN(date.getTime()) ? null : date;
}

function dateLabel(value) {
  const date = parseDate(value);
  return date ? date.toLocaleDateString('it-IT', {
    weekday: 'short', day: 'numeric', month: 'long', year: 'numeric',
  }) : value || 'Data non disponibile';
}

function timeLabel(value) {
  const date = parseDate(value);
  return date ? date.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }) : '—';
}

function BookingItem({ booking, sessionId }) {
  const cancelled = booking.stato === 'annullata';
  const date = parseDate(booking.data_visita);
  const past = !cancelled && date !== null && date < new Date();
  const status = cancelled ? 'Annullata' : past ? 'Passata' : 'Confermata';
  const StatusIcon = cancelled ? X : past ? History : Check;
  const numericPrice = Number(booking.importo);

  return <li className={`mb-booking ${cancelled ? 'mb-booking-cancelled' : ''}`}>
    <div className="mb-booking-top"><span className="mb-reference">Prenotazione #{booking.prenotazione_id}</span><span className={`mb-status ${cancelled ? 'mb-status-cancelled' : past ? 'mb-status-past' : 'mb-status-confirmed'}`}><StatusIcon size={12} aria-hidden="true" />{status}</span></div>
    <div className="mb-booking-title"><span className="mb-specialty-icon"><Stethoscope size={19} aria-hidden="true" /></span><div><h3>{booking.specialita}</h3><p>{booking.tipo_visita}</p></div><span className="mb-price">{Number.isFinite(numericPrice) ? euros.format(numericPrice) : '—'}</span></div>
    <p className="mb-doctor">{booking.medico}</p>
    <div className="mb-appointment"><span><CalendarDays size={15} aria-hidden="true" /><time dateTime={String(booking.data_visita || '').replace(' ', 'T')}>{dateLabel(booking.data_visita)}</time></span><span><Clock3 size={15} aria-hidden="true" />{timeLabel(booking.data_visita)}</span></div>
    {booking.receipt_available && <a className="mb-download" href={`/api/sessions/${encodeURIComponent(sessionId)}/receipt/${encodeURIComponent(booking.prenotazione_id)}`} download={`ricevuta_${String(booking.prenotazione_id).padStart(3, '0')}.json`}><Download size={15} aria-hidden="true" />Scarica ricevuta JSON<ArrowRight size={14} aria-hidden="true" /></a>}
  </li>;
}

export default function MyBookings({ sessionId, initialView = 'all', onClose, onAsk }) {
  const titleId = useId();
  const [bookings, setBookings] = useState([]);
  const [loading, setLoading] = useState(Boolean(sessionId));
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState(initialView);

  useEffect(() => {
    const controller = new AbortController();
    setBookings([]);
    setError('');
    if (!sessionId) { setLoading(false); return () => controller.abort(); }
    setLoading(true);
    apiRequest(`/api/sessions/${encodeURIComponent(sessionId)}/bookings${view === 'future' ? '?scope=future' : ''}`, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setBookings(Array.isArray(data.bookings) ? data.bookings : []);
      })
      .catch((requestError) => {
        if (!controller.signal.aborted) setError(requestError.message || 'Non è stato possibile recuperare le prenotazioni.');
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [sessionId, attempt, view]);

  return <section className="mb-panel" aria-labelledby={titleId}>
    <header className="mb-header"><div><span className="mb-overline">Il tuo spazio</span><h2 id={titleId}>Le mie prenotazioni</h2></div><button type="button" className="mb-close" aria-label="Chiudi prenotazioni" onClick={onClose}><X size={20} /></button></header>
    <div className="mb-filters" role="group" aria-label="Filtra prenotazioni"><button type="button" aria-pressed={view === 'all'} onClick={() => setView('all')}>Tutte</button><button type="button" aria-pressed={view === 'future'} onClick={() => setView('future')}>In programma</button></div>
    <div className="mb-content" aria-live="polite" aria-busy={loading}>
      {loading ? <div className="mb-state" role="status"><LoaderCircle className="mb-spin" size={24} aria-hidden="true" /><p>Recupero le tue prenotazioni…</p></div> : error ? <div className="mb-state mb-error" role="alert"><CircleAlert size={25} aria-hidden="true" /><p>{error}</p><button type="button" className="mb-action" onClick={() => setAttempt((value) => value + 1)}><RefreshCw size={15} aria-hidden="true" />Riprova</button></div> : !sessionId ? <div className="mb-state"><CalendarDays size={28} aria-hidden="true" /><p>Accedi per consultare le tue prenotazioni.</p></div> : bookings.length === 0 ? <div className="mb-state mb-empty"><span className="mb-empty-icon"><CalendarDays size={27} aria-hidden="true" /></span><h3>{view === 'future' ? 'Nessuna visita in programma.' : 'Ancora nessuna visita.'}</h3><p>{view === 'future' ? 'Qui trovi le visite future confermate.' : 'Quando prenoti, ritrovi qui tutti i dettagli.'}</p>{onAsk && <button type="button" className="mb-action" onClick={() => onAsk('Vorrei prenotare una visita.')}>Chiedi una visita<ArrowRight size={15} aria-hidden="true" /></button>}</div> : <><p className="mb-count">{bookings.length} {bookings.length === 1 ? 'prenotazione' : 'prenotazioni'}</p><ul className="mb-list" aria-label="Elenco delle tue prenotazioni">{bookings.map((booking) => <BookingItem key={booking.prenotazione_id} booking={booking} sessionId={sessionId} />)}</ul></>}
    </div>
  </section>;
}
