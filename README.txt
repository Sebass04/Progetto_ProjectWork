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
    - Dopo aver scaricato i modelli, o se li hai già scaricati, nel terminale di VS code (PowerShell) scrivere:
        - $env:OLLAMA_MODEL="<modello-chat>"
        - $env:OLLAMA_EMBED_MODEL="<modello-embedding>"
      (nel Prompt dei comandi cmd invece: set OLLAMA_MODEL=<modello-chat>)
      Se non si imposta niente, config.py usa già qwen2.5:latest e bge-m3:latest.

4. Creare il database SQLite
    - python db.py
    - crea medibook.db a partire da schema.sql (se manca, viene creato anche in automatico al primo avvio)
    - se si modifica schema.sql bisogna rilanciare python db.py

5. Avviare l'assistente
    - python main.py (chiede il codice fiscale del paziente)
    - /esci chiude la conversazione e si torna al codice fiscale: ogni accesso è una conversazione nuova
    - /fine al posto del codice fiscale chiude il programma
    - preferenze del paziente (Store): dopo ogni prenotazione confermata vengono salvati il medico e la fascia
      oraria (mattina o pomeriggio) di quella prenotazione, al posto dei precedenti; al nuovo accesso dello
      stesso paziente vengono mostrati e negli orari liberi sono segnati "medico preferito" e "fascia preferita"
    - le preferenze sono in memoria (InMemoryStore): chiudendo il programma si perdono

MODELLI DA USARE:
- MODELLO-CHAT: qwen2.5:latest
- MODELLO-EMBEDDING: bge-m3:latest
