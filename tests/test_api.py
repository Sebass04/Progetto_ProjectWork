"""HTTP contract tests use an isolated database and never contact Ollama."""

import json
import sqlite3
import asyncio
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api import ROOT, MessageBody, create_app


class FakeStore:
    def __init__(self):
        self.values = {}

    def get(self, namespace, key):
        value = self.values.get((namespace, key))
        return SimpleNamespace(value=value) if value else None


class FakeGraph:
    def __init__(self, database, receipts, store):
        self.database = database
        self.receipts = receipts
        self.store = store
        self.threads = {}
        self.fail_next = False
        self.fail_after_commit = False
        self.fail_receipt_write = False
        self.create_unrelated_booking = False
        self.slot_id = 5
        self.deleted = []
        self.checkpointer = SimpleNamespace(delete_thread=self.deleted.append)

    def invoke(self, payload, config):
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("Ollama unavailable")
        thread = config["configurable"]["thread_id"]
        messages = self.threads.setdefault(thread, [])
        with sqlite3.connect(self.database) as conn:
            slot = conn.execute("""SELECT slot.data_ora, medici.nome, specialita.nome
                FROM slot JOIN medici ON medici.id = slot.medico_id
                JOIN specialita ON specialita.id = medici.specialita_id WHERE slot.id = ?""", (self.slot_id,)).fetchone()
        if isinstance(payload, dict):
            content = payload["messages"][0][1]
            messages.append(SimpleNamespace(type="human", content=content))
            if content == "prenota":
                return {"messages": messages[:], "__interrupt__": [SimpleNamespace(
                    id="confirm-1", value={"domanda": "Confermi?", "paziente": "Mario Rossi",
                        "specialita": slot[2], "medico": slot[1],
                        "data_visita": datetime.fromisoformat(slot[0]).strftime("%d-%m-%Y %H:%M"), "tipo_visita": "Prima visita",
                        "importo_euro": 120, "preparazione": ["Portare i referti"]})]}
            messages.append(SimpleNamespace(type="ai", content="Informazione dal documento.", id=f"answer-{len(messages)}"))
            return {"messages": messages[:]}
        answer = payload.resume["confirm-1"]
        if answer == "si":
            with sqlite3.connect(self.database) as conn:
                if self.create_unrelated_booking:
                    conn.execute("INSERT INTO prenotazioni (paziente_id,slot_id,tipo_visita,importo) VALUES (1,10,'Prima visita',120)")
                conn.execute("UPDATE slot SET libero = 0 WHERE id = ?", (self.slot_id,))
                cur = conn.execute("INSERT INTO prenotazioni (paziente_id,slot_id,tipo_visita,importo) VALUES (1,?,'Prima visita',120)", (self.slot_id,))
                booking_id = cur.lastrowid
            if self.fail_receipt_write:
                raise OSError("Cannot write receipt after commit")
            receipt = {"prenotazione_id": booking_id, "paziente_id": 1, "slot_id": self.slot_id,
                       "specialita": slot[2], "medico": slot[1],
                       "data_visita": slot[0], "importo": 120,
                       "tipo_visita": "Prima visita", "stato": "confermata"}
            self.receipts.mkdir(exist_ok=True)
            (self.receipts / f"ricevuta_{booking_id:03d}.json").write_text(json.dumps(receipt), encoding="utf-8")
            self.store.values[(("pazienti", "RSSMRA90A01H501X"), "preferenze")] = {"medico": "Laura Bianchi", "fascia": "mattina"}
            if self.fail_after_commit:
                raise ConnectionError("Model failed after booking was saved")
            messages.append(SimpleNamespace(type="ai", content="Prenotazione confermata.", id=f"confirmed-{booking_id}"))
        else:
            messages.append(SimpleNamespace(type="ai", content="Prenotazione non registrata.", id="declined"))
        return {"messages": messages[:]}


@pytest.fixture
def env(tmp_path):
    database = tmp_path / "test.db"
    with sqlite3.connect(database) as conn:
        conn.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        conn.execute("UPDATE slot SET data_ora = '2099' || substr(data_ora, 5)")
    store = FakeStore()
    graph = FakeGraph(database, tmp_path / "receipts", store)
    runtime = SimpleNamespace(grafo=graph, memoria_preferenze=store,
                              Command=lambda **kwargs: SimpleNamespace(**kwargs))
    loads = []
    def load():
        loads.append(True)
        return runtime
    app = create_app(database_path=database, runtime_loader=load, receipt_directory=tmp_path / "receipts")
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, graph=graph, loads=loads, app=app, database=database)


def login(env, code="RSSMRA90A01H501X"):
    response = env.client.post("/api/sessions", json={"codice_fiscale": code})
    assert response.status_code == 200
    return response.json()["session_id"]


def test_login_and_availability_do_not_load_ai(env):
    session = login(env, " rssmra90a01h501x ")
    assert session
    assert env.client.get("/api/specialties").json()["specialties"][0]["nome"] == "Cardiologia"
    response = env.client.get("/api/slots", params={"specialita": "Cardiologia", "data": "2099-11-05"})
    assert response.status_code == 200
    assert 5 in [s["slot_id"] for s in response.json()["slots"]]
    assert env.loads == []


def test_invalid_login_and_dates_have_italian_errors(env):
    assert env.client.post("/api/sessions", json={"codice_fiscale": "NONPRESENTE"}).status_code == 404
    bad_date = env.client.get("/api/slots", params={"specialita": "Cardiologia", "data": "2099-02-31"})
    assert bad_date.status_code == 422
    assert "data" in bad_date.json()["detail"]
    assert env.client.get("/api/slots", params={"specialita": "Altro", "data": "2099-11-05"}).status_code == 422


def test_slots_exclude_occupied_and_past(env):
    result = env.client.get("/api/slots", params={"specialita": "Cardiologia", "data": "2099-11-03"}).json()
    assert 1 not in [s["slot_id"] for s in result["slots"]]
    response = env.client.get("/api/slots", params={"specialita": "Cardiologia", "data": "2001-11-03"})
    assert response.status_code == 422
    assert "già passata" in response.json()["detail"]
    assert datetime.now().strftime("%d-%m-%Y") in response.json()["detail"]


def test_booking_requires_confirmation_and_download_is_session_scoped(env):
    session = login(env)
    other = login(env)
    base = f"/api/sessions/{session}"
    response = env.client.post(base + "/messages", json={"message": "prenota"}).json()
    assert response["pending"]["summary"]["importo_euro"] == 120
    assert response["receipt"] is None
    with sqlite3.connect(env.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM prenotazioni").fetchone()[0] == 1
    assert env.client.post(base + "/messages", json={"message": "ciao"}).status_code == 409
    result = env.client.post(base + "/confirm", json={"answer": "si"}).json()
    assert result["pending"] is None
    assert result["receipt"]["prenotazione_id"] == 2
    assert result["preferences"] == {"medico": "Laura Bianchi", "fascia": "mattina"}
    download = env.client.get(base + "/receipt/2")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["cache-control"] == "no-store"
    assert env.client.get(f"/api/sessions/{other}/receipt/2").status_code == 404
    assert env.client.post(base + "/confirm", json={"answer": "si"}).status_code == 409


def test_declining_never_writes_a_booking(env):
    session = login(env)
    base = f"/api/sessions/{session}"
    env.client.post(base + "/messages", json={"message": "prenota"})
    result = env.client.post(base + "/confirm", json={"answer": "no"}).json()
    assert result["receipt"] is None
    assert result["pending"] is None
    with sqlite3.connect(env.database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM prenotazioni").fetchone()[0] == 1


def test_error_releases_lock_and_preserves_pending(env):
    session = login(env)
    base = f"/api/sessions/{session}"
    env.client.post(base + "/messages", json={"message": "prenota"})
    env.graph.fail_next = True
    assert env.client.post(base + "/confirm", json={"answer": "si"}).status_code == 503
    assert env.app.state.sessions[session].pending is not None
    assert env.client.post(base + "/confirm", json={"answer": "no"}).status_code == 200
    assert env.client.post(base + "/messages", json={"message": "ciao"}).status_code == 200


def test_error_after_commit_returns_actual_receipt(env):
    session = login(env)
    base = f"/api/sessions/{session}"
    env.client.post(base + "/messages", json={"message": "prenota"})
    env.graph.fail_after_commit = True
    response = env.client.post(base + "/confirm", json={"answer": "si"})
    assert response.status_code == 200
    assert response.json()["receipt"]["prenotazione_id"] == 2
    assert response.json()["pending"] is None
    anchor = response.json()["messages"][-1]["id"]
    assert response.json()["receipt_anchor"] == anchor
    assert env.client.get(base).json()["receipt_anchors"] == {"2": anchor}


def test_receipt_write_failure_does_not_offer_duplicate_confirmation(env):
    session = login(env)
    base = f"/api/sessions/{session}"
    env.client.post(base + "/messages", json={"message": "prenota"})
    env.graph.fail_receipt_write = True
    response = env.client.post(base + "/confirm", json={"answer": "si"})
    assert response.status_code == 200
    receipt = response.json()["receipt"]
    assert receipt["prenotazione_id"] == 2
    assert receipt["preparazione"] == ["Portare i referti"]
    assert response.json()["pending"] is None
    assert env.client.get(base + "/receipt/2").status_code == 200
    assert env.client.post(base + "/confirm", json={"answer": "si"}).status_code == 409


def test_unrelated_concurrent_booking_is_not_attributed_to_session(env):
    session = login(env)
    base = f"/api/sessions/{session}"
    env.client.post(base + "/messages", json={"message": "prenota"})
    env.graph.create_unrelated_booking = True
    response = env.client.post(base + "/confirm", json={"answer": "si"})
    assert response.status_code == 200
    assert response.json()["receipt"]["prenotazione_id"] == 3
    assert env.client.get(base + "/receipt/2").status_code == 404
    assert env.client.get(base + "/receipt/3").status_code == 200


def test_parallel_request_is_rejected_without_losing_session(env):
    session = login(env)
    lock = env.app.state.sessions[session].lock
    lock.acquire()
    try:
        assert env.client.post(f"/api/sessions/{session}/messages", json={"message": "ciao"}).status_code == 409
        assert env.client.delete(f"/api/sessions/{session}").status_code == 409
    finally:
        lock.release()
    assert env.client.post(f"/api/sessions/{session}/messages", json={"message": "ciao"}).status_code == 200


def test_logout_deletes_checkpoint_and_session(env):
    session = login(env)
    env.client.post(f"/api/sessions/{session}/messages", json={"message": "ciao"})
    assert env.client.delete(f"/api/sessions/{session}").status_code == 200
    assert len(env.graph.deleted) == 1
    assert env.client.post(f"/api/sessions/{session}/messages", json={"message": "ciao"}).status_code == 404


def test_document_and_unknown_api_route(env):
    response = env.client.get("/api/services-document")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert env.client.get("/api/not-a-route").status_code == 404
    response = env.client.post("/api/sessions", json={})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_refresh_restores_ui_only_history_and_confirmation(env):
    session = login(env)
    base = f"/api/sessions/{session}"
    env.client.post(base + "/messages", json={"message": "prenota"})
    snapshot = env.client.get(base).json()
    assert snapshot["pending"]["id"] == "confirm-1"
    assert snapshot["messages"][0]["role"] == "user"
    first_id = snapshot["messages"][0]["id"]
    assert env.client.get(base).json()["messages"][0]["id"] == first_id
    env.client.post(base + "/confirm", json={"answer": "si"})
    snapshot = env.client.get(base).json()
    assert snapshot["pending"] is None
    assert snapshot["receipt"]["prenotazione_id"] == 2
    assert [m["role"] for m in snapshot["messages"]] == ["user", "user", "assistant"]


def test_snapshot_restores_all_and_only_this_sessions_receipts(env):
    session = login(env)
    other_session = login(env)
    first = {"prenotazione_id": 11, "paziente_id": 1, "medico": "Laura Bianchi"}
    second = {"prenotazione_id": 12, "paziente_id": 1, "medico": "Marco Rinaldi"}
    other = {"prenotazione_id": 13, "paziente_id": 1, "medico": "Laura Bianchi"}
    env.app.state.sessions[session].receipts.update({11: first, 12: second})
    env.app.state.sessions[other_session].receipts[13] = other
    snapshot = env.client.get(f"/api/sessions/{session}").json()
    assert snapshot["receipts"] == [first, second]
    assert snapshot["receipt"] == second
    assert env.client.get(f"/api/sessions/{other_session}").json()["receipts"] == [other]
    assert env.client.get(f"/api/sessions/{session}/receipt/11").status_code == 200
    assert env.client.get(f"/api/sessions/{other_session}/receipt/11").status_code == 404


def test_patient_bookings_are_isolated_and_do_not_load_ai(env):
    mario_session = login(env)
    luigi_session = login(env, "VRDLGU85B02A662Y")
    with sqlite3.connect(env.database) as conn:
        conn.execute("INSERT INTO prenotazioni (paziente_id,slot_id,tipo_visita,importo) VALUES (2,5,'Prima visita',120)")
    response = env.client.get(f"/api/sessions/{mario_session}/bookings")
    assert response.status_code == 200
    mario = response.json()["bookings"]
    luigi = env.client.get(f"/api/sessions/{luigi_session}/bookings").json()["bookings"]
    assert [booking["prenotazione_id"] for booking in mario] == [1]
    assert [booking["prenotazione_id"] for booking in luigi] == [2]
    assert mario[0]["medico"] == "Laura Bianchi"
    assert mario[0]["specialita"] == "Cardiologia"
    assert mario[0]["data_visita"] == "2099-11-03 09:00"
    assert mario[0]["receipt_available"] is False
    assert response.headers["cache-control"] == "no-store"
    assert env.loads == []


def test_patient_bookings_include_past_cancelled_and_order_by_date_then_id(env):
    session = login(env)
    with sqlite3.connect(env.database) as conn:
        conn.execute("UPDATE slot SET data_ora = '2001-11-03 09:00' WHERE id = 1")
        conn.execute("UPDATE slot SET data_ora = '2099-11-05 09:00' WHERE id IN (5,10)")
        conn.execute("INSERT INTO prenotazioni (paziente_id,slot_id,tipo_visita,importo,stato) VALUES (1,5,'Prima visita',120,'annullata')")
        conn.execute("INSERT INTO prenotazioni (paziente_id,slot_id,tipo_visita,importo) VALUES (1,10,'Visita di controllo',80)")
    bookings = env.client.get(f"/api/sessions/{session}/bookings").json()["bookings"]
    assert [booking["prenotazione_id"] for booking in bookings] == [3, 2, 1]
    assert bookings[1]["stato"] == "annullata"
    assert bookings[2]["data_visita"].startswith("2001-")
    assert bookings[0]["tipo_visita"] == "Visita di controllo"
    assert bookings[0]["importo"] == 80
    assert set(bookings[0]) == {"prenotazione_id", "slot_id", "specialita", "medico", "data_visita",
                                 "tipo_visita", "importo", "stato", "creata_il", "receipt_available"}
    assert env.loads == []


def test_patient_bookings_keep_receipt_download_scoped_to_issuing_session(env):
    session = login(env)
    another_session = login(env)
    base = f"/api/sessions/{session}"
    env.client.post(base + "/messages", json={"message": "prenota"})
    env.client.post(base + "/confirm", json={"answer": "si"})
    own = env.client.get(base + "/bookings").json()["bookings"]
    other = env.client.get(f"/api/sessions/{another_session}/bookings").json()["bookings"]
    assert [booking["prenotazione_id"] for booking in own] == [booking["prenotazione_id"] for booking in other]
    assert {booking["prenotazione_id"]: booking["receipt_available"] for booking in own} == {2: True, 1: False}
    assert all(not booking["receipt_available"] for booking in other)
    assert env.client.get(f"/api/sessions/{another_session}/receipt/2").status_code == 404


def test_patient_bookings_require_active_session_and_handle_empty_patient(env):
    assert env.client.get("/api/sessions/unknown/bookings").status_code == 404
    session = login(env, "VRDLGU85B02A662Y")
    assert env.client.get(f"/api/sessions/{session}/bookings").json() == {"bookings": []}
    assert env.client.delete(f"/api/sessions/{session}").status_code == 200
    assert env.client.get(f"/api/sessions/{session}/bookings").status_code == 404
    assert env.loads == []


def test_patient_bookings_reject_concurrent_operation_and_release_lock(env):
    session = login(env)
    lock = env.app.state.sessions[session].lock
    lock.acquire()
    try:
        response = env.client.get(f"/api/sessions/{session}/bookings")
        assert response.status_code == 409
    finally:
        lock.release()
    assert env.client.get(f"/api/sessions/{session}/bookings").status_code == 200


def test_receipt_anchors_remain_at_confirmation_after_two_bookings_and_followups(env):
    session = login(env)
    base = f"/api/sessions/{session}"
    env.client.post(base + "/messages", json={"message": "prenota"})
    first = env.client.post(base + "/confirm", json={"answer": "si"}).json()
    first_anchor = first["messages"][-1]["id"]
    first_followup = env.client.post(base + "/messages", json={"message": "Quali documenti porto?"}).json()["messages"][-1]["id"]
    env.graph.slot_id = 10
    env.client.post(base + "/messages", json={"message": "prenota"})
    second = env.client.post(base + "/confirm", json={"answer": "si"}).json()
    second_anchor = second["messages"][-1]["id"]
    last_followup = env.client.post(base + "/messages", json={"message": "Come posso pagare?"}).json()["messages"][-1]["id"]
    snapshot = env.client.get(base).json()
    assert snapshot["receipt_anchors"] == {"2": first_anchor, "3": second_anchor}
    assert first["receipt_anchor"] == first_anchor
    assert second["receipt_anchor"] == second_anchor
    ids = [message["id"] for message in snapshot["messages"]]
    assert ids.index(first_anchor) < ids.index(first_followup) < ids.index(second_anchor) < ids.index(last_followup)
    assert [receipt["prenotazione_id"] for receipt in snapshot["receipts"]] == [2, 3]


@pytest.mark.parametrize("operation", ["message", "snapshot", "logout", "bookings"])
def test_session_deleted_between_lookup_and_lock_cannot_be_used(env, operation):
    session_id = login(env)
    session = env.app.state.sessions[session_id]

    class DeletedDuringAcquire:
        released = False

        def acquire(self, blocking=False):
            # Another request completed DELETE after get_session returned but
            # before this request could take the session lock.
            env.app.state.sessions.pop(session_id, None)
            return True

        def release(self):
            self.released = True

    session.lock = DeletedDuringAcquire()
    base = f"/api/sessions/{session_id}"
    if operation == "message":
        response = env.client.post(base + "/messages", json={"message": "prenota"})
    elif operation == "snapshot":
        response = env.client.get(base)
    elif operation == "bookings":
        response = env.client.get(base + "/bookings")
    else:
        response = env.client.delete(base)
    assert response.status_code == 404
    assert session.lock.released
    assert env.loads == []
    assert session_id not in env.app.state.sessions


def streaming_events(response):
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/x-ndjson')
    assert response.headers['cache-control'] == 'no-store'
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def enable_custom_stream(env):
    states = {}
    calls = []

    def stream(payload, config, *, stream_mode, subgraphs):
        calls.append((stream_mode, subgraphs))
        yield (), 'custom', {'avanzamento': 'Sto capendo la richiesta...'}
        # Events from a nested agent have a namespace and must also reach the UI.
        yield ('agente_info:1',), 'custom', {'avanzamento': 'Sto cercando nella Carta dei Servizi...'}
        yield (), 'custom', {'avanzamento': 42}
        result = env.graph.invoke(payload, config)
        states[config['configurable']['thread_id']] = SimpleNamespace(
            values={'messages': result['messages']},
            interrupts=tuple(result.get('__interrupt__', ())),
        )

    env.graph.stream = stream
    env.graph.get_state = lambda config: states[config['configurable']['thread_id']]
    return calls


def test_custom_stream_delivers_progress_then_final_answer_and_snapshot(env):
    calls = enable_custom_stream(env)
    session = login(env)
    base = f'/api/sessions/{session}'
    events = streaming_events(env.client.post(base + '/messages/stream', json={'message': 'Quali documenti porto?'}))
    assert [event['type'] for event in events] == ['progress', 'progress', 'result']
    assert events[0]['message'] == 'Sto capendo la richiesta...'
    assert events[1]['message'] == 'Sto cercando nella Carta dei Servizi...'
    result = events[-1]['data']
    assert result['messages'][-1]['content'] == 'Informazione dal documento.'
    assert result['pending'] is None
    assert env.client.get(base).json()['messages'][-1] == result['messages'][-1]
    assert calls == [(['custom'], True)]


def test_custom_stream_recovers_interrupt_from_snapshot_and_commits_after_confirmation(env):
    enable_custom_stream(env)
    session = login(env)
    base = f'/api/sessions/{session}'
    pending = streaming_events(env.client.post(base + '/messages/stream', json={'message': 'prenota'}))[-1]['data']
    assert pending['pending']['id'] == 'confirm-1'
    assert pending['receipt'] is None
    with sqlite3.connect(env.database) as conn:
        assert conn.execute('SELECT count(*) FROM prenotazioni').fetchone()[0] == 1
    events = streaming_events(env.client.post(base + '/confirm/stream', json={'answer': 'si'}))
    result = events[-1]['data']
    assert result['pending'] is None
    assert result['receipt']['prenotazione_id'] == 2
    assert env.client.get(base + '/receipt/2').status_code == 200
    assert result['preferences']['medico'] == 'Laura Bianchi'


def test_custom_stream_error_is_sanitized_and_preserves_pending_and_unlocks(env):
    enable_custom_stream(env)
    session = login(env)
    base = f'/api/sessions/{session}'
    streaming_events(env.client.post(base + '/messages/stream', json={'message': 'prenota'}))
    env.graph.fail_next = True
    events = streaming_events(env.client.post(base + '/confirm/stream', json={'answer': 'si'}))
    assert [e['type'] for e in events] == ['progress', 'progress', 'error']
    assert events[-1]['status'] == 503
    assert 'Ollama unavailable' not in events[-1]['detail']
    restored = env.client.get(base)
    assert restored.status_code == 200
    assert restored.json()['pending']['id'] == 'confirm-1'
    result = streaming_events(env.client.post(base + '/confirm/stream', json={'answer': 'no'}))[-1]['data']
    assert result['pending'] is None
    assert result['receipt'] is None


def test_stream_auth_validation_conflicts_and_json_fallback(env):
    assert env.client.post('/api/sessions/unknown/messages/stream', json={'message': 'ciao'}).status_code == 404
    session = login(env)
    base = f'/api/sessions/{session}'
    assert env.client.post(base + '/messages/stream', json={'message': ' '}).status_code == 422
    assert env.client.post(base + '/confirm/stream', json={'answer': ''}).status_code == 422
    lock = env.app.state.sessions[session].lock
    lock.acquire()
    try:
        events = streaming_events(env.client.post(base + '/messages/stream', json={'message': 'ciao'}))
        assert events == [{'type': 'error', 'detail': "L'assistente sta già elaborando una richiesta. Attendi la risposta.", 'status': 409}]
    finally:
        lock.release()
    # Alternate runtimes without custom stream support retain the JSON behavior.
    events = streaming_events(env.client.post(base + '/messages/stream', json={'message': 'ciao'}))
    assert [e['type'] for e in events] == ['result']
    assert events[0]['data']['messages'][-1]['content'] == 'Informazione dal documento.'


def test_stream_recovers_receipt_if_model_fails_after_commit(env):
    enable_custom_stream(env)
    session = login(env)
    base = f'/api/sessions/{session}'
    streaming_events(env.client.post(base + '/messages/stream', json={'message': 'prenota'}))
    env.graph.fail_after_commit = True
    events = streaming_events(env.client.post(base + '/confirm/stream', json={'answer': 'si'}))
    assert events[-1]['type'] == 'result'
    assert events[-1]['data']['receipt']['prenotazione_id'] == 2
    assert events[-1]['data']['pending'] is None
    assert env.client.post(base + '/confirm', json={'answer': 'si'}).status_code == 409


def test_future_bookings_match_cli_scope_are_patient_isolated_and_chronological(env):
    session = login(env)
    with sqlite3.connect(env.database) as conn:
        conn.execute("UPDATE slot SET data_ora = '2001-11-03 09:00' WHERE id = 1")
        conn.execute("INSERT INTO prenotazioni (paziente_id,slot_id,tipo_visita,importo) VALUES (1,10,'Prima visita',120)")
        conn.execute("INSERT INTO prenotazioni (paziente_id,slot_id,tipo_visita,importo) VALUES (1,5,'Prima visita',120)")
        conn.execute("INSERT INTO prenotazioni (paziente_id,slot_id,tipo_visita,importo,stato) VALUES (1,7,'Prima visita',100,'annullata')")
        conn.execute("INSERT INTO prenotazioni (paziente_id,slot_id,tipo_visita,importo) VALUES (2,11,'Prima visita',100)")
    base = f'/api/sessions/{session}/bookings'
    result = env.client.get(base, params={'scope': 'future'})
    assert result.status_code == 200
    bookings = result.json()['bookings']
    assert [b['prenotazione_id'] for b in bookings] == [3, 2]
    assert all(b['stato'] == 'confermata' for b in bookings)
    assert [b['data_visita'] for b in bookings] == sorted(b['data_visita'] for b in bookings)
    assert len(env.client.get(base).json()['bookings']) == 4
    assert env.client.get(base, params={'scope': 'arbitrary'}).status_code == 422
    assert env.loads == []


def test_progress_arrives_before_completion_and_disconnecting_does_not_cancel_graph(env):
    session_id = login(env)
    session = env.app.state.sessions[session_id]
    continue_graph = threading.Event()
    states = {}

    def stream(payload, config, **_kwargs):
        yield (), 'custom', {'avanzamento': 'Sto cercando gli orari...'}
        assert continue_graph.wait(4)
        result = env.graph.invoke(payload, config)
        states[config['configurable']['thread_id']] = SimpleNamespace(
            values={'messages': result['messages']}, interrupts=tuple(result.get('__interrupt__', ())))

    env.graph.stream = stream
    env.graph.get_state = lambda config: states[config['configurable']['thread_id']]
    endpoint = next(route.endpoint for route in env.app.routes
                    if getattr(route, 'path', None) == '/api/sessions/{session_id}/messages/stream')
    response = endpoint(session_id, MessageBody(message='prenota'))

    async def receive_one_then_disconnect():
        first = await asyncio.wait_for(anext(response.body_iterator), timeout=2)
        assert json.loads(first) == {'type': 'progress', 'message': 'Sto cercando gli orari...'}
        assert session.lock.locked()
        assert session.pending is None
        # Closing the HTTP consumer must not cancel the worker, since an
        # already submitted confirmation could have committed to SQLite.
        await response.body_iterator.aclose()

    try:
        asyncio.run(receive_one_then_disconnect())
    finally:
        continue_graph.set()
    assert session.lock.acquire(timeout=2)
    try:
        assert session.pending['id'] == 'confirm-1'
    finally:
        session.lock.release()
    assert env.client.get(f'/api/sessions/{session_id}').status_code == 200
