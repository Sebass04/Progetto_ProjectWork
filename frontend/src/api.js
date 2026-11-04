export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

// No automatic retries: a repeated POST could create a second booking.
export async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options.headers },
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError('Non riesco a raggiungere il servizio. Controlla la connessione e riprova.', 0);
  }
  let data;
  try { data = await response.json(); }
  catch { throw new ApiError('Il servizio ha restituito una risposta non valida. Riprova tra poco.', response.status); }
  if (!response.ok) {
    throw new ApiError(typeof data.detail === 'string' ? data.detail : 'Non è stato possibile completare la richiesta.', response.status);
  }
  return data;
}

// Progress is read as NDJSON while the booking continues on the server. A lost
// response must be recovered from its session snapshot, never by repeating POST.
export async function apiStreamRequest(path, options = {}, onProgress) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/x-ndjson',
        ...options.headers,
      },
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new ApiError('Non riesco a raggiungere il servizio. Controlla la connessione e riprova.', 0);
  }

  const contentType = response.headers?.get?.('content-type') || '';
  if (!response.ok || contentType.includes('application/json') || !response.body?.getReader) {
    let data;
    try { data = await response.json(); }
    catch (error) {
      if (error.name === 'AbortError') throw error;
      throw new ApiError('Il servizio ha restituito una risposta non valida. Riprova tra poco.', response.status);
    }
    if (!response.ok) {
      throw new ApiError(typeof data?.detail === 'string' ? data.detail : 'Non è stato possibile completare la richiesta.', response.status);
    }
    return data;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffered = '';
  let result;
  let completed = false;
  const invalidResponse = () => new ApiError('Il servizio ha restituito una risposta non valida. Riprova tra poco.', response.status);

  function readLine(line) {
    if (!line.trim()) return;
    let event;
    try { event = JSON.parse(line); }
    catch { throw invalidResponse(); }
    if (!event || typeof event !== 'object' || Array.isArray(event)) throw invalidResponse();
    if (completed) throw invalidResponse();
    if (event.type === 'progress' && typeof event.message === 'string') {
      onProgress?.(event.message);
    } else if (event.type === 'result' && event.data && typeof event.data === 'object' && !Array.isArray(event.data)) {
      completed = true;
      result = event.data;
    } else if (event.type === 'error') {
      throw new ApiError(
        typeof event.detail === 'string' ? event.detail : 'Non è stato possibile completare la richiesta.',
        Number.isInteger(event.status) ? event.status : 503,
      );
    } else {
      throw invalidResponse();
    }
  }

  try {
    for (;;) {
      const { value, done } = await reader.read();
      buffered += decoder.decode(value, { stream: !done });
      let newline;
      while ((newline = buffered.indexOf('\n')) !== -1) {
        readLine(buffered.slice(0, newline));
        buffered = buffered.slice(newline + 1);
      }
      if (done) {
        readLine(buffered);
        break;
      }
    }
    if (!completed) throw new ApiError('Connessione interrotta. Recupero lo stato della conversazione.', 0);
    return result;
  } catch (error) {
    try { await reader.cancel(); } catch { /* The request may already be aborted. */ }
    if (error.name === 'AbortError' || error instanceof ApiError) throw error;
    throw new ApiError('Connessione interrotta. Recupero lo stato della conversazione.', 0);
  } finally {
    reader.releaseLock();
  }
}
