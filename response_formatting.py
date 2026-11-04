"""Small deterministic finishing rules for informational answers."""

import re
import unicodedata


INVITO_DURATA = (
    "Vuoi sapere la durata delle visite? "
    "chiedimi di tutte o una nello specifico."
)

_PREZZO = re.compile(r"\b(?:tariff[ae]|prezz[oi]|cost[oi]|costa(?:no)?|import[oi])\b")
_IMPORTO = re.compile(r"(?:\b\d+(?:[.,]\d{1,2})?\s*(?:€|euro\b|eur\b)|€\s*\d+)")
_VISITA = re.compile(
    r"\b(?:visit[ae]|controll[oi]|cardiolog\w*|dermatolog\w*|ortoped\w*|oculistic\w*|nutrizion\w*)\b"
)
_DURATA = re.compile(r"\b(?:durat[ae]|dura(?:no)?|quanto tempo)\b")
_ALTRE_INFO = re.compile(
    r"\b(?:refert[oi]|pagament[oi]|pagare|pago|document[oi]|portare|prepar\w*|disdett[ae]|"
    r"disdire|annull\w*|penal\w*|ticket|esenzion\w*)\b"
)


def _normalizza(testo: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", testo.casefold())
                   if not unicodedata.combining(c))


def completa_risposta_tariffe(domanda: str, risposta: str) -> str:
    """End actual visit-price answers with one separate invitation paragraph.

    The response must contain visit prices, not just quote the section title.
    Explicit duration and administrative questions don't inherit a pricing
    invitation from previous conversation turns.
    """
    presente = INVITO_DURATA in risposta
    domanda_normalizzata = _normalizza(domanda)
    risposta_normalizzata = _normalizza(risposta)
    richiesta_prezzi = bool(_PREZZO.search(domanda_normalizzata))
    prezzi_visite = bool(_VISITA.search(risposta_normalizzata) and (
        _IMPORTO.search(risposta_normalizzata)
        or (richiesta_prezzi and _PREZZO.search(risposta_normalizzata)
            and re.search(r"\b\d+(?:[.,]\d+)?\b", risposta_normalizzata))
    ))
    altro_argomento = not richiesta_prezzi and (
        _DURATA.search(domanda_normalizzata) or _ALTRE_INFO.search(domanda_normalizzata)
    )
    if not presente and (not prezzi_visite or altro_argomento):
        return risposta

    corpo = risposta.replace(INVITO_DURATA, "").rstrip()
    if presente:
        # Removing an already generated invitation must not leave empty blocks.
        corpo = re.sub(r"\n(?:[ \t]*\n){2,}", "\n\n", corpo).strip()
    return f"{corpo}\n\n{INVITO_DURATA}" if corpo else INVITO_DURATA
