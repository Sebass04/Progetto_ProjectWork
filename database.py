
import json
from pathlib import Path

# Percorsi del progetto
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RICEVUTE_DIR = DATA_DIR / "ricevute"


def leggi_json(nome_file):
    """Legge un file JSON dalla cartella data."""
    percorso = DATA_DIR / nome_file

    with open(percorso, "r", encoding="utf-8") as file:
        return json.load(file)


def salva_json(nome_file, dati):
    """Salva i dati in un file JSON nella cartella data."""
    percorso = DATA_DIR / nome_file
    percorso.parent.mkdir(parents=True, exist_ok=True)

    with open(percorso, "w", encoding="utf-8") as file:
        json.dump(dati, file, ensure_ascii=False, indent=4)


def salva_ricevuta_file(ricevuta):
    """Crea un file JSON separato per ogni ricevuta."""
    RICEVUTE_DIR.mkdir(parents=True, exist_ok=True)

    numero = ricevuta["id"]
    nome_file = f"ricevuta_{numero:03d}.json"
    percorso = RICEVUTE_DIR / nome_file

    with open(percorso, "w", encoding="utf-8") as file:
        json.dump(ricevuta, file, ensure_ascii=False, indent=4)

    return str(percorso)

##if __name__ == "__main__":
 #   slot = leggi_json("slot.json")
#
 #   print("Slot caricati:")
 #   print(slot)

print(leggi_json("medici.json"))