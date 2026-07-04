# Deploy produzione locale

Target consigliato: VM Ubuntu Server LTS su Proxmox, repository clonato in `/opt/cassa`, servizio `systemd` chiamato `cassa`.

## Prima installazione

```bash
sudo apt update
sudo apt install -y git python3 python3-venv sqlite3 curl
sudo mkdir -p /opt/cassa /var/backups/cassa
sudo chown -R parrocchia:parrocchia /opt/cassa /var/backups/cassa
git clone git@github.com:lucacris72/cassa.git /opt/cassa
cd /opt/cassa
cp .env.example .env
nano .env
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
sudo cp deploy/cassa.service /etc/systemd/system/cassa.service
sudo cp deploy/sudoers-cassa /etc/sudoers.d/cassa
sudo chmod 440 /etc/sudoers.d/cassa
sudo systemctl daemon-reload
sudo systemctl enable --now cassa
curl http://127.0.0.1:18000/healthz
```

Impostare in `.env` almeno:

```bash
APP_HOST=0.0.0.0
APP_PORT=18000
DATABASE_URL=sqlite:////opt/cassa/data/app.db
PRINT_OUTPUT_DIR=/opt/cassa/print_output
SECRET_KEY=<valore-lungo-casuale>
```

## Aggiornamento produzione

Da `/opt/cassa`:

```bash
scripts/update_production.sh
```

Lo script fa backup SQLite, `git pull --ff-only`, aggiorna dipendenze, riavvia il servizio e controlla `/healthz`.

## Backup

Backup manuale:

```bash
scripts/backup_db.sh
```

Backup giornaliero con cron:

```bash
sudo crontab -e
```

```cron
15 3 * * * APP_DIR=/opt/cassa /opt/cassa/scripts/backup_db.sh >/var/log/cassa-backup.log 2>&1
```

## Comandi utili

```bash
sudo systemctl status cassa
sudo journalctl -u cassa -f
sudo systemctl restart cassa
curl http://127.0.0.1:18000/healthz
curl http://192.168.5.90:18000/healthz
curl http://10.0.0.102:18000/healthz
```

## Note rete

Per una rete dedicata alla cassa, lasciare stampanti e client con IP statici. Su questa VM la porta `8000` e gia occupata da un container, quindi la cassa usa la porta `18000` e ascolta su tutte le interfacce con `APP_HOST=0.0.0.0`.

Accessi diretti previsti:

- rete cassa: `http://192.168.5.90:18000`
- rete servizi/internet: `http://10.0.0.102:18000`

In alternativa puo essere pubblicata via Nginx Proxy Manager verso upstream `127.0.0.1:18000` oppure `192.168.5.90:18000`.
