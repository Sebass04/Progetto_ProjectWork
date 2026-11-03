import json
import sqlite3
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain.agents import create_agent
from langgraph.types import interrupt
from config import get_llm
from db import apri_connessione, crea_database, percorso_db
from rag import cerca_preparazione

llm = get_llm()

if not percorso_db.exists():
    crea_database()

cartella_ricevute = Path(__file__).parent / "ricevute"

giorni_settimana = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
risposte_si = ["sì", "si", "s", "ok", "confermo", "conferma", "yes"]

def mostra_data(data_ora):
    return datetime.fromisoformat(data_ora).strftime("%d-%m-%Y %H:%M")


def trova_specialita(nome):
    connessione = apri_connessione()
    riga = connessione.execute(
        "SELECT * FROM specialita WHERE lower(nome) = lower(?)", (nome.strip(),)
    ).fetchone()
    connessione.close()
    if riga is None:
        return None
    return dict(riga)

def errore_specialita(nome):
    # se la specialità non esiste, dice all'LLM quali sono quelle valide
    if trova_specialita(nome) is not None:
        return None
    connessione = apri_connessione()
    righe = connessione.execute("SELECT nome FROM specialita ORDER BY id").fetchall()
    connessione.close()
    nomi = []
    for riga in righe:
        nomi.append(riga["nome"])
    return f"Errore: specialità '{nome}' non valida. Specialità disponibili: " + ", ".join(nomi) + "."


def trova_paziente(codice_fiscale):
    connessione = apri_connessione()
    riga = connessione.execute(
        "SELECT id, nome, codice_fiscale FROM pazienti WHERE codice_fiscale = ?", (codice_fiscale,)
    ).fetchone()
    connessione.close()
    if riga is None:
        return None
    return dict(riga)


query_slot = """
    SELECT slot.id AS slot_id, medici.nome AS medico, specialita.nome AS specialita,
           slot.data_ora AS data_ora, slot.libero AS libero
    FROM slot
    JOIN medici ON medici.id = slot.medico_id
    JOIN specialita ON specialita.id = medici.specialita_id
"""


def trova_slot(slot_id):
    connessione = apri_connessione()
    riga = connessione.execute(query_slot + " WHERE slot.id = ?", (slot_id,)).fetchone()
    connessione.close()
    if riga is None:
        return None
    return dict(riga)


def cerca_medici_dati(specialita):
    connessione = apri_connessione()
    righe = connessione.execute(
        """SELECT medici.id AS id, medici.nome AS nome, specialita.nome AS specialita
           FROM medici JOIN specialita ON specialita.id = medici.specialita_id
           WHERE lower(specialita.nome) = lower(?)""",
        (specialita.strip(),),
    ).fetchall()
    connessione.close()
    risultati = []
    for riga in righe:
        risultati.append(dict(riga))
    return risultati


def cerca_slot_liberi_dati(specialita, data):
    adesso = datetime.now().strftime("%Y-%m-%d %H:%M")
    connessione = apri_connessione()
    righe = connessione.execute(
        query_slot + """ WHERE lower(specialita.nome) = lower(?)
                         AND slot.data_ora LIKE ?
                         AND slot.libero = 1
                         AND slot.data_ora > ?
                         ORDER BY slot.data_ora""",
        (specialita.strip(), data + "%", adesso),
    ).fetchall()
    connessione.close()
    risultati = []
    for riga in righe:
        risultati.append(dict(riga))
    return risultati


def registra_prenotazione(paziente_id, slot_id, tipo_visita, importo):
    # slot occupato e prenotazione inserita nella stessa transazione: o tutte e due o nessuna
    connessione = apri_connessione()
    try:
        with connessione:
            cursore = connessione.execute(
                "UPDATE slot SET libero = 0 WHERE id = ? AND libero = 1", (slot_id,)
            )
            if cursore.rowcount == 0:
                return {"errore": "slot non disponibile"}
            cursore = connessione.execute(
                "INSERT INTO prenotazioni (paziente_id, slot_id, tipo_visita, importo) VALUES (?, ?, ?, ?)",
                (paziente_id, slot_id, tipo_visita, importo),
            )
            prenotazione_id = cursore.lastrowid
        riga = connessione.execute(
            "SELECT id, stato, creato_il FROM prenotazioni WHERE id = ?", (prenotazione_id,)
        ).fetchone()
        return dict(riga)
    except sqlite3.Error as errore:
        return {"errore": str(errore)}
    finally:
        connessione.close()


def salva_ricevuta(ricevuta):
    cartella_ricevute.mkdir(exist_ok=True)
    percorso = cartella_ricevute / f"ricevuta_{ricevuta['prenotazione_id']:03d}.json"
    percorso.write_text(json.dumps(ricevuta, indent=4, ensure_ascii=False), encoding="utf-8")
    return percorso


def data() -> str:
    """Restituisce la data di oggi (GG-MM-AAAA) e il giorno della settimana.
        Da usare quando il paziente dice 'domani', 'lunedi prossimo', 'la settimana prossima' e simili"""
    adesso = datetime.now()
    return f"Oggi è {giorni_settimana[adesso.weekday()]} {adesso.strftime('%d-%m-%Y')}."


@tool
def cerca_medici(specialita: str) -> str:
    """Cerca i medici di una specialità (Cardiologia, Dermatologia, Ortopedia, Oculistica, Nutrizione)."""
    errore = errore_specialita(specialita)
    if errore is not None:
        return errore
    medici = cerca_medici_dati(specialita)
    righe = []
    for medico in medici:
        righe.append(f"- {medico['nome']} ({medico['specialita']})")
    return "\n".join(righe)


@tool
def cerca_slot_liberi(specialita: str, data: str) -> str:
    """Cerca gli orari liberi per una specialità in una data nel formato GG-MM-AAAA."""
    try:
        giorno = datetime.strptime(data, "%d-%m-%Y")
    except ValueError:
        return "Errore: la data deve essere nel formato GG-MM-AAAA, per esempio 03-11-2026."
    errore = errore_specialita(specialita)
    if errore is not None:
        return errore
    slot_liberi = cerca_slot_liberi_dati(specialita, giorno.strftime("%Y-%m-%d"))
    if len(slot_liberi) == 0:
        return f"Nessun orario libero per {specialita} il {giorno.strftime('%d-%m-%Y')}."
    righe = []
    for slot in slot_liberi:
        righe.append(f"- slot {slot['slot_id']}: {mostra_data(slot['data_ora'])} con {slot['medico']}")
    return "\n".join(righe)


@tool
def prenota_visita(slot_id: int, tipo_visita: str, config: RunnableConfig) -> str:
    """Prenota lo slot scelto dal paziente. tipo_visita deve essere 'prima' oppure 'controllo'.
    Chiede sempre la conferma al paziente prima di registrare."""
    # il codice fiscale arriva dal thread della conversazione, non dall'LLM
    codice_fiscale = config["configurable"]["thread_id"].strip().upper()
    paziente = trova_paziente(codice_fiscale)
    if paziente is None:
        return "Errore: paziente non registrato. Rivolgersi all'accettazione."

    tipo_visita = tipo_visita.strip().lower()
    if tipo_visita == "prima":
        descrizione_visita = "Prima visita"
    elif tipo_visita == "controllo":
        descrizione_visita = "Visita di controllo"
    else:
        return "Errore: il tipo di visita deve essere 'prima' oppure 'controllo'."

    slot = trova_slot(slot_id)
    if slot is None:
        return f"Errore: lo slot {slot_id} non esiste."
    if slot["libero"]:
        giorno = slot["data_ora"][:10]
        altri_slot = cerca_slot_liberi_dati(slot["specialita"], giorno)
        if len(altri_slot) == 0:
            return f"Errore: lo slot {slot_id} è già occupato e non ci sono altri orari liberi quel giorno."
        righe = []
        for altro in altri_slot:
            righe.append(f"- slot {altro['slot_id']}: {mostra_data(altro['data_ora'])} con {altro['medico']}")
        return f"Errore: lo slot {slot_id} è già occupato. Orari liberi aggiornati:\n" + "\n".join(righe)

    if datetime.fromisoformat(slot["data_ora"]) <= datetime.now():
        return "Errore: non si può prenotare una data passata."

    specialita = trova_specialita(slot["specialita"])
    if tipo_visita == "prima":
        importo = specialita["costo_prima_visita"]
    else:
        importo = specialita["costo_controllo"]

    preparazione = cerca_preparazione(slot["specialita"])

    # il grafo si ferma qui: le scritture avvengono solo dopo la conferma
    risposta = interrupt({
        "domanda": "Confermi la prenotazione? (si/no)",
        "paziente": paziente["nome"],
        "medico": slot["medico"],
        "specialita": slot["specialita"],
        "data_visita": mostra_data(slot["data_ora"]),
        "tipo_visita": descrizione_visita,
        "importo_euro": importo,
        "preparazione": preparazione["frasi"],
    })

    if str(risposta).strip().lower() != "si":
        return ("Prenotazione NON registrata: il paziente non ha confermato. "
                "Non dire che la visita è prenotata e non richiamare prenota_visita: "
                "chiedi al paziente se vuole scegliere un altro orario.")

    prenotazione = registra_prenotazione(paziente["id"], slot_id, descrizione_visita, importo)
    if "errore" in prenotazione:
        return "Errore durante la registrazione: " + prenotazione["errore"]

    ricevuta = {
        "prenotazione_id": prenotazione["id"],
        "paziente_id": paziente["id"],
        "slot_id": slot_id,
        "specialita": slot["specialita"],
        "medico": slot["medico"],
        "data_visita": slot["data_ora"],
        "tipo_visita": descrizione_visita,
        "importo": importo,
        "stato": prenotazione["stato"],
        "preparazione": preparazione["frasi"],
        "fonte_preparazione": preparazione["fonte"],
        "creata_il": prenotazione["creato_il"],
    }
    percorso = salva_ricevuta(ricevuta)

    return f"Prenotazione confermata. Ricevuta salvata in ricevute/{percorso.name}:\n" + json.dumps(ricevuta, indent=2, ensure_ascii=False)


prompt_booking = """Sei l'assistente prenotazioni del Poliambulatorio Salus Levante.
Per prenotare servono: specialità, data (GG-MM-AAAA), tipo di visita (prima o controllo) e lo slot scelto dal paziente.
Se manca uno di questi dati, chiedilo al paziente prima di usare i tool.
Se il paziente dice "domani", "lunedì prossimo" o simili, usa prima data_di_oggi per calcolare la data
Usa SEMPRE cerca_slot_liberi prima di proporre degli orari.
Quando mostri gli orari, scrivi sempre il numero dello slot (per esempio "slot 3: 04-11-2026 09:00").
Quando il paziente indica lo slot da prenotare, chiama SUBITO prenota_visita con quello slot:
è prenota_visita che mostra il riepilogo e chiede la conferma al paziente, tu non devi chiederla.
Chiama prenota_visita una sola volta per richiesta.
Non inventare mai medici, orari, prezzi o disponibilità: usa solo i risultati dei tool.
Non chiedere il codice fiscale: il sistema lo conosce già.
Non dare consigli medici. Rispondi sempre in italiano."""

agente_booking = create_agent(
    model=llm,
    tools=[cerca_medici, cerca_slot_liberi, prenota_visita],
    system_prompt=prompt_booking,
)