PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS prenotazioni;
DROP TABLE IF EXISTS pazienti;
DROP TABLE IF EXISTS slot;
DROP TABLE IF EXISTS medici;
DROP TABLE IF EXISTS specialita;

CREATE TABLE specialita (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    costo_prima_visita REAL NOT NULL CHECK (costo_prima_visita > 0),
    costo_controllo REAL NOT NULL CHECK (costo_controllo > 0),
    durata_minuti INTEGER NOT NULL CHECK (durata_minuti > 0)
);

-- Tariffe e durate dalla Carta dei Servizi (prestazioni private)
INSERT INTO specialita (id, nome, costo_prima_visita, costo_controllo, durata_minuti)
VALUES
    (1, 'Cardiologia', 120, 80, 40),
    (2, 'Dermatologia', 100, 70, 30),
    (3, 'Ortopedia', 110, 75, 30),
    (4, 'Oculistica', 100, 70, 40),
    (5, 'Nutrizione', 90, 60, 45);

CREATE TABLE medici (
    id INTEGER PRIMARY KEY,
    nome TEXT NOT NULL,
    specialita_id INTEGER NOT NULL,
    FOREIGN KEY (specialita_id) REFERENCES specialita(id)
);

INSERT INTO medici (id, nome, specialita_id)
VALUES
    (1, 'Laura Bianchi', 1),
    (2, 'Marco Rinaldi', 1),
    (3, 'Elena Greco', 2),
    (4, 'Paolo Ferri', 3),
    (5, 'Chiara Romano', 4),
    (6, 'Giulia Conti', 5);

CREATE TABLE slot (
    id INTEGER PRIMARY KEY,
    medico_id INTEGER NOT NULL,
    data_ora TEXT NOT NULL,
    libero INTEGER NOT NULL DEFAULT 1 CHECK (libero IN (0, 1)),
    FOREIGN KEY (medico_id) REFERENCES medici(id),
    UNIQUE (medico_id, data_ora)
);

-- data_ora nel formato 'AAAA-MM-GG HH:MM'
INSERT INTO slot (id, medico_id, data_ora, libero)
VALUES
    (1, 1, '2026-11-03 09:00', 0),
    (2, 1, '2026-11-03 10:00', 1),
    (3, 1, '2026-11-04 09:00', 1),
    (4, 1, '2026-11-04 10:00', 1),
    (5, 1, '2026-11-05 09:00', 1),
    (6, 2, '2026-11-03 11:00', 1),
    (7, 2, '2026-11-03 12:00', 1),
    (8, 2, '2026-11-04 11:00', 1),
    (9, 2, '2026-11-04 12:00', 1),
    (10, 2, '2026-11-05 11:00', 1),
    (11, 3, '2026-11-06 09:00', 1),
    (12, 3, '2026-11-06 10:00', 1),
    (13, 3, '2026-11-07 09:00', 1),
    (14, 3, '2026-11-07 10:00', 1),
    (15, 3, '2026-11-09 09:00', 1),
    (16, 4, '2026-11-10 09:00', 1),
    (17, 4, '2026-11-10 10:00', 1),
    (18, 4, '2026-11-11 09:00', 1),
    (19, 4, '2026-11-11 10:00', 1),
    (20, 4, '2026-11-12 09:00', 1),
    (21, 5, '2026-11-13 09:00', 1),
    (22, 5, '2026-11-13 10:00', 1),
    (23, 5, '2026-11-14 09:00', 1),
    (24, 5, '2026-11-14 10:00', 1),
    (25, 5, '2026-11-16 09:00', 1),
    (26, 6, '2026-11-17 09:00', 1),
    (27, 6, '2026-11-17 10:00', 1),
    (28, 6, '2026-11-18 09:00', 1),
    (29, 6, '2026-11-18 10:00', 1),
    (30, 6, '2026-11-19 09:00', 1),
    (31, 1, '2026-11-09 15:00', 1),
    (32, 2, '2026-11-09 15:00', 1),
    (33, 3, '2026-11-09 15:00', 1),
    (34, 4, '2026-11-09 15:00', 1),
    (35, 5, '2026-11-09 15:00', 1),
    (36, 6, '2026-11-09 15:00', 1),
    (37, 1, '2026-11-10 15:00', 1),
    (38, 2, '2026-11-10 15:00', 1),
    (39, 3, '2026-11-10 15:00', 1),
    (40, 4, '2026-11-10 15:00', 1),
    (41, 5, '2026-11-10 15:00', 1),
    (42, 6, '2026-11-10 15:00', 1),
    (43, 1, '2026-11-11 15:00', 1),
    (44, 2, '2026-11-11 15:00', 1),
    (45, 3, '2026-11-11 15:00', 1),
    (46, 4, '2026-11-11 15:00', 1),
    (47, 5, '2026-11-11 15:00', 1),
    (48, 6, '2026-11-11 15:00', 1),
    (49, 1, '2026-11-12 15:00', 1),
    (50, 2, '2026-11-12 15:00', 1),
    (51, 3, '2026-11-12 15:00', 1),
    (52, 4, '2026-11-12 15:00', 1),
    (53, 5, '2026-11-12 15:00', 1),
    (54, 6, '2026-11-12 15:00', 1),
    (55, 1, '2026-11-13 15:00', 1),
    (56, 2, '2026-11-13 15:00', 1),
    (57, 3, '2026-11-13 15:00', 1),
    (58, 4, '2026-11-13 15:00', 1),
    (59, 5, '2026-11-13 15:00', 1),
    (60, 6, '2026-11-13 15:00', 1),
    (61, 1, '2026-11-16 15:00', 1),
    (62, 2, '2026-11-16 15:00', 1),
    (63, 3, '2026-11-16 15:00', 1),
    (64, 4, '2026-11-16 15:00', 1),
    (65, 5, '2026-11-16 15:00', 1),
    (66, 6, '2026-11-16 15:00', 1),
    (67, 1, '2026-11-17 15:00', 1),
    (68, 2, '2026-11-17 15:00', 1),
    (69, 3, '2026-11-17 15:00', 1),
    (70, 4, '2026-11-17 15:00', 1),
    (71, 5, '2026-11-17 15:00', 1),
    (72, 6, '2026-11-17 15:00', 1),
    (73, 1, '2026-11-18 15:00', 1),
    (74, 2, '2026-11-18 15:00', 1),
    (75, 3, '2026-11-18 15:00', 1),
    (76, 4, '2026-11-18 15:00', 1),
    (77, 5, '2026-11-18 15:00', 1),
    (78, 6, '2026-11-18 15:00', 1),
    (79, 1, '2026-11-19 15:00', 1),
    (80, 2, '2026-11-19 15:00', 1),
    (81, 3, '2026-11-19 15:00', 1),
    (82, 4, '2026-11-19 15:00', 1),
    (83, 5, '2026-11-19 15:00', 1),
    (84, 6, '2026-11-19 15:00', 1),
    (85, 1, '2026-11-20 15:00', 1),
    (86, 2, '2026-11-20 15:00', 1),
    (87, 3, '2026-11-20 15:00', 1),
    (88, 4, '2026-11-20 15:00', 1),
    (89, 5, '2026-11-20 15:00', 1),
    (90, 6, '2026-11-20 15:00', 1);

CREATE TABLE pazienti (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    codice_fiscale TEXT NOT NULL UNIQUE
        CHECK (length(codice_fiscale) = 16 AND codice_fiscale = upper(codice_fiscale))
);

-- Pazienti di prova con dati di fantasia
INSERT INTO pazienti (id, nome, codice_fiscale)
VALUES
    (1, 'Mario Rossi', 'RSSMRA90A01H501X'),
    (2, 'Luigi Verdi', 'VRDLGU85B02A662Y'),
    (3, 'Anna Bianchi', 'BNCNNA92C41A662Z');

CREATE TABLE prenotazioni (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paziente_id INTEGER NOT NULL,
    slot_id INTEGER NOT NULL,
    tipo_visita TEXT NOT NULL
        CHECK (tipo_visita IN ('Prima visita', 'Visita di controllo')),
    importo REAL NOT NULL CHECK (importo >= 0),
    stato TEXT NOT NULL DEFAULT 'confermata'
        CHECK (stato IN ('confermata', 'annullata')),
    creato_il TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),

    FOREIGN KEY (paziente_id) REFERENCES pazienti(id),
    FOREIGN KEY (slot_id) REFERENCES slot(id)
);

-- Uno slot può avere una sola prenotazione confermata; dopo una disdetta si può riprenotare
CREATE UNIQUE INDEX prenotazione_confermata_per_slot
    ON prenotazioni (slot_id) WHERE stato = 'confermata';

-- Prenotazione di esempio: lo slot 1 è già occupato
INSERT INTO prenotazioni (id, paziente_id, slot_id, tipo_visita, importo, stato)
VALUES
    (1, 1, 1, 'Prima visita', 120, 'confermata');
