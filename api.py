"""Local web adapter for the existing Salus Levante LangGraph application.

Run with ``python -m uvicorn api:app --host 127.0.0.1 --port 8000``.
The graph is imported only when sending the first message, so the interface,
patient lookup and availability remain usable before Ollama is ready.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Callable, Literal
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent


class LoginBody(BaseModel):
    codice_fiscale: str = Field(min_length=1, max_length=40)


class MessageBody(BaseModel):
    message: str = Field(min_length=1, max_length=12000)


class ConfirmBody(BaseModel):
    answer: str = Field(min_length=1, max_length=100)


@dataclass
class Session:
    patient: dict[str, Any]
    thread_id: str = field(default_factory=lambda: str(uuid4()))
    pending: dict[str, Any] | None = None
    receipts: dict[int, dict[str, Any]] = field(default_factory=dict)
    receipt_anchors: dict[int, str] = field(default_factory=dict)
    recovered_receipts: set[int] = field(default_factory=set)
    messages: list[dict[str, Any]] = field(default_factory=list)
    seen_messages: int = 0
    lock: Any = field(default_factory=threading.Lock)

    @property
    def config(self):
        return {"configurable": {"thread_id": self.thread_id,
                                  "codice_fiscale": self.patient["codice_fiscale"]}}


def _ollama_status() -> tuple[bool, str | None]:
    required = ("langgraph", "langchain", "langchain_ollama", "langchain_chroma", "pypdf")
    if any(importlib.util.find_spec(name) is None for name in required):
        return False, "Installa le dipendenze Python indicate in requirements-web.txt per attivare l'assistente."
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    try:
        with urlopen(base_url + "/api/tags", timeout=2) as response:
            available = {m["name"] for m in json.load(response).get("models", [])}
        requested = [os.getenv("OLLAMA_MODEL", "qwen2.5:latest"),
                     os.getenv("OLLAMA_EMBED_MODEL", "bge-m3:latest")]
        missing = [name for name in requested
                   if name not in available and name + ":latest" not in available]
        if missing:
            return False, "Scarica in Ollama i modelli richiesti: " + ", ".join(missing) + "."
        return True, None
    except (OSError, URLError, ValueError, KeyError):
        return False, "Avvia Ollama per usare l'assistente. Puoi già consultare le disponibilità."


def create_app(database_path: Path | str | None = None,
               runtime_loader: Callable[[], Any] | None = None,
               receipt_directory: Path | str | None = None) -> FastAPI:
    application = FastAPI(title="Salus Levante · Assistente", docs_url="/api/docs")
    database = Path(database_path) if database_path else ROOT / "medibook.db"
    receipts_dir = Path(receipt_directory) if receipt_directory else ROOT / "ricevute"
    sessions: dict[str, Session] = {}
    db_lock = threading.Lock()
    # Existing booking functions don't record a web-session identifier. Serialising
    # graph invocations makes the before/after booking delta attributable to exactly
    # one session, including a booking committed before an LLM completion fails.
    invocation_lock = threading.Lock()
    runtime: Any = None

    @contextmanager
    def connect():
        with db_lock:
            if not database.exists():
                database.parent.mkdir(parents=True, exist_ok=True)
                with closing(sqlite3.connect(database)) as connection:
                    connection.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def get_session(session_id: str) -> Session:
        session = sessions.get(session_id)
        if session is None:
            raise HTTPException(404, "Sessione non trovata o terminata. Accedi nuovamente.")
        return session

    def preferences(session: Session):
        if runtime is None:
            return None
        item = runtime.memoria_preferenze.get(("pazienti", session.patient["codice_fiscale"]), "preferenze")
        return item.value if item is not None else None

    def booking_ids(session: Session) -> set[int]:
        with connect() as connection:
            return {r[0] for r in connection.execute(
                "SELECT id FROM prenotazioni WHERE paziente_id = ?", (session.patient["id"],))}

    def collect_receipts(session: Session, before: set[int], allowed: bool):
        # A successful booking can only follow this session's positive response to
        # its own interrupt. Do not attribute unrelated CLI bookings to a chat that
        # is merely asking for information, or whose confirmation was declined.
        if not allowed or session.pending is None:
            return None
        summary = session.pending["summary"]
        try:
            expected_date = datetime.strptime(summary["data_visita"], "%d-%m-%Y %H:%M").strftime("%Y-%m-%d %H:%M")
        except (KeyError, TypeError, ValueError):
            return None
        latest = None
        with connect() as connection:
            rows = connection.execute("""
                SELECT p.*, slot.data_ora, medici.nome AS medico, specialita.nome AS specialita
                FROM prenotazioni p JOIN slot ON slot.id = p.slot_id
                JOIN medici ON medici.id = slot.medico_id
                JOIN specialita ON specialita.id = medici.specialita_id
                WHERE p.paziente_id = ? AND p.stato = 'confermata' ORDER BY p.id
            """, (session.patient["id"],)).fetchall()
        for row in rows:
            booking_id = row["id"]
            if booking_id in before:
                continue
            if not (row["medico"] == summary.get("medico")
                    and row["specialita"] == summary.get("specialita")
                    and row["data_ora"] == expected_date
                    and row["tipo_visita"] == summary.get("tipo_visita")
                    and row["importo"] == summary.get("importo_euro")):
                continue
            path = receipts_dir / f"ricevuta_{booking_id:03d}.json"
            try:
                receipt = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(receipt, dict) or receipt.get("paziente_id") != session.patient["id"] or receipt.get("prenotazione_id") != booking_id:
                    raise ValueError("Receipt ownership does not match the recorded booking")
            except (OSError, ValueError):
                # booking.py commits before writing the JSON. If that write fails,
                # the DB still proves the visit is booked: reconstruct the download
                # from recorded fields and the confirmed preparation instructions.
                receipt = {"preparazione": summary.get("preparazione", []),
                           "fonte_preparazione": "Carta dei Servizi, sezione Preparazione agli esami"}
                session.recovered_receipts.add(booking_id)
            receipt.update({"prenotazione_id": booking_id, "paziente_id": row["paziente_id"],
                            "slot_id": row["slot_id"], "specialita": row["specialita"],
                            "medico": row["medico"], "data_visita": row["data_ora"],
                            "tipo_visita": row["tipo_visita"], "importo": row["importo"],
                            "stato": row["stato"], "creata_il": row["creato_il"]})
            session.receipts[booking_id] = receipt
            latest = receipt
        return latest

    def get_runtime():
        nonlocal runtime
        if runtime is None:
            if runtime_loader is None:
                ready, detail = _ollama_status()
                if not ready:
                    raise HTTPException(503, detail)
            try:
                runtime = runtime_loader() if runtime_loader else importlib.import_module("main")
            except Exception as error:
                raise HTTPException(503, "Impossibile inizializzare l'assistente. Controlla Ollama, i modelli e le dipendenze Python.") from error
        return runtime

    def anchor_receipt(session: Session, receipt):
        if receipt is None or not session.messages:
            return None
        anchor = next((message["id"] for message in reversed(session.messages)
                       if message["role"] == "assistant"), session.messages[-1]["id"])
        session.receipt_anchors[receipt["prenotazione_id"]] = anchor
        return anchor

    def format_result(result: dict, session: Session, receipt=None):
        interrupts = result.get("__interrupt__", ())
        if interrupts:
            # The current application produces exactly one booking confirmation.
            request = interrupts[0]
            session.pending = {"id": request.id, "summary": request.value}
        else:
            session.pending = None
        all_messages = result.get("messages", [])
        new_messages = all_messages[session.seen_messages:]
        session.seen_messages = len(all_messages)
        messages = []
        for msg in reversed(new_messages):
            if getattr(msg, "type", None) == "ai" and getattr(msg, "content", None) and not getattr(msg, "tool_calls", None):
                content = msg.content
                if isinstance(content, list):
                    content = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
                messages = [{"id": str(getattr(msg, "id", None) or uuid4()),
                             "role": "assistant", "content": str(content)}]
                break
        if receipt and receipt["prenotazione_id"] in session.recovered_receipts:
            session.pending = None
            messages = [{"id": str(uuid4()), "role": "assistant",
                         "content": "La prenotazione è stata registrata. Ho recuperato il riepilogo dai dati salvati: puoi scaricare qui la ricevuta."}]
        session.messages.extend(messages)
        receipt_anchor = anchor_receipt(session, receipt)
        return {"messages": messages, "pending": session.pending,
                "receipt": receipt, "receipt_anchor": receipt_anchor,
                "preferences": preferences(session)}

    def invoke(session_id: str, message: str | None = None, answer: str | None = None,
               on_progress: Callable[[str], None] | None = None):
        session = get_session(session_id)
        if not session.lock.acquire(blocking=False):
            raise HTTPException(409, "L'assistente sta già elaborando una richiesta. Attendi la risposta.")
        try:
            if sessions.get(session_id) is not session:
                raise HTTPException(404, "Sessione non trovata o terminata. Accedi nuovamente.")
            if answer is None and session.pending:
                raise HTTPException(409, "Conferma o rifiuta prima il riepilogo della prenotazione.")
            if answer is not None and not session.pending:
                raise HTTPException(409, "Non ci sono prenotazioni in attesa di conferma.")
            with invocation_lock:
                current_runtime = get_runtime()
                before = booking_ids(session)
                positive_confirmation = answer is not None and answer.strip().lower() in ("sì", "si", "s", "ok", "confermo", "conferma", "yes")
                if answer is not None:
                    command_factory = getattr(current_runtime, "Command", None)
                    if command_factory is None:
                        from langgraph.types import Command
                        command_factory = Command
                    payload = command_factory(resume={session.pending["id"]: answer})
                else:
                    payload = {"messages": [("user", message)]}
                session.messages.append({"id": str(uuid4()), "role": "user",
                                         "content": message if answer is None else answer})
                try:
                    graph = current_runtime.grafo
                    if on_progress is not None and hasattr(graph, "stream") and hasattr(graph, "get_state"):
                        # Match the CLI's custom stream, including messages from
                        # nested agents. The final checkpoint owns interrupts;
                        # they are not stored in StateSnapshot.values.
                        for event in graph.stream(payload, session.config,
                                                  stream_mode=["custom"], subgraphs=True):
                            if not isinstance(event, tuple) or len(event) != 3:
                                continue
                            _namespace, mode, data = event
                            if mode == "custom" and isinstance(data, dict):
                                progress = data.get("avanzamento")
                                if isinstance(progress, str) and progress.strip():
                                    on_progress(progress)
                        checkpoint = graph.get_state(session.config)
                        result = {"messages": checkpoint.values.get("messages", []),
                                  "__interrupt__": checkpoint.interrupts}
                    else:
                        result = graph.invoke(payload, session.config)
                except Exception as error:
                    receipt = collect_receipts(session, before, positive_confirmation)
                    # The booking transaction may have succeeded even when the model
                    # fails to phrase its final response. Return its actual receipt
                    # rather than inviting a potentially duplicate retry.
                    if receipt is not None:
                        session.pending = None
                        messages = [{"id": str(uuid4()), "role": "assistant",
                                     "content": "La prenotazione è stata registrata. Trovi qui il riepilogo e la ricevuta."}]
                        session.messages.extend(messages)
                        receipt_anchor = anchor_receipt(session, receipt)
                        return {"messages": messages,
                                "pending": None, "receipt": receipt,
                                "receipt_anchor": receipt_anchor, "preferences": preferences(session)}
                    # Do not clear pending on errors: the same confirmation can be
                    # retried against the existing LangGraph checkpoint.
                    raise HTTPException(503, "L'assistente non ha completato la risposta. Controlla Ollama e riprova.") from error
                return format_result(result, session, collect_receipts(session, before, positive_confirmation))
        finally:
            session.lock.release()

    def stream_invocation(session_id: str, message: str | None = None, answer: str | None = None):
        # Reject an unknown session before sending HTTP 200 stream headers.
        get_session(session_id)
        events: Queue = Queue()

        def produce():
            try:
                result = invoke(session_id, message=message, answer=answer,
                                on_progress=lambda text: events.put({"type": "progress", "message": text}))
                events.put({"type": "result", "data": result})
            except HTTPException as error:
                detail = error.detail if isinstance(error.detail, str) else "Non è stato possibile completare la richiesta."
                events.put({"type": "error", "detail": detail, "status": error.status_code})
            except Exception:
                events.put({"type": "error", "detail": "L'assistente non ha completato la richiesta. Riprova tra poco.",
                            "status": 503})
            finally:
                events.put(None)

        def consume():
            while True:
                try:
                    event = events.get(timeout=1)
                except Empty:
                    # A blank NDJSON line is a transport heartbeat, not an AI
                    # progress claim. Clients ignore it while Ollama is busy.
                    yield "\n"
                    continue
                if event is None:
                    return
                yield json.dumps(event, ensure_ascii=False) + "\n"

        # Keep the graph running if a tab refreshes or disconnects after the
        # confirmation POST. Its receipt/checkpoint can then be recovered with
        # a GET, rather than retrying a potentially committed booking.
        threading.Thread(target=produce, daemon=True, name="salus-graph-stream").start()
        return StreamingResponse(consume(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @application.middleware("http")
    async def privacy_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(_request, _error):
        return JSONResponse(status_code=422, content={"detail": "Controlla i dati inseriti e riprova."})

    @application.get("/api/health")
    def health():
        ready, detail = (True, None) if runtime_loader else _ollama_status()
        return {"status": "ok", "ai_ready": ready, **({"detail": detail} if detail else {})}

    @application.get("/api/specialties")
    def specialties():
        with connect() as connection:
            rows = connection.execute("SELECT * FROM specialita ORDER BY id").fetchall()
        return {"specialties": [dict(row) for row in rows]}

    @application.post("/api/sessions")
    def login(body: LoginBody):
        codice = body.codice_fiscale.strip().upper()
        with connect() as connection:
            row = connection.execute("SELECT id, nome, codice_fiscale FROM pazienti WHERE codice_fiscale = ?", (codice,)).fetchone()
        if row is None:
            raise HTTPException(404, "Codice fiscale non trovato. Rivolgiti all'accettazione.")
        session = Session(patient=dict(row))
        session_id = str(uuid4())
        sessions[session_id] = session
        return {"session_id": session_id, "patient": session.patient, "preferences": preferences(session)}

    @application.get("/api/sessions/{session_id}")
    def snapshot(session_id: str):
        session = get_session(session_id)
        if not session.lock.acquire(blocking=False):
            raise HTTPException(409, "La richiesta è ancora in corso. Attendi qualche istante.")
        try:
            if sessions.get(session_id) is not session:
                raise HTTPException(404, "Sessione non trovata o terminata. Accedi nuovamente.")
            return {"session_id": session_id, "patient": session.patient,
                    "preferences": preferences(session), "messages": session.messages[:],
                    "pending": session.pending,
                    "receipt": next(reversed(session.receipts.values()), None),
                    "receipts": list(session.receipts.values()),
                    "receipt_anchors": session.receipt_anchors.copy()}
        finally:
            session.lock.release()

    @application.get("/api/sessions/{session_id}/bookings")
    def patient_bookings(session_id: str, scope: Literal["all", "future"] = "all"):
        session = get_session(session_id)
        if not session.lock.acquire(blocking=False):
            raise HTTPException(409, "La richiesta è ancora in corso. Attendi qualche istante.")
        try:
            if sessions.get(session_id) is not session:
                raise HTTPException(404, "Sessione non trovata o terminata. Accedi nuovamente.")
            params: tuple = (session.patient["id"],)
            where = ""
            order = "DESC"
            if scope == "future":
                where = " AND p.stato = 'confermata' AND slot.data_ora > ?"
                params += (datetime.now().strftime("%Y-%m-%d %H:%M"),)
                order = "ASC"
            with connect() as connection:
                rows = connection.execute("""
                    SELECT p.id AS prenotazione_id, p.slot_id, specialita.nome AS specialita,
                           medici.nome AS medico, slot.data_ora AS data_visita,
                           p.tipo_visita, p.importo, p.stato, p.creato_il AS creata_il
                    FROM prenotazioni p JOIN slot ON slot.id = p.slot_id
                    JOIN medici ON medici.id = slot.medico_id
                    JOIN specialita ON specialita.id = medici.specialita_id
                    WHERE p.paziente_id = ?
                """ + where + f" ORDER BY slot.data_ora {order}, p.id {order}", params).fetchall()
            # Historical appointments are visible across sessions. Download rights
            # stay limited to receipts already issued to this particular session.
            bookings = [{**dict(row), "receipt_available": row["prenotazione_id"] in session.receipts}
                        for row in rows]
            return {"bookings": bookings}
        finally:
            session.lock.release()

    @application.get("/api/slots")
    def slots(specialita: str = Query(min_length=1, max_length=100), data: str = Query(min_length=10, max_length=10)):
        try:
            requested_date = date.fromisoformat(data)
        except ValueError:
            raise HTTPException(422, "La data deve essere valida e nel formato AAAA-MM-GG.")
        today = date.today()
        if requested_date < today:
            raise HTTPException(422, f"La data {requested_date.strftime('%d-%m-%Y')} è già passata. "
                                    f"Oggi è {today.strftime('%d-%m-%Y')}: scegli una data da oggi in poi.")
        with connect() as connection:
            exists = connection.execute("SELECT id FROM specialita WHERE lower(nome) = lower(?)", (specialita.strip(),)).fetchone()
            if exists is None:
                raise HTTPException(422, "Scegli una delle specialità disponibili.")
            rows = connection.execute("""
                SELECT slot.id AS slot_id, medici.nome AS medico, specialita.nome AS specialita, slot.data_ora
                FROM slot JOIN medici ON medici.id = slot.medico_id
                JOIN specialita ON specialita.id = medici.specialita_id
                WHERE lower(specialita.nome) = lower(?) AND slot.data_ora LIKE ?
                    AND slot.libero = 1 AND slot.data_ora > ?
                ORDER BY slot.data_ora, medici.nome
            """, (specialita.strip(), data + "%", datetime.now().strftime("%Y-%m-%d %H:%M"))).fetchall()
        return {"slots": [dict(row) for row in rows], "date": data, "specialita": specialita.strip()}

    @application.post("/api/sessions/{session_id}/messages")
    def message(session_id: str, body: MessageBody):
        text = body.message.strip()
        if not text:
            raise HTTPException(422, "Scrivi un messaggio prima di inviare.")
        return invoke(session_id, message=text)

    @application.post("/api/sessions/{session_id}/confirm")
    def confirm(session_id: str, body: ConfirmBody):
        answer = body.answer.strip()
        if not answer:
            raise HTTPException(422, "Scegli se confermare o rifiutare la prenotazione.")
        return invoke(session_id, answer=answer)

    @application.post("/api/sessions/{session_id}/messages/stream")
    def stream_message(session_id: str, body: MessageBody):
        text = body.message.strip()
        if not text:
            raise HTTPException(422, "Scrivi un messaggio prima di inviare.")
        return stream_invocation(session_id, message=text)

    @application.post("/api/sessions/{session_id}/confirm/stream")
    def stream_confirm(session_id: str, body: ConfirmBody):
        answer = body.answer.strip()
        if not answer:
            raise HTTPException(422, "Scegli se confermare o rifiutare la prenotazione.")
        return stream_invocation(session_id, answer=answer)

    @application.get("/api/sessions/{session_id}/receipt/{booking_id}")
    def download_receipt(session_id: str, booking_id: int):
        session = get_session(session_id)
        receipt = session.receipts.get(booking_id)
        if receipt is None:
            raise HTTPException(404, "Ricevuta non disponibile in questa conversazione.")
        return JSONResponse(content=receipt, headers={
            "Content-Disposition": f'attachment; filename="ricevuta_{booking_id:03d}.json"'})

    @application.delete("/api/sessions/{session_id}")
    def logout(session_id: str):
        session = get_session(session_id)
        if not session.lock.acquire(blocking=False):
            raise HTTPException(409, "Attendi che l'assistente completi la richiesta prima di uscire.")
        try:
            if sessions.get(session_id) is not session:
                raise HTTPException(404, "Sessione non trovata o terminata. Accedi nuovamente.")
            sessions.pop(session_id, None)
            if runtime is not None:
                saver = getattr(runtime.grafo, "checkpointer", None)
                if saver is not None and hasattr(saver, "delete_thread"):
                    saver.delete_thread(session.thread_id)
        finally:
            session.lock.release()
        return {"status": "closed"}

    @application.get("/api/services-document")
    def services_document():
        return FileResponse(ROOT / "data" / "carta_servizi_poliambulatorio.pdf", media_type="application/pdf")

    # Mount assets separately so unknown API URLs never fall through to the SPA.
    dist = ROOT / "frontend" / "dist"
    if (dist / "assets").is_dir():
        application.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @application.get("/{path:path}")
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Endpoint non trovato.")
        index = dist / "index.html"
        if index.is_file():
            # Only serve files proven to remain inside the frontend build directory.
            candidate = (dist / path).resolve()
            if path and candidate.is_relative_to(dist.resolve()) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(index)
        return JSONResponse(status_code=503, content={
            "detail": "Frontend non ancora compilato. Esegui npm install e npm run build nella cartella frontend."})

    application.state.sessions = sessions
    application.state.invoke = invoke
    return application


app = create_app()
