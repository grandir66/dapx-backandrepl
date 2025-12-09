# 🔄 Guida Aggiornamento - DAPX-backandrepl

Guida completa per aggiornare e gestire installazioni esistenti.

## 📋 Indice

1. [Aggiornamento Singolo Sistema](#aggiornamento-singolo-sistema)
2. [Aggiornamento Remoto (più sistemi)](#aggiornamento-remoto)
3. [Aggiornamento Container LXC](#aggiornamento-container-lxc)
4. [Aggiornamento Container Docker](#aggiornamento-container-docker)
5. [Gestione e Manutenzione](#gestione-e-manutenzione)
6. [Rollback](#rollback)

---

## 🖥️ Aggiornamento Singolo Sistema

### Metodo 1: Script automatico (Consigliato)

Sul sistema da aggiornare:

```bash
# Download ed esecuzione script aggiornamento
wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/update.sh -O /tmp/update.sh
chmod +x /tmp/update.sh
/tmp/update.sh
```

### Metodo 2: Aggiornamento manuale

```bash
# 1. Ferma servizio
systemctl stop dapx-backandrepl
# oppure
systemctl stop sanoid-manager

# 2. Backup database
cp /var/lib/dapx-backandrepl/dapx-backandrepl.db /var/lib/dapx-backandrepl/backup-$(date +%Y%m%d).db

# 3. Aggiorna codice
cd /opt/dapx-backandrepl
git pull origin main

# 4. Aggiorna dipendenze
cd backend
pip3 install -r requirements.txt --upgrade

# 5. Riavvia servizio
systemctl daemon-reload
systemctl start dapx-backandrepl

# 6. Verifica
systemctl status dapx-backandrepl
```

---

## 🌐 Aggiornamento Remoto

Aggiorna più sistemi contemporaneamente dalla tua macchina locale.

### Metodo 1: Script remoto (Consigliato)

```bash
# Scarica script
wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/remote-update.sh
chmod +x remote-update.sh

# Aggiorna singolo host
./remote-update.sh update 192.168.40.3

# Aggiorna più host
./remote-update.sh update 192.168.40.3 192.168.40.4 192.168.40.5

# Verifica stato
./remote-update.sh status 192.168.40.3

# Visualizza log
./remote-update.sh logs 192.168.40.3

# Mostra versioni
./remote-update.sh version 192.168.40.3 192.168.40.4

# Riavvia servizio
./remote-update.sh restart 192.168.40.3
```

### Metodo 2: Aggiornamento SSH manuale

```bash
# Singolo host
ssh root@192.168.40.3 "wget -qO- https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/update.sh | bash"

# Più host con loop
for HOST in 192.168.40.3 192.168.40.4 192.168.40.5; do
    echo "=== Aggiornamento ${HOST} ==="
    ssh root@${HOST} "wget -qO- https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/update.sh | bash"
done
```

### Metodo 3: Con Ansible (per infrastrutture grandi)

```yaml
# playbook.yml
- hosts: dapx_servers
  become: yes
  tasks:
    - name: Scarica script aggiornamento
      get_url:
        url: https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/update.sh
        dest: /tmp/update.sh
        mode: '0755'
    
    - name: Esegui aggiornamento
      shell: /tmp/update.sh
      
    - name: Verifica servizio
      systemd:
        name: dapx-backandrepl
        state: started
        enabled: yes
```

Esegui con:
```bash
ansible-playbook -i inventory.ini playbook.yml
```

---

## 🐳 Aggiornamento Container LXC

### Metodo 1: Script gestione

```bash
# Sul nodo Proxmox
cd /root/dapx-lxc-deploy/dapx-backandrepl/lxc

# Aggiorna applicazione nel container
./manage-lxc.sh 100 update

# Verifica stato
./manage-lxc.sh 100 status
```

### Metodo 2: Manuale

```bash
# Entra nel container
pct enter 100

# Aggiorna
cd /opt/dapx-backandrepl
git pull origin main
cd backend
pip3 install -r requirements.txt --upgrade
systemctl restart dapx-backandrepl

# Esci
exit
```

### Metodo 3: Da remoto

```bash
# Dal nodo Proxmox
pct exec 100 -- bash -c "
    cd /opt/dapx-backandrepl && \
    git pull origin main && \
    cd backend && \
    pip3 install -r requirements.txt --upgrade && \
    systemctl restart dapx-backandrepl
"
```

---

## 🐋 Aggiornamento Container Docker

### Metodo 1: Rebuild immagine

```bash
cd /opt/dapx-backandrepl-docker

# Pull ultime modifiche
git pull origin main

# Rebuild e riavvia
docker-compose down
docker-compose build --no-cache
docker-compose up -d

# Verifica
docker-compose logs -f
```

### Metodo 2: Solo aggiornamento codice

```bash
cd /opt/dapx-backandrepl-docker

# Pull modifiche
git pull origin main

# Riavvia container (usa i nuovi file montati)
docker-compose restart
```

---

## 🛠️ Gestione e Manutenzione

### Comandi utili

```bash
# === STATO ===
# Stato servizio
systemctl status dapx-backandrepl

# Log in tempo reale
journalctl -u dapx-backandrepl -f

# Ultimi 100 log
journalctl -u dapx-backandrepl -n 100

# === CONTROLLO ===
# Riavvia servizio
systemctl restart dapx-backandrepl

# Ferma servizio
systemctl stop dapx-backandrepl

# Avvia servizio
systemctl start dapx-backandrepl

# === VERIFICA ===
# Test API
curl http://localhost:8420/api/health

# Versione
cat /opt/dapx-backandrepl/version.txt

# === BACKUP ===
# Backup database
cp /var/lib/dapx-backandrepl/dapx-backandrepl.db /backup/dapx-$(date +%Y%m%d).db
```

### Verifica versione installata

```bash
# Metodo 1: File versione
cat /opt/dapx-backandrepl/version.txt

# Metodo 2: Git
cd /opt/dapx-backandrepl
git describe --tags

# Metodo 3: API
curl -s http://localhost:8420/api/health | jq .version
```

### Monitoraggio

```bash
# CPU e memoria servizio
systemctl status dapx-backandrepl | grep -E "Memory|CPU"

# Spazio database
du -h /var/lib/dapx-backandrepl/

# Connessioni attive
ss -tlnp | grep 8420
```

---

## ⏪ Rollback

Se un aggiornamento causa problemi:

### Metodo 1: Rollback Git

```bash
# Ferma servizio
systemctl stop dapx-backandrepl

# Torna alla versione precedente
cd /opt/dapx-backandrepl
git log --oneline -10  # Vedi commit recenti
git checkout <commit-hash>  # Torna a commit specifico

# Oppure torna al tag precedente
git checkout v3.4.4

# Riavvia
systemctl start dapx-backandrepl
```

### Metodo 2: Ripristino backup

```bash
# Ferma servizio
systemctl stop dapx-backandrepl

# Ripristina database
cp /backup/dapx-20241208.db /var/lib/dapx-backandrepl/dapx-backandrepl.db

# Riavvia
systemctl start dapx-backandrepl
```

### Metodo 3: Reinstallazione

```bash
# Se tutto fallisce, reinstalla
cd /opt
rm -rf dapx-backandrepl

# Reinstalla versione specifica
git clone --branch v3.4.4 https://github.com/grandir66/dapx-backandrepl.git
cd dapx-backandrepl
./install.sh
```

---

## 📊 Riepilogo Comandi

| Azione | Comando |
|--------|---------|
| Aggiorna singolo sistema | `wget -qO- .../update.sh \| bash` |
| Aggiorna remoto | `./remote-update.sh update HOST` |
| Aggiorna LXC | `./manage-lxc.sh 100 update` |
| Aggiorna Docker | `docker-compose build && up -d` |
| Verifica stato | `systemctl status dapx-backandrepl` |
| Log | `journalctl -u dapx-backandrepl -f` |
| Riavvia | `systemctl restart dapx-backandrepl` |
| Versione | `cat version.txt` o `curl .../health` |

---

## 🔗 Link utili

- **Repository**: https://github.com/grandir66/dapx-backandrepl
- **Releases**: https://github.com/grandir66/dapx-backandrepl/releases
- **Changelog**: https://github.com/grandir66/dapx-backandrepl/blob/main/CHANGELOG.md

---

**© 2025 Domarc S.r.l. - Tutti i diritti riservati**



