import os
from langchain_ollama import ChatOllama, OllamaEmbeddings

# Modello per la chat e gli agenti
MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:latest")

# Modello per gli embedding del RAG
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3:latest")

# Indirizzo del server Ollama
BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


def get_llm(temperature: float = 0) -> ChatOllama:
    return ChatOllama(
        model=MODEL,
        temperature=temperature,
        base_url=BASE_URL
    )


def get_embeddings() -> OllamaEmbeddings:
    return OllamaEmbeddings(
        model=EMBED_MODEL,
        base_url=BASE_URL
    )