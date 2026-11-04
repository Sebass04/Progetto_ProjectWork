# Salus Levante · Assistente pazienti

Frontend React per il chatbot del Poliambulatorio Salus Levante, collegato agli agenti Python già presenti nel progetto. La chat e le prenotazioni usano il grafo reale di `main.py`: il frontend non simula risposte né registra prenotazioni autonomamente.

## Avvio rapido su Windows

Prerequisiti: Python 3.11+, Node.js 22.12+ e Ollama in esecuzione. I modelli originali del progetto sono:

```powershell
ollama pull qwen2.5:latest
ollama pull bge-m3:latest
```

Dalla cartella del progetto:

```powershell
.\avvia-web.ps1
```

Al primo avvio lo script prepara `.venv`, installa `requirements-web.txt`, installa e compila il frontend. Aprire **http://127.0.0.1:8000**. Lasciare il terminale aperto; `Ctrl+C` arresta il servizio. Se la policy PowerShell impedisce l’esecuzione, usare i comandi manuali qui sotto. Per reinstallare le dipendenze e ricompilare dopo modifiche: `.\avvia-web.ps1 -Install`.

Il database viene creato automaticamente **solo se manca**. Non eseguire `python db.py` per avviare il sito: quel comando ricrea le tabelle e azzera le prenotazioni esistenti.

## Sviluppo frontend

Primo terminale, dalla radice:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
.\.venv\Scripts\python.exe -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Secondo terminale:

```powershell
cd frontend
npm ci
npm run dev
```

Aprire **http://127.0.0.1:5173**. Vite inoltra `/api` al backend locale sulla porta 8000. Le modifiche al frontend si aggiornano automaticamente. Per servire la versione compilata dalla sola API, eseguire `npm run build` e riavviare il backend se è la prima compilazione.

## Provare la conversazione

“Accedi” richiede un codice fiscale presente nel database. La finestra offre anche “Stai provando il progetto?” per compilare il paziente fittizio Mario Rossi, codice `RSSMRA90A01H501X`.

Esempi:

- «Quali sono le tariffe delle prime visite e dei controlli?»
- «Come posso pagare e dove trovo i miei referti?»
- «Quali documenti devo portare?»
- «Quali medici ci sono per Cardiologia?»
- «Vorrei una prima visita cardiologica domani.»

La prenotazione parte dalla chat o dal suggerimento “Prenota una visita”. L’agente cerca gli orari disponibili e raccoglie la scelta del paziente. Il riepilogo nasce dall’interruzione `interrupt` del backend: **nessuna visita viene registrata prima di “Conferma prenotazione”**. “Non confermare” riprende lo stesso grafo con un rifiuto.

Il menu a scomparsa si apre con l’hamburger su qualsiasi schermo. Contiene “Le mie prenotazioni”, la Carta dei Servizi, nuova conversazione, preferenze e uscita. Lo storico legge SQLite e mostra solo le visite del paziente attivo, incluse quelle di conversazioni precedenti; il download JSON resta disponibile per le ricevute autorizzate nella sessione corrente. Le domande suggerite compaiono nella chat solo quando è vuota. Lo stato Online/Offline riflette la disponibilità dell’agente, e il campo messaggio parte da una riga e cresce con il testo.

Toccando l’avatar in alto oppure avatar e nome nel menu si apre il codice fiscale del paziente; la nuvoletta si chiude con un altro clic, un clic esterno o Escape. “Copia” conferma l’operazione con un check animato solo dopo la copia effettiva negli appunti. Accesso, nuova chat e uscita usano gli stessi modali compatti.

Il suggerimento “Pagamenti e referti” invia la domanda al RAG sulla Carta dei Servizi. Le risposte sulle tariffe delle visite terminano con l’invito a chiedere la durata, aggiunto dal codice in un nuovo paragrafo e conservato anche nella conversazione.

Gli slot dimostrativi sono fissi nel **novembre 2026**, non vengono generati automaticamente nei mesi successivi. Le date passate e gli slot occupati non vengono proposti.

## Funzionalità coperte

| Backend originale | Interfaccia web |
| --- | --- |
| Riconoscimento paziente tramite codice fiscale | Accesso, errori di anagrafica, paziente attivo e uscita |
| Router informazioni/prenotazione/diagnosi/altro | Conversazione libera collegata a `main.grafo` |
| RAG sulla Carta dei Servizi | Risposte Markdown, tabelle, sezioni citate, PDF originale consultabile |
| Ricerca medici | Domande in chat e suggerimento “Medici disponibili” |
| Ricerca per specialità e data, anche relativa | Chat libera collegata agli strumenti dell’agente |
| Prima visita e controllo, tariffe dal database | Scelta in chat e riepilogo verificabile |
| Conferma/rifiuto tramite interrupt | Scheda con dettagli, preparazione e due azioni esplicite |
| Registrazione e ricevuta JSON | Scheda confermata e download della ricevuta |
| Preferenze medico e fascia dall’ultima prenotazione | Preferenze nel menu e indicazioni nelle risposte dell’agente |
| Nuovo accesso/conversazione, `/esci`, `/fine` | Nuova conversazione, uscita e comandi intercettati nel composer |
| Storico in SQLite | “Le mie prenotazioni” nel menu, limitato al paziente della sessione |

In aggiunta, la pagina recupera la conversazione dopo un refresh, mentre il processo API resta aperto. In `sessionStorage` conserva solo l’ID casuale della sessione; messaggi e codice fiscale non vengono scritti nel browser storage. Una richiesta ancora in corso viene recuperata con soli GET, senza ripetere automaticamente un invio o una conferma.

Se Ollama non è disponibile, la pagina mostra lo stato del servizio: accesso, storico delle prenotazioni e PDF continuano a funzionare. Per le risposte in chat e la conferma serve l’AI attiva.

## Struttura e scelte

- `frontend/src/App.jsx`: layout, chat, accesso, sessione, conferma, ripristino, responsive e tastiera mobile.
- `frontend/src/BookingWidgets.jsx`: ricerca appuntamenti, riepilogo e ricevuta.
- `frontend/src/MyBookings.jsx`: storico del paziente, stati delle visite e ricevute autorizzate.
- `frontend/src/ChatInteractions.jsx`: copia animata e codice fiscale nel profilo.
- `frontend/src/api.js`: richieste HTTP ed errori, senza retry automatici delle scritture.
- `api.py`: adattatore FastAPI; importa il grafo originale solo al primo messaggio.
- `requirements-web.txt`: aggiunge le dipendenze web a quelle originali.

Il riferimento frontend è `the-gathering-pwa/src/pages/GeminiAgent.jsx`: sono stati ripresi i pattern di shell con chat scorrevole, messaggi Markdown, composer adattivo e gestione viewport. Nessun codice Firebase, Gemini, monetizzazione, dato o asset del progetto di riferimento è stato importato. I file Python originali e il funzionamento da terminale restano disponibili.

## Verifiche

```powershell
.\.venv\Scripts\python.exe -m pytest tests -q
cd frontend
npm test
npm run build
```

I test API usano database temporanei e un grafo controllato; i test UI simulano soltanto le risposte HTTP. Non richiedono Ollama e non modificano le prenotazioni locali. Le prove manuali con i modelli reali sono distinte dai test automatici.

## Limiti del prototipo

L’accesso tramite solo codice fiscale identifica una riga dimostrativa e **non autentica una persona**. Il launcher ascolta solo su `127.0.0.1`; questa versione è pensata per sviluppo e dimostrazione locale. Sessioni, cronologia e preferenze sono in memoria: riavviando il processo si perdono; le prenotazioni restano in SQLite. I link alle ricevute richiedono la sessione ancora attiva: scaricare il JSON prima di uscire.

Modifica/disdetta delle visite, pagamento, registrazione di nuovi pazienti e invio email non sono implementati dal backend originale e non sono presentati come funzioni disponibili.
