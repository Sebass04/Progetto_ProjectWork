import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, apiStreamRequest } from './api.js';

const encoder = new TextEncoder();
const result = { messages: [{ id: 'answer', role: 'assistant', content: 'Visita pronta.' }], pending: null };

function streamed(chunks, options = {}) {
  let index = 0;
  return {
    ok: true, status: 200,
    headers: { get: () => 'application/x-ndjson' },
    body: new ReadableStream({
      async pull(controller) {
        if (index < chunks.length) {
          const chunk = chunks[index++];
          if (typeof chunk === 'function') await chunk(controller);
          else controller.enqueue(typeof chunk === 'string' ? encoder.encode(chunk) : chunk);
        } else if (options.error) controller.error(options.error);
        else controller.close();
      },
    }),
  };
}

afterEach(() => vi.unstubAllGlobals());

describe('richieste con avanzamento NDJSON', () => {
  it('comunica avanzamenti prima di risolvere e invia un solo POST', async () => {
    let finish;
    const gate = new Promise(resolve => { finish = resolve; });
    const fetch = vi.fn().mockResolvedValue(streamed([
      '{"type":"progress","message":"Sto cercando gli orari…"}\n',
      async controller => { await gate; controller.enqueue(encoder.encode(JSON.stringify({ type: 'result', data: result }) + '\n')); },
    ]));
    vi.stubGlobal('fetch', fetch);
    const progress = vi.fn();
    let settled = false;
    const request = apiStreamRequest('/messages/stream', { method: 'POST', body: '{"message":"prenota"}' }, progress).then(value => { settled = true; return value; });
    await vi.waitFor(() => expect(progress).toHaveBeenCalledWith('Sto cercando gli orari…'));
    expect(settled).toBe(false);
    finish();
    expect(await request).toEqual(result);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][1]).toMatchObject({ method: 'POST', headers: { Accept: 'application/x-ndjson', 'Content-Type': 'application/json' } });
  });

  it('ricompone UTF-8 e righe frammentate, heartbeat e riga finale senza newline', async () => {
    const content = '\n' + JSON.stringify({ type: 'progress', message: 'Disponibilità giovedì…' }) + '\r\n\n' + JSON.stringify({ type: 'result', data: result });
    const bytes = encoder.encode(content);
    // Single-byte chunks deliberately split all accented and multibyte characters.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamed([...bytes].map(byte => new Uint8Array([byte])))));
    const progress = vi.fn();
    expect(await apiStreamRequest('/messages/stream', {}, progress)).toEqual(result);
    expect(progress).toHaveBeenCalledExactlyOnceWith('Disponibilità giovedì…');
  });

  it('mantiene dettaglio e stato degli errori applicativi dopo un avanzamento', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamed([
      '{"type":"progress","message":"Registro…"}\n',
      '{"type":"error","detail":"Conferma ancora in corso.","status":409}\n',
    ])));
    await expect(apiStreamRequest('/confirm/stream')).rejects.toMatchObject({ name: 'ApiError', message: 'Conferma ancora in corso.', status: 409 });
  });

  it('richiede il recupero snapshot se il server chiude senza un risultato finale', async () => {
    const fetch = vi.fn().mockResolvedValue(streamed(['{"type":"progress","message":"Registro…"}\n']));
    vi.stubGlobal('fetch', fetch);
    await expect(apiStreamRequest('/confirm/stream', { method: 'POST' })).rejects.toMatchObject({ message: 'Connessione interrotta. Recupero lo stato della conversazione.', status: 0 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('tratta un errore di trasporto durante la lettura come stato da recuperare', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamed(['{"type":"progress","message":"Registro…"}\n'], { error: new Error('Network lost') })));
    await expect(apiStreamRequest('/confirm/stream')).rejects.toMatchObject({ name: 'ApiError', status: 0 });
  });

  it.each([
    '{malformed}\n',
    JSON.stringify({ type: 'result', data: result }) + '\n' + JSON.stringify({ type: 'result', data: result }) + '\n',
  ])('rifiuta un protocollo malformato o risultati duplicati', async content => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(streamed([content])));
    await expect(apiStreamRequest('/messages/stream')).rejects.toBeInstanceOf(ApiError);
  });

  it('propaga un errore HTTP JSON prima dell’inizio dello stream', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({ detail: 'Sessione terminata.' }) }));
    await expect(apiStreamRequest('/messages/stream')).rejects.toMatchObject({ message: 'Sessione terminata.', status: 404 });
  });

  it('preserva AbortError nella lettura e non ripete la richiesta', async () => {
    const aborted = new DOMException('Operation aborted', 'AbortError');
    const fetch = vi.fn().mockResolvedValue(streamed([], { error: aborted }));
    vi.stubGlobal('fetch', fetch);
    await expect(apiStreamRequest('/messages/stream')).rejects.toBe(aborted);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('preserva AbortError prima che arrivi una risposta', async () => {
    const aborted = new DOMException('Operation aborted', 'AbortError');
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(aborted));
    await expect(apiStreamRequest('/messages/stream')).rejects.toBe(aborted);
  });

  it('accetta risposte JSON ordinarie senza body stream', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => result }));
    const progress = vi.fn();
    expect(await apiStreamRequest('/messages/stream', {}, progress)).toEqual(result);
    expect(progress).not.toHaveBeenCalled();
  });

  it('accetta il content-type JSON esplicito anche quando esiste il body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, headers: { get: () => 'application/json; charset=utf-8' }, body: new ReadableStream(), json: async () => result }));
    expect(await apiStreamRequest('/messages/stream')).toEqual(result);
  });
});
