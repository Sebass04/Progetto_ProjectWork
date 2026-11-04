from pathlib import Path

from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_core.messages import SystemMessage
from langchain_chroma import Chroma
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.config import get_stream_writer
from config import get_llm, get_embeddings

cartella = Path(__file__).parent
percorso_pdf = cartella / "data" / "carta_servizi_poliambulatorio.pdf"

titoli_sezioni = [
    "Avvertenza importante",
    "Orari",
    "Specialità e tariffe (prestazioni private)",
    "Preparazione agli esami",
    "Documenti necessari",
    "Disdette",
    "Pagamenti e referti",
]

# un chunk per sezione: così la citazione indica una sezione vera e i paragrafi non vengono spezzati
testo_pdf = ""
for pagina in PdfReader(percorso_pdf).pages:
    testo_pdf = testo_pdf + pagina.extract_text() + "\n"

sezioni = []
sezione_corrente = None
righe_correnti = []
for riga in testo_pdf.splitlines():
    if riga.strip() in titoli_sezioni:
        if sezione_corrente is not None:
            sezioni.append(Document(page_content="\n".join(righe_correnti), metadata={"sezione": sezione_corrente}))
        sezione_corrente = riga.strip()
        righe_correnti = []
    elif sezione_corrente is not None:
        righe_correnti.append(riga)
if sezione_corrente is not None:
    sezioni.append(Document(page_content="\n".join(righe_correnti), metadata={"sezione": sezione_corrente}))

# se un titolo non viene riconosciuto ci si ferma subito, invece di perdere una sezione in silenzio
assert len(sezioni) == len(titoli_sezioni), f"Trovate {len(sezioni)} sezioni su {len(titoli_sezioni)}"

# l'indice si crea solo la prima volta (se cambi il PDF, cancella la cartella chroma_db)
vectorstore = Chroma(
    collection_name="carta_servizi",
    embedding_function=get_embeddings(),
    persist_directory=str(cartella / "chroma_db"),
)
if len(vectorstore.get()["ids"]) == 0:
    vectorstore.add_documents(sezioni, ids=[f"sezione-{numero}" for numero in range(len(sezioni))])
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

llm = get_llm()

system_prompt = (
    "Sei l'assistente virtuale informativo del Poliambulatorio Salus Levante. "
    "Rispondi alla domanda del paziente utilizzando **unicamente** i contesti estratti dalla Carta dei Servizi qui sotto.\n"
    "Se l'informazione non è presente nel documento, di' chiaramente che non la trovi, "
    "senza inventare orari, tariffe o regole (evita assolutamente allucinazioni).\n"
    "Cita sempre la sezione o il riferimento del documento da cui prendi l'informazione.\n\n"
    "Contesto:\n{context}"
)


def formatta_documenti(documenti):
    blocchi = []
    for documento in documenti:
        blocchi.append(f"[Sezione: {documento.metadata['sezione']}]\n{documento.page_content}")
    return "\n\n".join(blocchi)


# ---------- Agente Info: piccolo sottografo recupera -> genera ----------
class StatoInfo(MessagesState):
    contesto: str


def messaggi_di_testo(stato):
    # tiene solo i messaggi di testo (niente tool call o ToolMessage)
    return [m for m in stato["messages"] if m.type in ("human", "ai") and m.content]


def recupera(stato: StatoInfo) -> dict:
    # uso le ultime due domande, così "e per la dermatologia?" ha ancora senso
    domande = [m.content for m in messaggi_di_testo(stato) if m.type == "human"]
    scrittore = get_stream_writer()
    scrittore({"avanzamento": "Sto cercando nella Carta dei Servizi..."})
    documenti = retriever.invoke(" ".join(domande[-2:]))
    return {"contesto": formatta_documenti(documenti)}


def genera(stato: StatoInfo) -> dict:
    istruzioni = system_prompt.replace("{context}", stato["contesto"])
    risposta = llm.invoke([SystemMessage(istruzioni)] + messaggi_di_testo(stato)[-5:])
    return {"messages": [risposta]}


costruttore_info = StateGraph(StatoInfo)
costruttore_info.add_node("recupera", recupera)
costruttore_info.add_node("genera", genera)
costruttore_info.add_edge(START, "recupera")
costruttore_info.add_edge("recupera", "genera")
costruttore_info.add_edge("genera", END)
agente_info = costruttore_info.compile()


# ---------- Preparazione alla visita (per la ricevuta) ----------
etichette_visite = {
    "Cardiologia": "Visita cardiologica",
    "Dermatologia": "Visita dermatologica",
    "Ortopedia": "Visita ortopedica",
    "Oculistica": "Visita oculistica",
    "Nutrizione": "Visita nutrizionale",
}


def cerca_preparazione(specialita):
    fonte = "Carta dei Servizi, sezione Preparazione agli esami"
    nessuna = {"frasi": ["Nessuna preparazione indicata"], "fonte": fonte}
    etichetta = etichette_visite.get(specialita)
    if etichetta is None:
        return nessuna

    # leggo la sezione direttamente, senza passare dalla ricerca per similarità
    testo = ""
    for documento in sezioni:
        if documento.metadata["sezione"] == "Preparazione agli esami":
            testo = " ".join(documento.page_content.split())
    inizio = testo.find(etichetta)
    if inizio == -1:
        return nessuna

    resto = testo[inizio + len(etichetta):]
    fine = resto.find("Visita ")
    if fine != -1:
        resto = resto[:fine]
    resto = resto[resto.find(":") + 1:]

    frasi = []
    for parte in resto.split(";"):
        frase = parte.strip().rstrip(".")
        if frase != "":
            frasi.append(frase[0].upper() + frase[1:])
    return {"frasi": frasi, "fonte": fonte}