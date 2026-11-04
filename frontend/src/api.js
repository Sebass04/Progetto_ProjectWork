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
