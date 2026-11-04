import pytest

from response_formatting import INVITO_DURATA, completa_risposta_tariffe


@pytest.mark.parametrize("domanda,risposta", [
    ("Quali sono le tariffe delle prime visite e dei controlli?",
     "Cardiologia: 120 € per la prima visita e 80 € per il controllo.\n\nFonte: Carta dei Servizi."),
    ("Quanto costa una visita dermatologica?", "La prima visita dermatologica costa 100 euro."),
    ("Quanto costano i controlli?", "Il controllo oculistico costa 70 EUR."),
    ("Qual è il costo del controllo?", "Il costo della visita di controllo è 80."),
    ("E per la dermatologia?", "Dermatologia: prima visita 100 €, controllo 70 €."),
    ("E quella ortopedica?", "La visita ortopedica costa €110."),
])
def test_invita_sulle_tariffe_esplicite_e_sui_prezzi_dei_segui(domanda, risposta):
    assert completa_risposta_tariffe(domanda, risposta) == risposta + "\n\n" + INVITO_DURATA


@pytest.mark.parametrize("domanda,risposta", [
    ("Come posso pagare e dove trovo i miei referti?",
     "Si accettano contanti, carte e pagamenti digitali. I referti sono disponibili entro 5 giorni."),
    ("Quali sono i documenti necessari?", "Per la visita servono tessera sanitaria e documento d’identità."),
    ("Come mi preparo alla visita?", "Evita il caffè nelle 3 ore precedenti la visita cardiologica."),
    ("Quanto dura la visita?", "La visita cardiologica dura 40 minuti. Fonte: Specialità e tariffe."),
    ("Qual è la durata delle visite?", "Cardiologia: 40 minuti; dermatologia: 30 minuti."),
    ("Quanto tempo richiede il controllo?", "Il controllo dura 30 minuti e costa 70 €."),
    ("Posso disdire la visita?", "La disdetta tardiva costa il 50% della tariffa della visita."),
    ("Quanto pago per la mancata disdetta?", "Per una visita da 100 € la penale è 50 €."),
    ("Dove pago?", "La visita da 100 € si paga all’accettazione."),
    ("Quali sono i prezzi?", "Non trovo questa informazione nella Carta dei Servizi."),
    ("Come mi preparo?", "Leggi la sezione Specialità e tariffe (prestazioni private)."),
])
def test_non_aggiunge_inviti_ad_altri_argomenti_o_a_prezzi_assenti(domanda, risposta):
    assert completa_risposta_tariffe(domanda, risposta) == risposta


def test_normalizza_una_sola_copia_in_fondo_preservando_il_contenuto():
    corpo = "Prima visita cardiologica: 120 €.\n\nFonte: Carta dei Servizi."
    originale = f"Prima visita cardiologica: 120 €.\n\n{INVITO_DURATA}\n\nFonte: Carta dei Servizi.\n\n{INVITO_DURATA}"
    risultato = completa_risposta_tariffe("Tariffe?", originale)
    assert risultato == corpo + "\n\n" + INVITO_DURATA
    assert risultato.count(INVITO_DURATA) == 1
    assert completa_risposta_tariffe("Tariffe?", risultato) == risultato


def test_non_modifica_testi_non_tariffari_neppure_negli_spazi():
    testo = "Documenti necessari:\n\n- Tessera sanitaria\n- Documento\n"
    assert completa_risposta_tariffe("Quali documenti porto?", testo) == testo
