import { useEffect, useId, useRef, useState } from 'react';
import {
  ArrowRight, CalendarDays, Check, CheckCircle2, ChevronDown, CircleAlert,
  Clock3, Download, FileText, LoaderCircle, Search, ShieldCheck, Star,
  Stethoscope, UserRound, X,
} from 'lucide-react';
import { apiRequest } from './api.js';
import './booking-widgets.css';

const euro = new Intl.NumberFormat('it-IT', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 });

function localDate(offset = 0) {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

function readDate(value) {
  if (!value) return null;
  const text = String(value);
  const european = text.match(/^(\d{2})-(\d{2})-(\d{4})(.*)$/);
  const normalized = european ? `${european[3]}-${european[2]}-${european[1]}${european[4]}` : text;
  const date = new Date(normalized.replace(' ', 'T'));
  return Number.isNaN(date.getTime()) ? null : date;
}

function readableDate(value, includeYear = false) {
  const date = readDate(value);
  return date ? date.toLocaleDateString('it-IT', {
    weekday: 'long', day: 'numeric', month: 'long', ...(includeYear ? { year: 'numeric' } : {}),
  }) : value || '—';
}

function readableTime(value) {
  const date = readDate(value);
  return date ? date.toLocaleTimeString('it-IT', { hour: '2-digit', minute: '2-digit' }) : '—';
}

function price(value) {
  return value !== null && value !== undefined && Number.isFinite(Number(value)) ? euro.format(Number(value)) : '—';
}

function Preparation({ value, source }) {
  const instructions = Array.isArray(value) ? value : value ? [String(value)] : [];
  if (!instructions.length) return null;
  return (
    <div className="bw-preparation">
      <div className="bw-preparation-heading"><FileText size={16} aria-hidden="true" /><span>Prima della visita</span></div>
      <ul>{instructions.map((instruction, index) => <li key={`${index}-${instruction}`}>{instruction}</li>)}</ul>
      {source && <p className="bw-source">Fonte: {source}</p>}
    </div>
  );
}

export function AvailabilityPanel({ specialties = [], preferences, busy = false, onChoose, onClose }) {
  const fieldId = useId();
  const [specialty, setSpecialty] = useState(specialties[0]?.nome || '');
  const [date, setDate] = useState(() => localDate(1));
  const [visitType, setVisitType] = useState('prima');
  const [slots, setSlots] = useState(null);
  const [searchedDate, setSearchedDate] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const requestRef = useRef(null);
  const selectedSpecialty = specialties.find(item => item.nome === specialty);
  const disabled = busy || loading;

  useEffect(() => {
    if (!specialty && specialties.length) setSpecialty(specialties[0].nome);
  }, [specialties, specialty]);

  useEffect(() => () => requestRef.current?.abort(), []);

  function resetResults() {
    setSlots(null);
    setError('');
  }

  async function search(event) {
    event.preventDefault();
    if (!specialty || !date || disabled) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError('');
    setSlots(null);
    try {
      const params = new URLSearchParams({ specialita: specialty, data: date });
      const response = await apiRequest(`/api/slots?${params}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setSlots(Array.isArray(response.slots) ? response.slots : []);
      setSearchedDate(date);
    } catch (requestError) {
      if (!controller.signal.aborted) setError(requestError.message || 'Non è stato possibile cercare gli orari. Riprova tra poco.');
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return (
    <section className="bw-panel" aria-labelledby={`${fieldId}-title`}>
      <div className="bw-panel-header">
        <div className="bw-heading-icon"><CalendarDays size={20} aria-hidden="true" /></div>
        <div className="bw-panel-heading"><p className="bw-eyebrow">Trova il tuo appuntamento</p><h2 id={`${fieldId}-title`}>Uno spazio per la tua salute.</h2></div>
        {onClose && <button type="button" className="bw-icon-button" onClick={onClose} aria-label="Chiudi ricerca appuntamenti"><X size={19} /></button>}
      </div>

      <form className="bw-search-form" onSubmit={search}>
        <div className="bw-field">
          <label htmlFor={`${fieldId}-specialty`}>Specialità</label>
          <div className="bw-select-wrap"><Stethoscope size={17} className="bw-input-icon" aria-hidden="true" />
            <select id={`${fieldId}-specialty`} value={specialty} disabled={disabled || !specialties.length} onChange={event => { setSpecialty(event.target.value); resetResults(); }} required>
              {!specialties.length && <option value="">Caricamento specialità…</option>}
              {specialties.map(item => <option key={item.id ?? item.nome} value={item.nome}>{item.nome}</option>)}
            </select><ChevronDown size={15} className="bw-select-chevron" aria-hidden="true" />
          </div>
        </div>

        <fieldset className="bw-visit-field"><legend>Tipo di visita</legend><div className="bw-visit-types">
          {[['prima', 'Prima visita'], ['controllo', 'Controllo']].map(([value, label]) => (
            <label key={value} className={`bw-visit-option ${visitType === value ? 'bw-selected' : ''}`}>
              <input type="radio" name={`${fieldId}-visit`} value={value} checked={visitType === value} disabled={disabled} onChange={() => setVisitType(value)} />
              <span className="bw-radio-mark" aria-hidden="true">{visitType === value && <Check size={11} strokeWidth={3} />}</span><span>{label}</span>
              <span className="bw-visit-price">{price(value === 'prima' ? selectedSpecialty?.costo_prima_visita : selectedSpecialty?.costo_controllo)}</span>
            </label>
          ))}
        </div></fieldset>

        <div className="bw-date-search"><div className="bw-field">
          <label htmlFor={`${fieldId}-date`}>Quando vorresti venire?</label>
          <input id={`${fieldId}-date`} type="date" value={date} min={localDate()} required disabled={disabled} onChange={event => { setDate(event.target.value); resetResults(); }} />
        </div><button className="bw-button bw-button-primary bw-search-button" type="submit" disabled={disabled || !specialty || !date}>
          {loading ? <LoaderCircle size={17} className="bw-spin" aria-hidden="true" /> : <Search size={17} aria-hidden="true" />}<span>{loading ? 'Cerco…' : 'Cerca orari'}</span>
        </button></div>
      </form>

      {error && <p className="bw-error" role="alert"><CircleAlert size={17} aria-hidden="true" /><span>{error}</span></p>}
      <div className="bw-search-results" aria-live="polite" aria-busy={loading}>
        {loading && <div className="bw-search-wait"><LoaderCircle size={20} className="bw-spin" aria-hidden="true" /><span>Controllo gli orari disponibili…</span></div>}
        {slots !== null && !loading && <>
          <div className="bw-results-heading"><h3>{readableDate(`${searchedDate}T12:00:00`)}</h3><span>{slots.length} {slots.length === 1 ? 'orario disponibile' : 'orari disponibili'}</span></div>
          {slots.length === 0 ? <div className="bw-empty"><CalendarDays size={25} aria-hidden="true" /><p>Nessun appuntamento disponibile.</p><span>Prova un’altra data per questa specialità.</span></div> : <div className="bw-slot-list">{slots.map(slot => {
            const slotDate = readDate(slot.data_ora);
            const preferredDoctor = Boolean(preferences?.medico && slot.medico === preferences.medico);
            const preferredTime = Boolean(slotDate && preferences?.fascia && (slotDate.getHours() < 13 ? 'mattina' : 'pomeriggio') === preferences.fascia);
            return <button key={slot.slot_id} type="button" className={`bw-slot ${preferredDoctor || preferredTime ? 'bw-slot-preferred' : ''}`} disabled={disabled} onClick={() => onChoose?.({ slot, tipo_visita: visitType })} aria-label={`Scegli le ${readableTime(slot.data_ora)} con ${slot.medico}, ${visitType === 'prima' ? 'prima visita' : 'controllo'}`}>
              <span className="bw-slot-time">{readableTime(slot.data_ora)}<span>Slot {slot.slot_id}</span></span>
              <span className="bw-slot-info"><strong>{slot.medico}</strong><span>{slot.specialita || specialty}</span>{(preferredDoctor || preferredTime) && <span className="bw-preferred-label"><Star size={10} aria-hidden="true" />{[preferredDoctor && 'Medico preferito', preferredTime && 'Fascia preferita'].filter(Boolean).join(' · ')}</span>}</span>
              <span className="bw-slot-arrow" aria-hidden="true"><ArrowRight size={17} /></span>
            </button>;
          })}</div>}
        </>}
      </div>
      <div className="bw-panel-footnote"><ShieldCheck size={14} aria-hidden="true" /><span>Potrai controllare tutti i dettagli prima di confermare.</span></div>
    </section>
  );
}

export function BookingCard({ pending, busy = false, onConfirm }) {
  const titleId = useId();
  if (!pending?.summary) return null;
  const summary = pending.summary;
  return (
    <section className="bw-booking-card" aria-labelledby={titleId} aria-busy={busy}>
      <div className="bw-card-overline"><span className="bw-status-dot" />{busy ? 'Elaboro la tua scelta…' : 'In attesa della tua conferma'}</div>
      <h3 id={titleId}>È tutto pronto.<br />Controlliamo i dettagli?</h3>
      <div className="bw-booking-specialty"><span className="bw-heading-icon"><Stethoscope size={21} aria-hidden="true" /></span><div><strong>{summary.specialita}</strong><span>{summary.tipo_visita}</span></div><strong className="bw-total">{price(summary.importo_euro)}</strong></div>
      <dl className="bw-details">
        <div><dt><UserRound size={15} aria-hidden="true" />Paziente</dt><dd>{summary.paziente}</dd></div>
        <div><dt><Stethoscope size={15} aria-hidden="true" />Medico</dt><dd>{summary.medico}</dd></div>
        <div><dt><CalendarDays size={15} aria-hidden="true" />Data</dt><dd>{readableDate(summary.data_visita, true)}</dd></div>
        <div><dt><Clock3 size={15} aria-hidden="true" />Orario</dt><dd>{readableTime(summary.data_visita)}</dd></div>
      </dl>
      <Preparation value={summary.preparazione} />
      <p className="bw-confirm-note"><ShieldCheck size={16} aria-hidden="true" />La visita verrà registrata solo dopo la tua conferma.</p>
      <div className="bw-confirm-actions"><button type="button" className="bw-button bw-button-primary" disabled={busy} onClick={() => onConfirm?.('si')}>{busy ? <LoaderCircle size={17} className="bw-spin" aria-hidden="true" /> : <Check size={17} aria-hidden="true" />}Conferma prenotazione</button><button type="button" className="bw-button bw-button-secondary" disabled={busy} onClick={() => onConfirm?.('no')}>Non confermare</button></div>
    </section>
  );
}

export function ReceiptCard({ receipt, sessionId }) {
  const titleId = useId();
  if (!receipt) return null;
  const bookingId = receipt.prenotazione_id;
  return (
    <section className="bw-receipt-card" aria-labelledby={titleId}>
      <div className="bw-receipt-header"><span className="bw-success-icon"><CheckCircle2 size={24} aria-hidden="true" /></span><div><p className="bw-eyebrow">Prenotazione confermata</p><h3 id={titleId}>Ci vediamo presto.</h3></div></div>
      <div className="bw-receipt-reference"><span>Ricevuta di prenotazione</span><strong>N° {String(bookingId).padStart(3, '0')}</strong></div>
      <div className="bw-booking-specialty"><span className="bw-heading-icon"><Stethoscope size={20} aria-hidden="true" /></span><div><strong>{receipt.specialita}</strong><span>{receipt.tipo_visita}</span></div><strong className="bw-total">{price(receipt.importo)}</strong></div>
      <dl className="bw-details bw-receipt-details"><div><dt>Medico</dt><dd>{receipt.medico}</dd></div><div><dt>Data</dt><dd>{readableDate(receipt.data_visita, true)}</dd></div><div><dt>Orario</dt><dd>{readableTime(receipt.data_visita)}</dd></div></dl>
      <Preparation value={receipt.preparazione} source={receipt.fonte_preparazione} />
      {sessionId && bookingId !== undefined && <a className="bw-button bw-download" href={`/api/sessions/${encodeURIComponent(sessionId)}/receipt/${encodeURIComponent(bookingId)}`} download={`ricevuta_${String(bookingId).padStart(3, '0')}.json`}><Download size={17} aria-hidden="true" /><span>Scarica ricevuta <span className="bw-file-type">JSON</span></span><ArrowRight size={16} aria-hidden="true" /></a>}
    </section>
  );
}
