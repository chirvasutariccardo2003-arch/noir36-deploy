# Noir36 - Guida Deploy Completa

## Metodo 1: Render.com (GRATUITO, più facile)

### Step 1: MongoDB Atlas (Gratuito)
1. Vai su https://cloud.mongodb.com
2. Registrati → Create Cluster → M0 Free (scegli Europe)
3. Database Access → Add User → crea utente e password
4. Network Access → Add IP → "Allow Access from Anywhere" (0.0.0.0/0)
5. Connect → Drivers → Copia la stringa tipo:
   `mongodb+srv://utente:password@cluster0.xxxxx.mongodb.net/noir36`

### Step 2: Deploy su Render.com
1. Vai su https://render.com → registrati con GitHub
2. New → Web Service → seleziona il repo (o carica con Docker)
3. Settings:
   - Runtime: Docker
   - Instance Type: Free
4. Environment Variables → aggiungi:
   - `MONGO_URL` = la stringa di MongoDB Atlas
   - `DB_NAME` = noir36
   - `JWT_SECRET` = genera da https://randomkeygen.com (504-bit WPA Key)
   - `ADMIN_EMAIL` = admin@noir36.com
   - `ADMIN_PASSWORD` = la tua password
   - `CORS_ORIGINS` = *
5. Deploy → attendi 2-3 minuti
6. Il sito sarà su https://noir36-xxxx.onrender.com

**Costo: 0€** (si addormenta dopo 15 min inattività, si risveglia in ~30s)
**No pubblicità, no sponsor**

---

## Metodo 2: VPS Hetzner (4.51€/mese, sempre online)

### Step 1: Crea VPS
1. https://hetzner.cloud → registrati
2. New Server → Falkenstein → Ubuntu 24.04 → CX22 (4.51€/mese)
3. Aggiungi la tua SSH key

### Step 2: Setup Server
```bash
ssh root@TUO_IP

# Installa Docker
curl -fsSL https://get.docker.com | sh

# Installa Docker Compose
apt install docker-compose-plugin -y

# Crea cartella
mkdir -p /opt/noir36
cd /opt/noir36
```

### Step 3: Carica i file
Dal tuo PC:
```bash
scp -r noir36-deploy/* root@TUO_IP:/opt/noir36/
```

### Step 4: Docker Compose
Crea `/opt/noir36/docker-compose.yml`:
```yaml
services:
  mongo:
    image: mongo:7
    volumes:
      - mongo_data:/data/db
    restart: always

  app:
    build: .
    ports:
      - "80:8001"
    environment:
      - MONGO_URL=mongodb://mongo:27017/noir36
      - DB_NAME=noir36
      - JWT_SECRET=cambia-con-stringa-random
      - ADMIN_EMAIL=admin@noir36.com
      - ADMIN_PASSWORD=TuaPasswordSicura
      - CORS_ORIGINS=*
    depends_on:
      - mongo
    restart: always

volumes:
  mongo_data:
```

```bash
docker compose up -d
```

Il sito è live su http://TUO_IP

### Step 5: Dominio + HTTPS
```bash
apt install certbot python3-certbot-nginx nginx -y
# Configura nginx come reverse proxy su porta 8001
# Lancia certbot per SSL gratuito
```

---

## Credenziali Admin
- Email: admin@noir36.com
- Password: (quella che imposti in ADMIN_PASSWORD)
- URL Admin: https://tuosito.com/admin

## File nel pacchetto
- `server.py` - Backend FastAPI completo
- `requirements.txt` - Dipendenze Python
- `static/` - Frontend React già buildato
- `Dockerfile` - Per deploy con Docker
- `.env` - Template variabili d'ambiente
- `start.sh` - Script avvio diretto
