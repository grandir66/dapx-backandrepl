# 🐳 Installazione Containerizzata - DAPX-backandrepl

Guida per installare e utilizzare DAPX-backandrepl in un container Docker.

## 📋 Requisiti

- **Docker** 20.10+ 
- **Docker Compose** 2.0+ (o `docker compose` plugin)
- **Porta 8420** libera
- **Accesso SSH** ai nodi Proxmox da gestire

## 🚀 Installazione Rapida

### 1. Clona il Repository

```bash
git clone https://github.com/grandir66/dapx-backandrepl.git
cd dapx-backandrepl
```

### 2. Esegui Installazione

```bash
chmod +x docker-install.sh
./docker-install.sh
```

Lo script:
- Crea le directory necessarie (`data/`, `config/`, `logs/`, `certs/`)
- Genera chiavi SSH se non presenti
- Crea file di configurazione
- Builda l'immagine Docker
- Avvia il container

### 3. Accesso Web UI

Apri il browser su: `http://localhost:8420`

## 🔧 Installazione Manuale

### 1. Crea Directory

```bash
mkdir -p data config logs certs
```

### 2. Configura Variabili d'Ambiente

Crea `config/.env`:

```bash
cat > config/.env << EOF
DAPX_SECRET_KEY=$(openssl rand -hex 32)
DAPX_TOKEN_EXPIRE=480
DAPX_CORS_ORIGINS=
EOF
```

### 3. Build Immagine

```bash
docker-compose build
```

Oppure con Docker Compose v2:

```bash
docker compose build
```

### 4. Avvia Container

```bash
docker-compose up -d
```

Oppure:

```bash
docker compose up -d
```

## 📁 Struttura Directory

```
dapx-backandrepl/
├── docker-compose.yml      # Configurazione Docker Compose
├── Dockerfile              # Definizione immagine Docker
├── docker-install.sh      # Script installazione
├── data/                   # Database SQLite (persistente)
├── config/                 # File di configurazione
├── logs/                   # Log applicazione
└── certs/                  # Certificati SSL (opzionale)
```

## 🔐 Configurazione SSH

Il container monta la directory SSH dell'host (`${HOME}/.ssh`) in sola lettura.

### Autorizza Chiave SSH sui Nodi

```bash
# Mostra chiave pubblica
cat ~/.ssh/id_rsa.pub

# Su ogni nodo Proxmox:
ssh-copy-id -i ~/.ssh/id_rsa.pub root@192.168.1.10
```

**Nota**: Se usi un utente diverso da `root`, modifica `docker-compose.yml` per montare la directory SSH corretta.

## ⚙️ Configurazione

### Variabili d'Ambiente

Modifica `config/.env` o `docker-compose.yml`:

```yaml
environment:
  - DAPX_DB=/data/dapx-backandrepl.db
  - DAPX_PORT=8420
  - DAPX_LOG_LEVEL=INFO
  - DAPX_SECRET_KEY=your-secret-key-here
  - DAPX_TOKEN_EXPIRE=480
  - DAPX_CORS_ORIGINS=http://localhost:3000
```

### Porta Personalizzata

Modifica `docker-compose.yml`:

```yaml
ports:
  - "8080:8420"  # Host:Container
```

### Volume Personalizzati

```yaml
volumes:
  - /path/to/data:/data
  - /path/to/config:/config
  - /path/to/logs:/logs
```

## 🛠️ Comandi Utili

### Visualizza Log

```bash
# Log in tempo reale
docker-compose logs -f

# Ultimi 100 log
docker-compose logs --tail=100

# Log specifico servizio
docker-compose logs dapx-backandrepl
```

### Gestione Container

```bash
# Avvia
docker-compose up -d

# Ferma
docker-compose down

# Riavvia
docker-compose restart

# Stato
docker-compose ps

# Entra nel container
docker-compose exec dapx-backandrepl /bin/bash
```

### Backup Database

```bash
# Backup manuale
docker-compose exec dapx-backandrepl cp /data/dapx-backandrepl.db /data/backup-$(date +%Y%m%d).db

# Oppure dall'host
cp data/dapx-backandrepl.db data/backup-$(date +%Y%m%d).db
```

### Aggiornamento

```bash
# Pull ultime modifiche
git pull

# Rebuild immagine
docker-compose build

# Riavvia con nuova immagine
docker-compose up -d
```

## 🔒 Sicurezza

### Eseguire come Utente Non-Root

Il Dockerfile è configurato per eseguire come utente `dapx` (UID 1000). Se hai problemi con SSH, puoi:

1. **Opzione 1**: Eseguire come root (rimuovi commento in `docker-compose.yml`):
   ```yaml
   user: "0:0"
   ```

2. **Opzione 2**: Configurare SSH con utente non-root:
   ```bash
   # Nel container, crea directory SSH
   docker-compose exec dapx-backandrepl mkdir -p /home/dapx/.ssh
   
   # Copia chiavi
   docker cp ~/.ssh/id_rsa dapx-backandrepl:/home/dapx/.ssh/
   docker cp ~/.ssh/id_rsa.pub dapx-backandrepl:/home/dapx/.ssh/
   
   # Imposta permessi
   docker-compose exec dapx-backandrepl chmod 600 /home/dapx/.ssh/id_rsa
   docker-compose exec dapx-backandrepl chmod 644 /home/dapx/.ssh/id_rsa.pub
   ```

### Firewall

```bash
# UFW
ufw allow from 192.168.100.0/24 to any port 8420

# iptables
iptables -A INPUT -p tcp --dport 8420 -s 192.168.100.0/24 -j ACCEPT
```

### Reverse Proxy con SSL

Usa Nginx o Traefik come reverse proxy:

```nginx
# Nginx
server {
    listen 443 ssl;
    server_name dapx.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8420;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 🐛 Troubleshooting

### Container non parte

```bash
# Controlla log
docker-compose logs

# Verifica stato
docker-compose ps

# Verifica permessi directory
ls -la data/ config/ logs/
```

### Errore connessione SSH

```bash
# Verifica chiavi SSH nel container
docker-compose exec dapx-backandrepl ls -la /home/dapx/.ssh/

# Testa connessione
docker-compose exec dapx-backandrepl ssh -i /home/dapx/.ssh/id_rsa root@nodo "echo OK"
```

### Database non persiste

Verifica che il volume sia montato correttamente:

```bash
docker-compose exec dapx-backandrepl ls -la /data/
```

### Porta già in uso

```bash
# Trova processo che usa porta 8420
sudo lsof -i :8420

# Cambia porta in docker-compose.yml
ports:
  - "8421:8420"
```

## 📊 Monitoraggio

### Health Check

Il container include un health check automatico:

```bash
# Verifica stato health
docker inspect dapx-backandrepl | grep -A 10 Health
```

### Risorse

```bash
# Utilizzo risorse
docker stats dapx-backandrepl
```

## 🔄 Migrazione da Installazione Standard

Se hai già un'installazione standard e vuoi migrare a container:

1. **Backup database**:
   ```bash
   cp /var/lib/sanoid-manager/sanoid-manager.db ./data/dapx-backandrepl.db
   ```

2. **Copia configurazione** (se presente):
   ```bash
   cp /etc/sanoid-manager/sanoid-manager.env ./config/.env
   ```

3. **Avvia container**:
   ```bash
   docker-compose up -d
   ```

4. **Verifica**:
   ```bash
   docker-compose logs -f
   ```

## 📝 Note

- Il database è persistente nella directory `data/`
- I log sono salvati in `logs/` e anche visibili via `docker-compose logs`
- Le chiavi SSH sono montate dalla directory home dell'host
- Per produzione, configura SSL/TLS tramite reverse proxy
- Limita l'accesso alla porta 8420 solo alla rete di gestione

## 🆚 Confronto: Container vs Installazione Standard

| Aspetto | Container | Standard |
|---------|-----------|----------|
| **Isolamento** | ✅ Completo | ❌ Condivide sistema |
| **Portabilità** | ✅ Alta | ⚠️ Media |
| **Aggiornamento** | ✅ Facile | ⚠️ Richiede script |
| **Risorse** | ⚠️ Overhead Docker | ✅ Diretto |
| **SSH** | ⚠️ Richiede mount | ✅ Nativo |
| **Debug** | ⚠️ Più complesso | ✅ Più semplice |

**Raccomandazione**:
- **Container**: Per sviluppo, test, o deployment in ambienti containerizzati
- **Standard**: Per produzione su server dedicati, massime performance

---

**© 2025 Domarc S.r.l. - Tutti i diritti riservati**



