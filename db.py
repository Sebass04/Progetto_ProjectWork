import sqlite3
from pathlib import Path

cartella = Path(__file__).parent
percorso_db = cartella / "medibook.db"
percorso_schema = cartella / "schema.sql"


def apri_connessione():
    # le chiavi esterne vanno attivate a ogni connessione, altrimenti SQLite non le controlla
    connessione = sqlite3.connect(percorso_db)
    connessione.execute("PRAGMA foreign_keys = ON")
    connessione.row_factory = sqlite3.Row
    return connessione


def crea_database():
    schema = percorso_schema.read_text(encoding="utf-8")
    connessione = sqlite3.connect(percorso_db)
    connessione.executescript(schema)
    connessione.close()


if __name__ == "__main__":
    crea_database()
    print("Database creato:", percorso_db)
