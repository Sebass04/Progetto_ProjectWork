from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.config import get_stream_writer
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from config import get_llm
from booking import agente_booking, trova_paziente, leggi_preferenze, prenotazioni_future_dati, mostra_data
from rag import agente_info

llm = get_llm()


class Stato(MessagesState):
    intento: str


# ---------- Guardrail sanitario (nel codice, prima del router) ----------
parole_urgenza = [
    "dolore al petto", "dolore toracico", "male al petto", "non riesco a respirare", "non respiro",
    "difficoltà a respirare", "difficolta a respirare", "svenuto", "svenuta", "svenimento",
    "sto per svenire", "perdita di coscienza", "ho perso conoscenza", "infarto", "ictus", "emergenza",
    "mi fa male il petto", "male il petto", "male al cuore", "mi fa male il cuore",
]

parole_diagnosi = [
    "mi fai una diagnosi", "fammi una diagnosi", "che malattia ho", "quale farmaco devo prendere",
    "che medicina devo prendere", "che farmaco devo prendere", "che farmaci devo prendere",
]

risposta_standard_112 = (
    "Non posso fornire diagnosi né consigli medici. "
    "In caso di dolore toracico, difficoltà respiratorie, perdita di coscienza o altre emergenze "
    "chiami immediatamente il 112. Se vuole, posso aiutarla a prenotare una visita."
)


def controlla_guardrail(stato: Stato) -> dict:
    testo = stato["messages"][-1].content.lower()
    for parola in parole_urgenza + parole_diagnosi:
        if parola in testo:
            return {"intento": "urgente"}
    return {"intento": ""}


def dopo_guardrail(stato: Stato) -> str:
    if stato["intento"] == "urgente":
        return "urgente"
    else:
        return "ok"


def risposta_112(stato: Stato) -> dict:
    return {"messages": [("ai", risposta_standard_112)]}


# ---------- Router con output strutturato ----------
class Rotta(BaseModel):
    intento: Literal["info", "booking", "diagnosi", "altro"] = Field(
        description="info = domande sulla carta dei servizi; booking = prenotare una visita; "
                    "diagnosi = sintomi o richieste di diagnosi; altro = tutto il resto"
    )


router_llm = llm.with_structured_output(Rotta)

prompt_router = """Classifica l'ultima richiesta del paziente di un poliambulatorio.
- info: orari, tariffe, documenti, preparazione alle visite, disdette, pagamenti, referti.
  Anche le domande su cosa portare o come prepararsi a una visita (per esempio farmaci da portare) sono info.
- Se il paziente chiede di prenotare o nomina un medico o uno specialista (per esempio "ho bisogno di un cardiologo"), è booking, 
  anche se in precedenza ha parlato di sintomi.
- booking: prenotare una visita, scegliere data, orario o slot, rispondere alle domande della prenotazione.
- diagnosi: sintomi, malattie, richieste di diagnosi o di consigli medici.
- altro: saluti e tutto il resto.
Se la conversazione è una prenotazione in corso, scegli booking."""


def router(stato: Stato) -> dict:
    # solo messaggi di testo: i ToolMessage dell'agente Booking confondono il router
    solo_testo = [m for m in stato["messages"] if m.type in ("human", "ai") and m.content]

    for numero in range(len(solo_testo)- 1, -1, -1):
        if solo_testo[numero].type == "ai" and solo_testo[numero].content == risposta_standard_112:
            solo_testo = solo_testo[numero + 1:]
            break

    scrittore = get_stream_writer()
    scrittore({"avanzamento": "Sto capendo la richiesta..."})
    rotta = router_llm.invoke([SystemMessage(prompt_router)] + solo_testo[-4:])
    return {"intento": rotta.intento}


def scegli_ramo(stato: Stato) -> str:
    return stato["intento"]


def risposta_cortesia(stato: Stato) -> dict:
    return {"messages": [("ai", "Sono l'assistente del Poliambulatorio Salus Levante: posso darle informazioni sulla carta dei servizi o aiutarla a prenotare una visita.")]}


# ---------- Grafo principale ----------
costruttore = StateGraph(Stato)
costruttore.add_node("controlla_guardrail", controlla_guardrail)
costruttore.add_node("router", router)
costruttore.add_node("risposta_112", risposta_112)
costruttore.add_node("agente_info", agente_info)
costruttore.add_node("agente_booking", agente_booking)
costruttore.add_node("risposta_cortesia", risposta_cortesia)

costruttore.add_edge(START, "controlla_guardrail")
costruttore.add_conditional_edges(
    "controlla_guardrail", dopo_guardrail,
    {"urgente": "risposta_112", "ok": "router"},
)
costruttore.add_conditional_edges(
    "router", scegli_ramo,
    {"info": "agente_info", "booking": "agente_booking", "diagnosi": "risposta_112", "altro": "risposta_cortesia"},
)
costruttore.add_edge("risposta_112", END)
costruttore.add_edge("agente_info", END)
costruttore.add_edge("agente_booking", END)
costruttore.add_edge("risposta_cortesia", END)

# checkpointer = memoria della singola conversazione; store = preferenze del paziente, condivise tra le conversazioni
memoria_preferenze = InMemoryStore()
grafo = costruttore.compile(checkpointer=InMemorySaver(), store=memoria_preferenze)


def salva_diagramma():
    # per la consegna: grafo.md con il diagramma Mermaid (da copiare anche nel README)
    mermaid = grafo.get_graph().draw_mermaid()
    (Path(__file__).parent / "grafo.md").write_text("```mermaid\n" + mermaid + "\n```\n", encoding="utf-8")


# ---------- Chat da terminale ----------
def mostra_riepilogo(riepilogo):
    for chiave in riepilogo:
        if chiave != "domanda":
            print(f"   {chiave}: {riepilogo[chiave]}")


def esegui(ingresso, config):
    # streaming custom: router, agente Info e tool del Booking mandano messaggi di avanzamento mentre lavorano;
    # subgraphs=True serve perché gli agenti sono sottografi e i loro messaggi altrimenti non arrivano qui
    for spazio, modalita, dato in grafo.stream(ingresso, config, stream_mode=["custom"], subgraphs=True):
        print("   ...", dato["avanzamento"])
    return grafo.get_state(config)


def mostra_prenotazioni(paziente):
    # letto dal database e non chiesto all'LLM: così l'elenco è sempre vero
    visite = prenotazioni_future_dati(paziente["id"])
    if len(visite) == 0:
        print("Non ha visite prenotate.")
    else:
        print("Le sue visite prenotate:")
        for visita in visite:
            print(f"   prenotazione {visita['prenotazione_id']}: {visita['specialita']} con {visita['medico']} "
                  f"il {mostra_data(visita['data_ora'])} ({visita['tipo_visita']})")


def conversazione(paziente, config):
    print(f"Benvenuto {paziente['nome']}. Scrivi /prenotazioni per vedere le sue visite, /esci per terminare la conversazione.")
    preferenze = leggi_preferenze(memoria_preferenze, paziente["codice_fiscale"])
    if preferenze is not None:
        print(f"Dalle visite precedenti: medico preferito {preferenze['medico']}, fascia preferita {preferenze['fascia']}.")

    while True:
        testo = input("Tu: ")
        if testo == "/esci":
            print("Arrivederci!")
            return
        if testo == "/prenotazioni":
            mostra_prenotazioni(paziente)
            continue

        stato = esegui({"messages": [("user", testo)]}, config)

        while len(stato.interrupts) > 0:
            risposte = {}
            for richiesta in stato.interrupts:
                print("Riepilogo della prenotazione:")
                mostra_riepilogo(richiesta.value)
                risposta = input(richiesta.value["domanda"] + " ")
                if risposta == "/esci":
                    print("Arrivederci!")
                    return
                risposte[richiesta.id] = risposta
            stato = esegui(Command(resume=risposte), config)

        print("Assistente:", stato.values["messages"][-1].content)


def chat():
    # come uno sportello: dopo /esci si torna al codice fiscale e ogni accesso è una conversazione nuova
    numero_conversazione = 0
    while True:
        codice_fiscale = input("Codice fiscale (/fine per chiudere il programma): ").strip().upper()
        if codice_fiscale == "/FINE":
            break
        paziente = trova_paziente(codice_fiscale)
        if paziente is None:
            print("Codice fiscale non trovato: rivolgersi all'accettazione.")
        else:
            numero_conversazione = numero_conversazione + 1
            config = {"configurable": {
                "thread_id": f"{codice_fiscale}-{numero_conversazione}",
                "codice_fiscale": codice_fiscale,
            }}
            conversazione(paziente, config)


if __name__ == "__main__":
    salva_diagramma()
    chat()