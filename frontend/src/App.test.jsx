import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App.jsx';

const PATIENT = { id: 1, nome: 'Mario Rossi', codice_fiscale: 'RSSMRA90A01H501X' };
const SESSION = { session_id: 'test-session-1', patient: PATIENT, preferences: null };
const SPECIALTIES = [
  { id: 1, nome: 'Cardiologia', costo_prima_visita: 120, costo_controllo: 80 },
  { id: 2, nome: 'Dermatologia', costo_prima_visita: 100, costo_controllo: 70 },
];
const tomorrow = new Date();
tomorrow.setDate(tomorrow.getDate() + 1);
const DATE = `${tomorrow.getFullYear()}-${String(tomorrow.getMonth() + 1).padStart(2, '0')}-${String(tomorrow.getDate()).padStart(2, '0')}`;
const SLOT = { slot_id: 17, medico: 'Dott.ssa Elena Riva', specialita: 'Cardiologia', data_ora: `${DATE} 10:30` };
const PENDING = { id: 'interrupt-1', summary: {
  paziente: PATIENT.nome, medico: SLOT.medico, specialita: SLOT.specialita,
  data_visita: `${DATE.slice(8)}-${DATE.slice(5, 7)}-${DATE.slice(0, 4)} 10:30`,
  tipo_visita: 'Prima visita', importo_euro: 120,
  preparazione: ['Portare gli ECG precedenti'], domanda: 'Confermi la prenotazione? (si/no)',
} };
const RECEIPT = {
  prenotazione_id: 4, paziente_id: 1, slot_id: 17, medico: SLOT.medico,
  specialita: SLOT.specialita, data_visita: SLOT.data_ora, tipo_visita: 'Prima visita',
  importo: 120, stato: 'confermata', preparazione: PENDING.summary.preparazione,
  fonte_preparazione: 'Carta dei Servizi, sezione Preparazione agli esami',
};
const PREFERENCES = { medico: SLOT.medico, fascia: 'mattina' };

function response(data, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => data };
}

function deferred() {
  let resolve;
  const promise = new Promise(accept => { resolve = accept; });
  return { promise, resolve };
}

let route;
let snapshot;
let fetchMock;
let originalShowModal;
let originalClose;

beforeAll(() => {
  originalShowModal = HTMLDialogElement.prototype.showModal;
  originalClose = HTMLDialogElement.prototype.close;
  HTMLDialogElement.prototype.showModal = function showModal() { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function close() { this.removeAttribute('open'); };
});

afterAll(() => {
  if (originalShowModal) HTMLDialogElement.prototype.showModal = originalShowModal;
  else delete HTMLDialogElement.prototype.showModal;
  if (originalClose) HTMLDialogElement.prototype.close = originalClose;
  else delete HTMLDialogElement.prototype.close;
});

beforeEach(() => {
  sessionStorage.clear();
  snapshot = { ...SESSION, messages: [], pending: null, receipt: null };
  route = async () => undefined;
  fetchMock = vi.fn(async (input, options = {}) => {
    const url = new URL(String(input), window.location.origin);
    const request = { path: url.pathname, query: url.searchParams, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null };
    const custom = await route(request);
    if (custom !== undefined) return custom;
    if (request.path === '/api/health') return response({ status: 'ok', ai_ready: true });
    if (request.path === '/api/specialties') return response({ specialties: SPECIALTIES });
    if (request.path === '/api/sessions' && request.method === 'POST') return response(SESSION);
    if (request.path === `/api/sessions/${SESSION.session_id}` && request.method === 'GET') return response(snapshot);
    if (request.path === `/api/sessions/${SESSION.session_id}` && request.method === 'DELETE') return response({ ok: true });
    if (request.path === `/api/sessions/${SESSION.session_id}/bookings` && request.method === 'GET') return response({ bookings: [] });
    throw new Error(`Unexpected HTTP request: ${request.method} ${request.path}`);
  });
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  sessionStorage.clear();
});

function requests(path, method = 'POST') {
  return fetchMock.mock.calls.filter(([input, options = {}]) => String(input).split('?')[0] === path && (options.method || 'GET') === method);
}

async function mount() {
  const user = userEvent.setup();
  render(<App />);
  await screen.findByText('Online', { exact: true });
  return user;
}

async function signIn(user) {
  await user.click(screen.getByRole('button', { name: 'Accedi', exact: true }));
  const dialog = screen.getByRole('dialog', { name: 'Accesso paziente' });
  await user.type(within(dialog).getByLabelText('Codice fiscale'), PATIENT.codice_fiscale);
  await user.click(within(dialog).getByRole('button', { name: 'Accedi', exact: true }));
  await screen.findByRole('button', { name: 'Mostra codice fiscale', exact: true });
  await waitFor(() => expect(sessionStorage.getItem('salus-session')).toBe(SESSION.session_id));
  await waitFor(() => expect(dialog).not.toHaveAttribute('open'));
}

async function openMenu(user) {
  await user.click(screen.getByRole('button', { name: 'Apri menu', exact: true }));
  return screen.getByRole('dialog', { name: 'Navigazione principale' });
}

async function checkPreferences(user) {
  const menu = await openMenu(user);
  expect(within(menu).getByRole('region', { name: 'Le tue preferenze' })).toBeVisible();
  expect(within(menu).getByText(PREFERENCES.medico)).toBeVisible();
  await user.click(within(menu).getByRole('button', { name: 'Chiudi menu' }));
}

async function startPending(user) {
  route = async request => request.path.endsWith('/messages') ? response({ messages: [], pending: PENDING, receipt: null, preferences: null }) : undefined;
  await user.type(screen.getByRole('textbox', { name: 'Scrivi a Salus' }), 'Vorrei prenotare una visita cardiologica');
  await user.click(screen.getByRole('button', { name: 'Invia messaggio' }));
  await screen.findByRole('button', { name: 'Conferma prenotazione' });
}

describe('Salus: accesso e conversazione', () => {
  it('presenta i servizi e distingue un codice fiscale incompleto da un paziente non registrato', async () => {
    route = async request => request.path === '/api/sessions' && request.method === 'POST'
      ? response({ detail: 'Codice fiscale non trovato: rivolgersi all’accettazione.' }, 404) : undefined;
    const user = await mount();
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Come posso aiutarti?');
    const menu = await openMenu(user);
    expect(within(menu).getByRole('link', { name: /Carta dei servizi/i })).toHaveAttribute('href', '/api/services-document');
    await user.click(within(menu).getByRole('button', { name: 'Accedi', exact: true }));
    const dialog = screen.getByRole('dialog', { name: 'Accesso paziente' });
    const input = within(dialog).getByLabelText('Codice fiscale');
    await user.type(input, 'ABC');
    await user.click(within(dialog).getByRole('button', { name: 'Accedi', exact: true }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('16 lettere e numeri');
    expect(requests('/api/sessions')).toHaveLength(0);
    await user.clear(input);
    await user.type(input, 'ZZZZZZ00A00A000Z');
    await user.click(within(dialog).getByRole('button', { name: 'Accedi', exact: true }));
    await waitFor(() => expect(within(dialog).getByRole('alert')).toHaveTextContent('Codice fiscale non trovato'));
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(sessionStorage.getItem('salus-session')).toBeNull();
  });

  it('accede, invia una domanda e rende la risposta Markdown ricevuta dal backend', async () => {
    route = async request => request.path.endsWith('/messages') ? response({
      messages: [{ id: 'answer-1', role: 'assistant', content: '**Accettazione**\n\n- Dal lunedì al venerdì\n\nFonte: Orari.' }], pending: null, receipt: null, preferences: null,
    }) : undefined;
    const user = await mount();
    await signIn(user);
    expect(sessionStorage.getItem('salus-session')).toBe(SESSION.session_id);
    const input = screen.getByRole('textbox', { name: 'Scrivi a Salus' });
    await user.type(input, 'Quali sono gli orari?{Enter}');
    const log = await screen.findByRole('log', { name: 'Messaggi della conversazione' });
    await within(log).findByText('Accettazione');
    expect(within(log).getByText('Accettazione').tagName).toBe('STRONG');
    expect(within(log).getByRole('listitem')).toHaveTextContent('Dal lunedì al venerdì');
    expect(JSON.parse(requests(`/api/sessions/${SESSION.session_id}/messages`)[0][1].body)).toEqual({ message: 'Quali sono gli orari?' });
    expect(input).toHaveValue('');
    expect(input).toBeEnabled();
  });

  it('blocca invii concorrenti mentre il backend elabora una domanda', async () => {
    const reply = deferred();
    route = async request => request.path.endsWith('/messages') ? reply.promise : undefined;
    const user = await mount();
    await signIn(user);
    const input = screen.getByRole('textbox', { name: 'Scrivi a Salus' });
    await user.type(input, 'Quali documenti porto?');
    await user.dblClick(screen.getByRole('button', { name: 'Invia messaggio' }));
    expect(input).toBeDisabled();
    expect(requests(`/api/sessions/${SESSION.session_id}/messages`)).toHaveLength(1);
    await act(async () => reply.resolve(response({ messages: [{ id: 'answer-docs', role: 'assistant', content: 'Porta la tessera sanitaria.' }], pending: null })));
    await screen.findByText('Porta la tessera sanitaria.');
    expect(input).toBeEnabled();
  });
});

describe('Salus: appuntamenti e conferma esplicita', () => {
  it('invia lo slot scelto in chat al grafo e registra solo dopo un singolo sì', async () => {
    const confirmation = deferred();
    route = async request => {
      if (request.path.endsWith('/messages')) return response({ messages: [], pending: PENDING, receipt: null, preferences: null });
      if (request.path.endsWith('/confirm')) return confirmation.promise;
      return undefined;
    };
    const user = await mount();
    await signIn(user);
    expect(screen.queryByRole('button', { name: 'Cerca disponibilità' })).not.toBeInTheDocument();
    await user.type(screen.getByRole('textbox', { name: 'Scrivi a Salus' }), `Vorrei prenotare lo slot 17 di Cardiologia il ${DATE} alle 10:30, prima visita.`);
    await user.click(screen.getByRole('button', { name: 'Invia messaggio' }));
    const confirm = await screen.findByRole('button', { name: 'Conferma prenotazione' });
    expect(screen.getByRole('textbox', { name: 'Scrivi a Salus' })).toBeDisabled();
    expect(requests(`/api/sessions/${SESSION.session_id}/confirm`)).toHaveLength(0);
    expect(JSON.parse(requests(`/api/sessions/${SESSION.session_id}/messages`)[0][1].body).message).toContain('slot 17');
    expect(screen.getByText('Portare gli ECG precedenti')).toBeInTheDocument();
    await user.dblClick(confirm);
    expect(requests(`/api/sessions/${SESSION.session_id}/confirm`)).toHaveLength(1);
    expect(JSON.parse(requests(`/api/sessions/${SESSION.session_id}/confirm`)[0][1].body)).toEqual({ answer: 'si' });
    await act(async () => confirmation.resolve(response({ messages: [{ id: 'confirmed', role: 'assistant', content: 'Prenotazione registrata.' }], pending: null, receipt: RECEIPT, preferences: PREFERENCES })));
    await screen.findByText('Ci vediamo presto.');
    expect(screen.getByRole('link', { name: /Scarica ricevuta/ })).toHaveAttribute('href', `/api/sessions/${SESSION.session_id}/receipt/4`);
    expect(screen.getByRole('link', { name: /Scarica ricevuta/ })).toHaveAttribute('download', 'ricevuta_004.json');
    await checkPreferences(user);
    expect(screen.queryByRole('button', { name: 'Conferma prenotazione' })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Scrivi a Salus' })).toBeEnabled();
  });

  it('rifiuta il riepilogo senza mostrare una ricevuta o registrare un sì', async () => {
    const user = await mount();
    await signIn(user);
    await startPending(user);
    route = async request => request.path.endsWith('/confirm') ? response({ messages: [{ id: 'declined', role: 'assistant', content: 'Prenotazione non registrata. Scegliamo un altro orario?' }], pending: null, receipt: null, preferences: null }) : undefined;
    await user.click(screen.getByRole('button', { name: 'Non confermare' }));
    await screen.findByText('Prenotazione non registrata. Scegliamo un altro orario?');
    expect(JSON.parse(requests(`/api/sessions/${SESSION.session_id}/confirm`)[0][1].body)).toEqual({ answer: 'no' });
    expect(screen.queryByRole('link', { name: /Scarica ricevuta/ })).not.toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Scrivi a Salus' })).toBeEnabled();
  });

  it('recupera lo stato dal server dopo un errore di conferma e conserva la richiesta pendente', async () => {
    const user = await mount();
    await signIn(user);
    await startPending(user);
    snapshot = { ...SESSION, messages: [{ id: 'stored-user', role: 'user', content: 'Vorrei prenotare una visita cardiologica' }], pending: PENDING, receipt: null };
    route = async request => request.path.endsWith('/confirm') ? response({ detail: 'Modello temporaneamente non disponibile.' }, 503) : undefined;
    await user.click(screen.getByRole('button', { name: 'Conferma prenotazione' }));
    await screen.findByText('Modello temporaneamente non disponibile.');
    await waitFor(() => expect(requests(`/api/sessions/${SESSION.session_id}`, 'GET')).toHaveLength(1));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Conferma prenotazione' })).toBeEnabled());
    expect(screen.getByRole('textbox', { name: 'Scrivi a Salus' })).toBeDisabled();
    expect(screen.queryByRole('link', { name: /Scarica ricevuta/ })).not.toBeInTheDocument();
    expect(requests(`/api/sessions/${SESSION.session_id}/confirm`)).toHaveLength(1);
  });
});

describe('Salus: ciclo della sessione', () => {
  it('attende uno snapshot inizialmente occupato senza ripetere login, messaggi o conferme', async () => {
    sessionStorage.setItem('salus-session', SESSION.session_id);
    snapshot = { ...SESSION, messages: [{ id: 'answer-after-refresh', role: 'assistant', content: 'La risposta completata prima del ripristino.' }], pending: null, receipts: [] };
    let snapshotReads = 0;
    route = async request => {
      if (request.path === `/api/sessions/${SESSION.session_id}` && request.method === 'GET') {
        snapshotReads += 1;
        return snapshotReads === 1
          ? response({ detail: 'La conversazione sta elaborando una richiesta.' }, 409)
          : response(snapshot);
      }
      return undefined;
    };
    const user = await mount();
    expect(screen.getByText('Recupero la tua conversazione…')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Scrivi a Salus' })).toBeDisabled();
    await screen.findByText('La risposta completata prima del ripristino.', {}, { timeout: 3000 });
    expect(requests(`/api/sessions/${SESSION.session_id}`, 'GET')).toHaveLength(2);
    expect(requests('/api/sessions')).toHaveLength(0);
    expect(requests(`/api/sessions/${SESSION.session_id}/messages`)).toHaveLength(0);
    expect(requests(`/api/sessions/${SESSION.session_id}/confirm`)).toHaveLength(0);
    expect(sessionStorage.getItem('salus-session')).toBe(SESSION.session_id);
    expect(screen.getByRole('textbox', { name: 'Scrivi a Salus' })).toBeEnabled();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('ripristina tutte le ricevute della sessione con il download della prenotazione corrispondente', async () => {
    sessionStorage.setItem('salus-session', SESSION.session_id);
    const secondReceipt = { ...RECEIPT, prenotazione_id: 5, slot_id: 28, specialita: 'Dermatologia', medico: 'Dott. Paolo Neri', importo: 100 };
    snapshot = {
      ...SESSION, messages: [{ id: 'receipt-history', role: 'assistant', content: 'Hai confermato due visite.' }],
      pending: null, receipts: [RECEIPT, secondReceipt], receipt: secondReceipt, preferences: PREFERENCES,
    };
    const user = await mount();
    expect(await screen.findAllByText('Ci vediamo presto.')).toHaveLength(2);
    const downloads = screen.getAllByRole('link', { name: /Scarica ricevuta/ });
    expect(downloads).toHaveLength(2);
    expect(downloads[0]).toHaveAttribute('href', `/api/sessions/${SESSION.session_id}/receipt/4`);
    expect(downloads[0]).toHaveAttribute('download', 'ricevuta_004.json');
    expect(downloads[1]).toHaveAttribute('href', `/api/sessions/${SESSION.session_id}/receipt/5`);
    expect(downloads[1]).toHaveAttribute('download', 'ricevuta_005.json');
    expect(screen.getByText('N° 004')).toBeInTheDocument();
    expect(screen.getByText('N° 005')).toBeInTheDocument();
    expect(requests('/api/sessions')).toHaveLength(0);
    expect(requests(`/api/sessions/${SESSION.session_id}/confirm`)).toHaveLength(0);
  });

  it('mantiene la ricevuta accanto alla conferma originale prima dei messaggi successivi dopo il ripristino', async () => {
    sessionStorage.setItem('salus-session', SESSION.session_id);
    const anchoredReceipt = { ...RECEIPT, prenotazione_id: 2 };
    snapshot = {
      ...SESSION,
      messages: [
        { id: 'a1', role: 'assistant', content: 'La visita cardiologica è stata prenotata.' },
        { id: 'u2', role: 'user', content: 'Quali documenti devo portare alla visita?' },
        { id: 'a2', role: 'assistant', content: 'Porta tessera sanitaria e documento di identità.' },
      ],
      pending: null, receipts: [anchoredReceipt], receipt: anchoredReceipt,
      receipt_anchors: { '2': 'a1' }, preferences: PREFERENCES,
    };
    const user = await mount();
    const receipt = (await screen.findByText('Ci vediamo presto.')).closest('section');
    const confirmation = screen.getByText('La visita cardiologica è stata prenotata.');
    const nextQuestion = screen.getByText('Quali documenti devo portare alla visita?');
    const nextAnswer = screen.getByText('Porta tessera sanitaria e documento di identità.');
    expect(confirmation.compareDocumentPosition(receipt) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(receipt.compareDocumentPosition(nextQuestion) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(receipt.compareDocumentPosition(nextAnswer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(screen.getByRole('log', { name: 'Messaggi della conversazione' })).getByRole('link', { name: /Scarica ricevuta/ })).toHaveAttribute('href', `/api/sessions/${SESSION.session_id}/receipt/2`);
    expect(screen.getByRole('link', { name: /Scarica ricevuta/ })).toHaveAttribute('download', 'ricevuta_002.json');
    expect(screen.getAllByText('Ci vediamo presto.')).toHaveLength(1);
  });

  it('ripristina una conversazione pendente da sessionStorage senza ripetere il login o la prenotazione', async () => {
    sessionStorage.setItem('salus-session', SESSION.session_id);
    snapshot = { ...SESSION, messages: [{ id: 'restored-user', role: 'user', content: 'La mia visita in sospeso' }], pending: PENDING, receipt: null, preferences: PREFERENCES };
    const user = await mount();
    await screen.findByText('La mia visita in sospeso');
    expect(screen.getByRole('button', { name: 'Conferma prenotazione' })).toBeEnabled();
    await checkPreferences(user);
    expect(requests('/api/sessions')).toHaveLength(0);
    expect(requests(`/api/sessions/${SESSION.session_id}/messages`)).toHaveLength(0);
    expect(requests(`/api/sessions/${SESSION.session_id}/confirm`)).toHaveLength(0);
  });

  it('termina la sessione solo dopo la conferma di uscita e rimuove il riferimento salvato', async () => {
    const user = await mount();
    await signIn(user);
    const deletion = deferred();
    route = async request => request.path === `/api/sessions/${SESSION.session_id}` && request.method === 'DELETE' ? deletion.promise : undefined;
    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('button', { name: 'Esci dalla sessione' }));
    const dialog = screen.getByRole('dialog', { name: 'Termina conversazione' });
    expect(requests(`/api/sessions/${SESSION.session_id}`, 'DELETE')).toHaveLength(0);
    const confirmExit = within(dialog).getByRole('button', { name: 'Esci', exact: true });
    await user.dblClick(confirmExit);
    expect(requests(`/api/sessions/${SESSION.session_id}`, 'DELETE')).toHaveLength(1);
    expect(confirmExit).toBeDisabled();
    expect(within(dialog).getByRole('button', { name: 'Annulla', exact: true })).toBeDisabled();
    await act(async () => deletion.resolve(response({ ok: true })));
    await screen.findByRole('button', { name: 'Accedi', exact: true });
    expect(requests(`/api/sessions/${SESSION.session_id}`, 'DELETE')).toHaveLength(1);
    expect(sessionStorage.getItem('salus-session')).toBeNull();
    expect(screen.queryByText(PATIENT.nome)).not.toBeInTheDocument();
  });

  it('apre una nuova conversazione per lo stesso paziente dopo aver chiuso quella precedente', async () => {
    const user = await mount();
    await signIn(user);
    route = async request => request.path === '/api/sessions' && request.method === 'POST'
      ? response({ ...SESSION, session_id: 'test-session-2', preferences: PREFERENCES }) : undefined;
    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('button', { name: 'Nuova conversazione' }));
    const dialog = screen.getByRole('dialog', { name: 'Nuova conversazione' });
    await user.click(within(dialog).getByRole('button', { name: 'Nuova chat', exact: true }));
    await waitFor(() => expect(sessionStorage.getItem('salus-session')).toBe('test-session-2'));
    expect(requests(`/api/sessions/${SESSION.session_id}`, 'DELETE')).toHaveLength(1);
    expect(JSON.parse(requests('/api/sessions').at(-1)[1].body)).toEqual({ codice_fiscale: PATIENT.codice_fiscale });
    await checkPreferences(user);
    expect(screen.getByRole('textbox', { name: 'Scrivi a Salus' })).toBeEnabled();
  });
});

describe('Salus: menu essenziale e prenotazioni del paziente', () => {
  it('mantiene il menu chiuso, propone le domande solo nella chat vuota e chiude il menu con il comando nativo Escape', async () => {
    const user = await mount();
    const opener = screen.getByRole('button', { name: 'Apri menu', exact: true });
    expect(opener).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('dialog', { name: 'Navigazione principale' })).not.toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Prenota una visita', exact: true })).toHaveLength(1);
    expect(screen.queryByText('Spazio paziente')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cerca disponibilità', exact: true })).not.toBeInTheDocument();

    const menu = await openMenu(user);
    expect(opener).toHaveAttribute('aria-expanded', 'true');
    expect(within(menu).queryByRole('button', { name: 'Prenota una visita', exact: true })).not.toBeInTheDocument();
    expect(within(menu).getByRole('button', { name: 'Le mie prenotazioni' })).toBeVisible();
    fireEvent(menu, new Event('cancel', { cancelable: true }));
    await waitFor(() => expect(menu).not.toHaveAttribute('open'));
    expect(opener).toHaveAttribute('aria-expanded', 'false');
  });

  it('mostra Online o Offline secondo la disponibilità reale del servizio e permette di ricollegarlo', async () => {
    route = async request => request.path === '/api/health'
      ? response({ status: 'ok', ai_ready: false, detail: 'Ollama non disponibile.' }) : undefined;
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText('Offline', { exact: true })).toBeVisible();
    expect(screen.queryByText('Online', { exact: true })).not.toBeInTheDocument();
    route = async request => request.path === '/api/health'
      ? response({ status: 'ok', ai_ready: true }) : undefined;
    await user.click(await screen.findByRole('button', { name: 'Ricollega', exact: true }));
    expect(await screen.findByText('Online', { exact: true })).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Ricollega', exact: true })).not.toBeInTheDocument();
  });

  it('apre le prenotazioni del paziente attivo e offre il download solo per le ricevute autorizzate', async () => {
    const oldBooking = { ...RECEIPT, prenotazione_id: 1, data_visita: '2020-01-10 09:00', receipt_available: false };
    const currentBooking = { ...RECEIPT, data_visita: '2099-01-10 10:30', receipt_available: true };
    route = async request => request.path === `/api/sessions/${SESSION.session_id}/bookings`
      ? response({ bookings: [currentBooking, oldBooking] }) : undefined;
    const user = await mount();
    await signIn(user);
    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('button', { name: 'Le mie prenotazioni' }));
    const dialog = await screen.findByRole('dialog', { name: 'Le mie prenotazioni' });
    const list = await within(dialog).findByRole('list', { name: 'Elenco delle tue prenotazioni' });
    const items = within(list).getAllByRole('listitem');
    expect(items).toHaveLength(2);
    expect(within(items[0]).getByText('Confermata')).toBeVisible();
    expect(within(items[1]).getByText('Passata')).toBeVisible();
    expect(within(items[0]).getByRole('link', { name: /Scarica ricevuta JSON/ })).toHaveAttribute('href', `/api/sessions/${SESSION.session_id}/receipt/4`);
    expect(within(items[1]).queryByRole('link', { name: /Scarica ricevuta/ })).not.toBeInTheDocument();
    expect(requests(`/api/sessions/${SESSION.session_id}/bookings`, 'GET')).toHaveLength(1);
    expect(requests(`/api/sessions/${SESSION.session_id}/messages`)).toHaveLength(0);
    await user.click(within(dialog).getByRole('button', { name: 'Chiudi prenotazioni' }));
    await waitFor(() => expect(dialog).not.toHaveAttribute('open'));
  });

  it('chiede accesso prima di recuperare le prenotazioni e riprende la destinazione scelta dopo il login', async () => {
    const user = await mount();
    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('button', { name: 'Le mie prenotazioni' }));
    const login = screen.getByRole('dialog', { name: 'Accesso paziente' });
    expect(requests(`/api/sessions/${SESSION.session_id}/bookings`, 'GET')).toHaveLength(0);
    await user.type(within(login).getByLabelText('Codice fiscale'), PATIENT.codice_fiscale);
    await user.click(within(login).getByRole('button', { name: 'Accedi', exact: true }));
    const bookings = await screen.findByRole('dialog', { name: 'Le mie prenotazioni' });
    expect(await within(bookings).findByText('Ancora nessuna visita.')).toBeVisible();
    expect(requests(`/api/sessions/${SESSION.session_id}/bookings`, 'GET')).toHaveLength(1);
    expect(requests('/api/sessions')).toHaveLength(1);
  });

  it('recupera la lista dopo un errore senza cambiare la sessione o ripetere una prenotazione', async () => {
    let attempts = 0;
    route = async request => {
      if (request.path === `/api/sessions/${SESSION.session_id}/bookings`) {
        attempts += 1;
        return attempts === 1 ? response({ detail: 'La richiesta è ancora in corso.' }, 409) : response({ bookings: [{ ...RECEIPT, receipt_available: false }] });
      }
      return undefined;
    };
    const user = await mount();
    await signIn(user);
    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('button', { name: 'Le mie prenotazioni' }));
    const dialog = await screen.findByRole('dialog', { name: 'Le mie prenotazioni' });
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('La richiesta è ancora in corso.');
    await user.click(within(dialog).getByRole('button', { name: 'Riprova', exact: true }));
    expect(await within(dialog).findByText('Prenotazione #4')).toBeVisible();
    expect(requests(`/api/sessions/${SESSION.session_id}/bookings`, 'GET')).toHaveLength(2);
    expect(requests(`/api/sessions/${SESSION.session_id}/confirm`)).toHaveLength(0);
    expect(requests('/api/sessions')).toHaveLength(1);
  });
});


describe('Salus: copia, profilo e finestre essenziali', () => {
  it('copia il testo completo della risposta e mostra il successo soltanto dopo la scrittura negli appunti', async () => {
    const text = '**Documenti necessari**\n\nPorta la tessera sanitaria.';
    sessionStorage.setItem('salus-session', SESSION.session_id);
    snapshot = { ...SESSION, messages: [{ id: 'copy-answer', role: 'assistant', content: text }], pending: null };
    const user = await mount();
    const copied = deferred();
    const write = vi.spyOn(navigator.clipboard, 'writeText').mockImplementation(() => copied.promise);
    const button = await screen.findByRole('button', { name: 'Copia la risposta' });
    await user.dblClick(button);
    expect(write).toHaveBeenCalledTimes(1);
    expect(write).toHaveBeenCalledWith(text);
    expect(button).toBeDisabled();
    expect(screen.queryByText('Copiato', { exact: true })).not.toBeInTheDocument();
    await act(async () => copied.resolve());
    expect(await screen.findByRole('button', { name: 'Risposta copiata' })).toHaveTextContent('Copiato');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Copia la risposta' })).toHaveTextContent('Copia'), { timeout: 3000 });
  });

  it('non mostra una falsa conferma di copia se il browser rifiuta gli appunti', async () => {
    sessionStorage.setItem('salus-session', SESSION.session_id);
    snapshot = { ...SESSION, messages: [{ id: 'copy-denied', role: 'assistant', content: 'Porta un documento di identità.' }], pending: null };
    const user = await mount();
    vi.spyOn(navigator.clipboard, 'writeText').mockRejectedValue(new Error('Permission denied'));
    await user.click(await screen.findByRole('button', { name: 'Copia la risposta' }));
    expect(await screen.findByText('Copia non disponibile. Puoi selezionare il testo della risposta.')).toBeVisible();
    expect(screen.queryByRole('button', { name: 'Risposta copiata' })).not.toBeInTheDocument();
    expect(screen.queryByText('Copiato', { exact: true })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Copia la risposta' })).toBeEnabled();
  });

  it('mostra il codice fiscale dal profilo in alto e dal nome nel menu e lo richiude senza terminare la sessione', async () => {
    const user = await mount();
    await signIn(user);
    const topProfile = screen.getByRole('button', { name: 'Mostra codice fiscale', exact: true });
    expect(topProfile).toHaveAttribute('aria-expanded', 'false');
    await user.click(topProfile);
    let bubble = screen.getByRole('region', { name: 'Codice fiscale del paziente' });
    expect(within(bubble).getByText(PATIENT.codice_fiscale)).toBeVisible();
    expect(topProfile).toHaveAttribute('aria-expanded', 'true');
    await user.click(topProfile);
    expect(screen.queryByRole('region', { name: 'Codice fiscale del paziente' })).not.toBeInTheDocument();
    await user.click(topProfile);
    await user.click(screen.getByRole('heading', { level: 1 }));
    expect(screen.queryByRole('region', { name: 'Codice fiscale del paziente' })).not.toBeInTheDocument();

    const menu = await openMenu(user);
    const sidebarProfile = within(menu).getByRole('button', { name: `Mostra codice fiscale di ${PATIENT.nome}` });
    await user.click(within(sidebarProfile).getByText(PATIENT.nome));
    bubble = within(menu).getByRole('region', { name: 'Codice fiscale del paziente' });
    expect(within(bubble).getByText(PATIENT.codice_fiscale)).toBeVisible();
    const escape = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    fireEvent(document, escape);
    expect(escape.defaultPrevented).toBe(true);
    expect(menu).toHaveAttribute('open');
    expect(within(menu).queryByRole('region', { name: 'Codice fiscale del paziente' })).not.toBeInTheDocument();
    expect(requests(`/api/sessions/${SESSION.session_id}`, 'DELETE')).toHaveLength(0);
    expect(requests(`/api/sessions/${SESSION.session_id}/messages`)).toHaveLength(0);
    expect(sessionStorage.getItem('salus-session')).toBe(SESSION.session_id);
  });

  it.each([
    ['Nuova conversazione', 'Nuova conversazione', 'Iniziare una nuova chat?', 'Nuova chat'],
    ['Esci dalla sessione', 'Termina conversazione', 'Uscire dalla chat?', 'Esci'],
  ])('annulla %s senza chiudere la sessione o perdere la conversazione', async (trigger, dialogName, title, confirmName) => {
    sessionStorage.setItem('salus-session', SESSION.session_id);
    snapshot = { ...SESSION, messages: [{ id: 'retained', role: 'assistant', content: 'La tua conversazione rimane qui.' }], pending: null };
    const user = await mount();
    await screen.findByText('La tua conversazione rimane qui.');
    const menu = await openMenu(user);
    await user.click(within(menu).getByRole('button', { name: trigger, exact: true }));
    const dialog = screen.getByRole('dialog', { name: dialogName });
    expect(within(dialog).getByRole('heading', { name: title })).toBeVisible();
    expect(within(dialog).getByText('Se non hai completato la prenotazione, le informazioni andranno perse.')).toBeVisible();
    expect(within(dialog).getByRole('button', { name: confirmName, exact: true })).toBeEnabled();
    await user.click(within(dialog).getByRole('button', { name: 'Annulla', exact: true }));
    expect(dialog).not.toHaveAttribute('open');
    expect(screen.getByText('La tua conversazione rimane qui.')).toBeVisible();
    expect(requests(`/api/sessions/${SESSION.session_id}`, 'DELETE')).toHaveLength(0);
    expect(requests('/api/sessions')).toHaveLength(0);
    expect(sessionStorage.getItem('salus-session')).toBe(SESSION.session_id);
  });
});

describe('Salus: suggerimenti coerenti con le richieste del backend', () => {
  it.each([
    ['Prenota una visita', 'Vorrei prenotare una prima visita.'],
    ['Medici disponibili', 'Quali medici ci sono per Cardiologia?'],
    ['Tariffe delle visite', 'Quali sono le tariffe delle prime visite e dei controlli?'],
    ['Documenti necessari', 'Quali documenti devo portare per una visita?'],
    ['Pagamenti e referti', 'Come posso pagare e dove trovo i miei referti?'],
  ])('invia la richiesta pertinente a %s senza suggerire prelievi', async (title, text) => {
    sessionStorage.setItem('salus-session', SESSION.session_id);
    route = async request => request.path.endsWith('/messages') ? response({ messages: [{ id: 'suggestion-answer', role: 'assistant', content: 'Ti aiuto con questa richiesta.' }], pending: null }) : undefined;
    const user = await mount();
    await screen.findByRole('button', { name: 'Mostra codice fiscale', exact: true });
    expect(document.body.textContent).not.toMatch(/preliev/i);
    await user.click(screen.getByRole('button', { name: title, exact: true }));
    await screen.findByText('Ti aiuto con questa richiesta.');
    expect(requests(`/api/sessions/${SESSION.session_id}/messages`)).toHaveLength(1);
    expect(JSON.parse(requests(`/api/sessions/${SESSION.session_id}/messages`)[0][1].body)).toEqual({ message: text });
    if (title === 'Prenota una visita') {
      expect(JSON.parse(requests(`/api/sessions/${SESSION.session_id}/messages`)[0][1].body).message).not.toMatch(/cardiolog/i);
    }
    expect(screen.queryByRole('button', { name: title, exact: true })).not.toBeInTheDocument();
  });
});
