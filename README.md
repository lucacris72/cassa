# Cassa Ristorante Locale

Applicazione locale per gestire ordini da cassa, ticket cliente e ticket produzione per cucina/bar/asporto.

Non gestisce scontrini fiscali, registratori telematici, fatturazione, pagamenti online, magazzino o cloud sync.

## Funzioni MVP

- Login con PIN.
- Cassa touch-friendly con prodotti raggruppati per categoria.
- Ordini con numero progressivo per giornata operativa.
- Storico ordini con dettaglio, ristampa, pagato, consegnato e annullato.
- Chiusura cassa giornaliera con snapshot vendite e incasso.
- Admin prodotti, categorie e stampanti.
- Ticket cliente e ticket produzione raggruppati per stampante.
- Stampante fake su file per test.
- Stampante ESC/POS di rete su IP/porta, default `9100`.
- Pagina mobile LAN per confermare e stampare comande dal telefono.

## Installazione

```bash
cd /home/luca/oratorio/cassa
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Modificare `SECRET_KEY` in `.env` prima dell'uso reale.

## Avvio

```bash
source .venv/bin/activate
uvicorn restaurant_pos.app.main:app --host 0.0.0.0 --port 8000
```

Cassa locale:

```text
http://localhost:8000
```

Da tablet o smartphone sulla stessa LAN:

```text
http://IP_DEL_PC_CASSA:8000
```

## Utenti iniziali

- `admin`, PIN `1234`
- `cashier`, PIN `1111`

Cambiare i PIN prima dell'uso reale. I PIN sono salvati come hash PBKDF2, non in chiaro.

## Configurazione

Variabili supportate in `.env`:

```text
APP_HOST=0.0.0.0
APP_PORT=8000
DATABASE_URL=sqlite:///./data/app.db
BUSINESS_DAY_RESET_HOUR=4
PRINT_OUTPUT_DIR=./print_output
SECRET_KEY=change-me
```

`BUSINESS_DAY_RESET_HOUR=4` fa appartenere gli ordini prima delle 04:00 alla giornata operativa precedente.

## Stampanti

Tipi supportati:

- `fake`: scrive file `.txt` in `print_output/`.
- `network_escpos`: invia testo ESC/POS via TCP a IP/porta configurati.

Configurare le stampanti da `Stampanti`, poi assegnare le categorie alla stampante di produzione da `Categorie`.

Per una stampante ESC/POS di rete:

```text
Tipo: network_escpos
IP: 192.168.1.50
Porta: 9100
Abilitata: si
```

Ogni stampa ordine crea prima un record `print_jobs`, poi tenta la stampa. Se la stampante non risponde, l'ordine resta salvato e il job risulta `failed`.

## Test fake printer

Con seed iniziale le tre stampanti sono fake. Creare un ordine dalla cassa e controllare:

```text
print_output/
```

I file contengono ticket cliente e produzione.

## Chiusura cassa

Da `Chiusure` selezionare la giornata operativa e premere `Chiudi turno e azzera numerazione`.

La chiusura:

- registra uno snapshot di vendite e incasso;
- marca come consegnati e pagati gli ordini vendita ancora aperti;
- lascia fuori gli ordini annullati;
- blocca la chiusura se ci sono eventuali ordini ancora da confermare;
- apre un nuovo turno: gli ordini successivi ripartono da N.001.

## Backup

Il database SQLite predefinito sta in:

```text
data/app.db
```

Per un backup manuale a server fermo:

```bash
cp data/app.db "data/backup-$(date +%F-%H%M).db"
```

Non cancellare vecchi ordini dal database se servono per storico o controlli operativi.

## Test

```bash
source .venv/bin/activate
pytest
```

## Risoluzione problemi stampa

- Verificare che la stampante sia abilitata.
- Verificare IP e porta.
- Provare `Test` dalla pagina stampanti.
- Controllare lo storico ordine: i job falliti mostrano l'errore.
- Usare `fake` per isolare problemi dell'app da problemi di rete/stampante.
