PREPARAZIONE DELL'AMBIENTE VIRTUALE E DEI MODELLI DA USARE
1. Creare un venv:
    - python -m venv .venv
    - .venv\Scripts\activate

2. Dopo che il venv è stato creato fare questo comando per installare le librerie necessarie:
    - pip install -r requirements.txt

3. Setup del chatbot
    - Aprire il terminale e scrivere 'ollama list' per vedere i modelli scaricati
    - Nel caso in cui il modello da usare non è scaricato usare questo   comando: 
        - ollama pull <modello-chat> e ollama pull <modello-embedding>
    - Dopo aver scaricato i modelli, o se li hai già scaricati, nel terminale di VS code scrivere:
        - set OLLAMA_MODEL=<modello-chat>
        - set OLLAMA_EMBED_MODEL=<modello-embedding>

MODELLI DA USARE:
- MODELLO-CHAT: qwen2.5:latest
- MODELLO-EMBEDDING: bge-m3:latest
