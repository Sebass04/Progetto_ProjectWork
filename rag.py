from pathlib import Path

from pypdf import PdfReader
from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
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

vectorstore = Chroma.from_documents(
    documents=sezioni,
    embedding=get_embeddings(),
    collection_name="carta_servizi",
    persist_directory=str(cartella / "chroma_db"),
    ids=[f"sezione-{numero}" for numero in range(len(sezioni))],
)
retriever = vectorstore.as_retriever(search_kwargs={"k": 3})

system_prompt = (
    "Sei l'assistente virtuale informativo del Poliambulatorio Salus Levante. "
    "Rispondi alla domanda del paziente utilizzando **unicamente** i contesti estratti dalla Carta dei Servizi qui sotto.\n"
    "Se l'informazione non è presente nel documento, di' chiaramente che non la trovi, "
    "senza inventare orari, tariffe o regole (evita assolutamente allucinazioni).\n"
    "Cita sempre la sezione o il riferimento del documento da cui prendi l'informazione.\n\n"
    "Contesto:\n{context}"
)
prompt = ChatPromptTemplate.from_messages([
    ("system", system_prompt),
    ("human", "{input}"),
])
catena = prompt | get_llm() | StrOutputParser()


def formatta_documenti(documenti):
    blocchi = []
    for documento in documenti:
        blocchi.append(f"[Sezione: {documento.metadata['sezione']}]\n{documento.page_content}")
    return "\n\n".join(blocchi)


def rispondi_info(domanda):
    documenti = retriever.invoke(domanda)
    return catena.invoke({"context": formatta_documenti(documenti), "input": domanda})


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

    testo = ""
    for documento in retriever.invoke(f"Preparazione agli esami: {etichetta.lower()}"):
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
