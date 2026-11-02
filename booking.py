import json
from datetime import datetime
from pathlib import Path

from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain.agents import create_agent
from langgraph.types import interrupt
from config import get_llm

llm = get_llm()

cartella_dati = Path(__file__).parent / "data"

with open(cartella_dati / "specialita.json", encoding="utf-8") as file:
    specialita_lista = json.load(file)
with open(cartella_dati / "medici.json", encoding="utf-8") as file:
    medici_lista = json.load(file)
with open(cartella_dati / "slot.json", encoding="utf-8") as file:
    slot_lista = json.load(file)
with open(cartella_dati / "pazienti.json", encoding="utf-8") as file:
    pazienti_lista = json.load(file)
with open(cartella_dati / "prenotazioni.json", encoding="utf-8") as file:
    prenotazioni_lista = json.load(file)
with open(cartella_dati / "ricevute.json", encoding="utf-8") as file:
    ricevute_lista = json.load(file)


def mostra_data(data_ora):
    return datetime.fromisoformat(data_ora).strftime("%d-%m-%Y %H:%M")


def nome_specialita(specialita_id):
    for specialita in specialita_lista:
        if specialita["id"] == specialita_id:
            return specialita["nome"]
    return None


def trova_medico(medico_id):
    for medico in medici_lista:
        if medico["id"] == medico_id:
            return medico
    return None


def trova_specialita(nome):
    for specialita in specialita_lista:
        if specialita["nome"].lower() == nome.lower():
            return specialita
    return None


def trova_paziente(codice_fiscale):
    for paziente in pazienti_lista:
        if paziente["codice_fiscale"].upper() == codice_fiscale:
            return paziente
    return None


def trova_slot(slot_id):
    for slot in slot_lista:
        if slot["id"] == slot_id:
            medico = trova_medico(slot["medico_id"])
            if medico is None:
                return None
            specialita = nome_specialita(medico["specialita_id"])
            if specialita is None:
                return None
            return {
                "slot_id": slot["id"],
                "medico": medico["nome"],
                "specialita": specialita,
                "data_ora": slot["data_ora"] + "T" + slot["ora"],
                "libero": slot["libero"],
            }
    return None


def cerca_medici_dati(specialita):
    risultati = []
    for medico in medici_lista:
        nome = nome_specialita(medico["specialita_id"])
        if nome is not None and nome.lower() == specialita.lower():
            risultati.append({"id": medico["id"], "nome": medico["nome"], "specialita": nome})
    return risultati


def cerca_slot_liberi_dati(specialita, data):
    adesso = datetime.now()
    risultati = []
    for slot in slot_lista:
        dettagli = trova_slot(slot["id"])
        if dettagli is not None:
            stessa_specialita = dettagli["specialita"].lower() == specialita.lower()
            stesso_giorno = dettagli["data_ora"].startswith(data)
            futuro = datetime.fromisoformat(dettagli["data_ora"]) > adesso
            if stessa_specialita and stesso_giorno and dettagli["libero"] and futuro:
                risultati.append(dettagli)
    return risultati


# Funzioni finte, da sostituire con quelle della Persona 1 (registrazione e ricevuta)
# e della Persona 2 (RAG). Cambiano i dati solo in memoria: nessun file viene modificato.

preparazioni_finte = {
    "Cardiologia": "Portare elenco dei farmaci assunti ed eventuali ECG precedenti; evitare caffè nelle 3 ore precedenti.",
    "Dermatologia": "Mappatura nei: non applicare creme o trucco il giorno della visita.",
    "Ortopedia": "Portare referti di radiografie o risonanze già eseguite.",
    "Oculistica": "La dilatazione della pupilla può rendere difficoltosa la guida per alcune ore, si consiglia di farsi accompagnare.",
    "Nutrizione": "Presentarsi con esami del sangue recenti (non più vecchi di 6 mesi) e un diario alimentare di 3 giorni.",
}


def nuovo_id(lista):
    massimo = 0
    for elemento in lista:
        if elemento["id"] > massimo:
            massimo = elemento["id"]
    return massimo + 1


def registra_prenotazione(paziente_id, slot_id, tipo_visita):
    for slot in slot_lista:
        if slot["id"] == slot_id:
            if slot["libero"] == False:
                return {"errore": "slot non disponibile"}
            slot["libero"] = False
            prenotazione = {
                "id": nuovo_id(prenotazioni_lista),
                "paziente_id": paziente_id,
                "slot_id": slot_id,
                "tipo_visita": tipo_visita,
                "stato": "confermata",
            }
            prenotazioni_lista.append(prenotazione)
            return prenotazione
    return {"errore": "slot inesistente"}


def salva_ricevuta(ricevuta):
    ricevuta_completa = {"id": nuovo_id(ricevute_lista)}
    ricevuta_completa.update(ricevuta)
    ricevute_lista.append(ricevuta_completa)
    return ricevuta_completa


def cerca_preparazione(specialita):
    testo = preparazioni_finte.get(specialita, "Nessuna preparazione indicata.")
    frasi = []
    for parte in testo.split(";"):
        frasi.append(parte.strip().rstrip("."))
    return {"frasi": frasi, "fonte": "Carta dei Servizi, sezione Preparazione agli esami"}


@tool
def cerca_medici(specialita: str) -> str:
    """Cerca i medici di una specialità (Cardiologia, Dermatologia, Ortopedia, Oculistica, Nutrizione)."""
    medici = cerca_medici_dati(specialita)
    if len(medici) == 0:
        return f"Nessun medico trovato per la specialità '{specialita}'."
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
    if slot["libero"] == False:
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
        return "Prenotazione annullata: il paziente non ha confermato."

    prenotazione = registra_prenotazione(paziente["id"], slot_id, descrizione_visita)
    if "errore" in prenotazione:
        return "Errore durante la registrazione: " + prenotazione["errore"]

    ricevuta = salva_ricevuta({
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
    })

    return "Prenotazione confermata. Ricevuta:\n" + json.dumps(ricevuta, indent=2, ensure_ascii=False)


prompt_booking = """Sei l'assistente prenotazioni del Poliambulatorio Salus Levante.
Per prenotare servono: specialità, data (GG-MM-AAAA), tipo di visita (prima o controllo) e lo slot scelto dal paziente.
Se manca uno di questi dati, chiedilo al paziente prima di usare i tool.
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
