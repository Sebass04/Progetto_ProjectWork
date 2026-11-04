import { useEffect, useId, useRef, useState } from 'react';
import { Check, Copy } from 'lucide-react';
import './chat-interactions.css';

export function CopyButton({ text, onCopy }) {
  const [copied, setCopied] = useState(false);
  const [copying, setCopying] = useState(false);
  const [animation, setAnimation] = useState(0);
  const pending = useRef(false);
  const timer = useRef(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; clearTimeout(timer.current); };
  }, []);

  async function copy() {
    if (pending.current) return;
    pending.current = true;
    clearTimeout(timer.current);
    setCopied(false);
    setCopying(true);
    try {
      const succeeded = await onCopy(text);
      if (!mounted.current || succeeded !== true) return;
      clearTimeout(timer.current);
      setCopied(true);
      setAnimation((value) => value + 1);
      timer.current = setTimeout(() => {
        if (mounted.current) setCopied(false);
      }, 2000);
    } catch {
      // The caller owns error feedback. Never show a check if copying failed.
    } finally {
      pending.current = false;
      if (mounted.current) setCopying(false);
    }
  }

  return <div className="ci-copy-control">
    <button type="button" className={`copy-button ci-copy-button ${copied ? 'ci-copy-success' : ''}`} onClick={copy} disabled={copying} aria-label={copied ? 'Risposta copiata' : 'Copia la risposta'}>
      <span key={animation} className={`ci-copy-icon ${copied ? 'ci-copy-icon-success' : ''}`} aria-hidden="true">{copied ? <Check size={15} strokeWidth={2.2} /> : <Copy size={14} />}</span>
      <span className={copied ? 'ci-copy-label-success' : ''}>{copied ? 'Copiato' : 'Copia'}</span>
    </button>
    <span className="ci-screen-reader" role="status" aria-live="polite">{copied ? 'Risposta copiata negli appunti.' : ''}</span>
  </div>;
}

export function ProfileInfo({ patient, compact = false }) {
  const [open, setOpen] = useState(false);
  const container = useRef(null);
  const bubbleId = useId();

  useEffect(() => { setOpen(false); }, [patient?.codice_fiscale]);

  useEffect(() => {
    if (!open) return;
    const outside = (event) => {
      if (!container.current?.contains(event.target)) setOpen(false);
    };
    const escape = (event) => {
      if (event.key !== 'Escape') return;
      // Prevent the enclosing native sidebar dialog from receiving this Escape.
      event.preventDefault();
      event.stopPropagation();
      setOpen(false);
    };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape, true);
    return () => {
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('keydown', escape, true);
    };
  }, [open]);

  if (!patient) return null;
  const initials = patient.nome.trim().split(/\s+/).slice(0, 2).map((part) => part[0]).join('');

  return <div ref={container} className={`ci-profile ${compact ? 'ci-profile-compact' : 'ci-profile-full'}`}>
    <button type="button" className="ci-profile-trigger" aria-label={compact ? 'Mostra codice fiscale' : `Mostra codice fiscale di ${patient.nome}`} aria-expanded={open} aria-controls={bubbleId} onClick={() => setOpen((value) => !value)}>
      <span className="ci-profile-avatar" aria-hidden="true">{initials}</span>
      {!compact && <span className="ci-profile-name">{patient.nome}<small>Paziente</small></span>}
    </button>
    {open && <div id={bubbleId} className="ci-profile-bubble" role="region" aria-label="Codice fiscale del paziente">
      <span className="ci-profile-bubble-label">Codice fiscale</span>
      <span className="ci-profile-code">{patient.codice_fiscale}</span>
    </div>}
  </div>;
}
