from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from config import get_llm
from booking import agente_booking, trova_paziente
from rag import agente_info

llm = get_llm()


class Stato(MessagesState):
    intento: str


# ---------- Guardrail sanitario (nel codice, prima del router) ----------
parole_urgenza = [
    "dolore al petto", "dolore toracico", "male al petto", "non riesco a respirare", "non respiro",
    "difficoltà a respirare", "difficolta a respirare", "svenuto", "svenuta", "svenimento",
    "sto per svenire", "perdita di coscienza", "ho perso conoscenza", "infarto", "ictus", "emergenza",
]

parole_diagnosi = [
    "mi fai una diagnosi", "fammi una diagnosi", "che malattia ho", "quale farmaco devo prendere",
    "che medicina devo prendere", "che farmaco", "che medicina",
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
- booking: prenotare una visita, scegliere data, orario o slot, rispondere alle domande della prenotazione.
- diagnosi: sintomi, malattie, richieste di diagnosi o di consigli medici.
- altro: saluti e tutto il resto.
Se la conversazione è una prenotazione in corso, scegli booking."""


def router(stato: Stato) -> dict:
    # solo messaggi di testo: i ToolMessage dell'agente Booking confondono il router
    solo_testo = [m for m in stato["messages"] if m.type in ("human", "ai") and m.content]
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

grafo = costruttore.compile(checkpointer=InMemorySaver())


def salva_diagramma():
    # per la consegna: grafo.md con il diagramma Mermaid (da copiare anche nel README)
    mermaid = grafo.get_graph().draw_mermaid()
    (Path(__file__).parent / "grafo.md").write_text("```mermaid\n" + mermaid + "\n```\n", encoding="utf-8")


# ---------- Chat da terminale ----------
def mostra_riepilogo(riepilogo):
    for chiave in riepilogo:
        if chiave != "domanda":
            print(f"   {chiave}: {riepilogo[chiave]}")


def chat():
    codice_fiscale = input("Codice fiscale: ").strip().upper()
    paziente = trova_paziente(codice_fiscale)
    if paziente is None:
        print("Codice fiscale non trovato: rivolgersi all'accettazione.")
        return

    config = {"configurable": {"thread_id": codice_fiscale}}
    print(f"Benvenuto {paziente['nome']}. Scrivi /esci per terminare.")

    while True:
        testo = input("Tu: ")
        if testo == "/esci":
            print("Arrivederci!")
            break

        risultato = grafo.invoke({"messages": [("user", testo)]}, config)

        while "__interrupt__" in risultato:
            risposte = {}
            for richiesta in risultato["__interrupt__"]:
                print("Riepilogo della prenotazione:")
                mostra_riepilogo(richiesta.value)
                risposta = input(richiesta.value["domanda"] + " ")
                if risposta == "/esci":
                    print("Arrivederci!")
                    return
                risposte[richiesta.id] = risposta
            risultato = grafo.invoke(Command(resume=risposte), config)

        print("Assistente:", risultato["messages"][-1].content)


if __name__ == "__main__":
    salva_diagramma()
    chat()