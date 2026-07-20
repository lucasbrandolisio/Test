# filesync

Strumento a riga di comando per tenere sincronizzate cartelle di progetto
(es. progetti PLC, HMI, script Python) tra il computer locale e un server
aziendale, con supporto per cartelle condivise VMware, backup di piu'
cartelle in parallelo, garanzia di non cancellare mai nulla, e cifratura
con recupero password (via email e/o tramite un amministratore).

## Funzionalita'

- **Sync incrementale**: copia solo i file nuovi o modificati.
- **Piu' cartelle in parallelo**: definisci tutti i progetti che vuoi
  (PLC, HMI, Python, ...) in un unico `config.yaml`; vengono sincronizzati
  contemporaneamente verso il server, non uno alla volta.
- **Non cancella mai nulla dal backup**: di default (`mirror: false`) un
  file rimosso dalla sorgente resta comunque nel backup. Anche attivando
  `mirror: true`, i file "rimossi" non vengono davvero cancellati ma
  spostati in `.filesync_trash/<data>/` dentro la destinazione: restano
  sempre recuperabili. Puoi quindi ripristinare l'intero backup dal
  server anche se il tuo PC si rompe.
- **Modalita' watch**: gira in loop e sincronizza automaticamente ad
  intervalli regolari.
- **Cifratura delle cartelle** (AES via `cryptography.Fernet`) cosi' chi
  ha accesso al server non puo' leggere il codice sorgente.
- **Recupero password su tre livelli** (vedi sotto in dettaglio):
  1. la tua password personale (uso quotidiano);
  2. una chiave di recovery ricevuta una volta via email, per
     auto-recuperarti se dimentichi la password;
  3. una chiave "master" che solo l'amministratore possiede, per
     recuperare l'accesso a qualunque progetto anche se un collega ha
     perso sia la password che la chiave di recovery (es. se ne e' andato
     dall'azienda).
- **Percorsi VMware Shared Folders**: nessuna integrazione dedicata
  necessaria, vedi sotto.

## Installazione

```bash
pip install -r requirements.txt
```

Richiede Python 3.9+. Nessuna dipendenza aggiuntiva per l'email o le
chiavi master: usano solo `cryptography` (gia' richiesta) e la libreria
standard di Python.

## Uso rapido

```bash
cp config.example.yaml config.yaml   # poi modifica sorgenti/destinazioni
python -m filesync sync -c config.yaml            # sincronizzazione singola
python -m filesync sync -c config.yaml --watch     # in continuo (ogni 60s)
python -m filesync sync -c config.yaml --dry-run   # prova senza modificare nulla
python -m filesync sync -c config.yaml --job PLC   # solo un progetto
```

## Piu' cartelle contemporaneamente

Ogni voce in `jobs:` nel `config.yaml` e' una cartella da sincronizzare.
Con piu' job, `filesync sync` li esegue **in parallelo** (di default fino
a 4 alla volta, regolabile con `--max-parallel`), cosi' il backup di PLC,
HMI e Python parte tutto insieme invece che in sequenza:

```bash
python -m filesync sync -c config.yaml                  # parallelo (default)
python -m filesync sync -c config.yaml --max-parallel 8  # fino a 8 insieme
python -m filesync sync -c config.yaml --sequential      # uno alla volta, se la rete e' lenta
```

## Non cancella mai nulla (backup "vitale")

Requisito centrale di questo tool: **il backup sul server non deve mai
perdere file**, cosi' se il PC locale si guasta puoi sempre andare sul
server e recuperare tutto.

- Lascia `mirror: false` (il default) sui job di backup: i file
  cancellati/rinominati in locale restano semplicemente nel backup.
- Anche se abiliti `mirror: true` per tenere il backup "pulito" allineato
  alla sorgente, filesync non fa mai una vera `rm`: sposta il file in
  `<destinazione>/.filesync_trash/<AAAAMMGG-hhmmss>/...`, mantenendo il
  contenuto intatto e recuperabile a mano in qualsiasi momento.
- L'unica pulizia manuale che dovrai fare, se lo spazio disco diventa un
  problema, e' svuotare ogni tanto `.filesync_trash` a mano: il programma
  non lo fa mai da solo.

### Ripristinare l'intero backup dopo un guasto

Per i job **non cifrati**, i file sono gia' in chiaro sulla destinazione:
basta copiarli. Per i job **cifrati**, usa:

```bash
python -m filesync open "//SERVER/Backup/PLC" ./PLC_ripristinato --password "la-tua-password"
```

## Cifratura: password personale, recovery via email, chiave master

Ogni job cifrato usa una singola chiave interna (DEK) per cifrare i file.
Questa chiave puo' essere sbloccata in tre modi indipendenti, senza mai
dover ricifrare i file quando cambi password:

| Chi | Come | Quando serve |
|---|---|---|
| Tu (utente) | la tua password personale | uso quotidiano |
| Tu (utente) | chiave di recovery ricevuta una volta via email | hai dimenticato la password |
| Amministratore (es. tu come "capo") | chiave master (file privato + passphrase, solo sua) | un collega ha perso password e chiave di recovery, o e' andato via dall'azienda |

### 1. Generare la chiave master (una tantum, solo l'amministratore)

```bash
python -m filesync master-keygen --out-dir ./keys
```

Ti chiede una passphrase (solo tu la devi sapere) e crea due file:

- `keys/master_public.pem` — **non e' un segreto**, va distribuita a tutti
  i colleghi/nel loro `config.yaml` (campo `master_public_key`). Serve solo
  per "chiudere il lucchetto", non per aprirlo.
- `keys/master_private.pem` — **massima riservatezza**: solo tu la
  conservi (es. su una chiavetta USB offline), mai su git, mai sul server
  di backup. Senza questo file + la tua passphrase nessuno puo' fare
  recupero master, nemmeno tu se li perdi entrambi: conservali con cura
  (es. una copia in un posto sicuro separato).

### 2. Configurare un job cifrato

Nel `config.yaml` di ogni collega:

```yaml
jobs:
  - name: "PLC"
    source: "/home/collega/Progetti/PLC"
    destination: "//SERVER/Backup/PLC"
    encrypt: true
    password_env: "FILESYNC_PW_PLC"
    master_public_key: "./keys/master_public.pem"   # tu distribuisci questo file
    recovery_email: "collega@azienda.it"             # riceve la chiave di recovery
```

Il collega imposta la propria password come variabile d'ambiente e lancia
la sync normalmente:

```bash
export FILESYNC_PW_PLC="una-password-a-sua-scelta"
python -m filesync sync -c config.yaml
```

Alla **prima** sincronizzazione di un job cifrato, filesync:

1. genera la DEK e la chiude con la password del collega;
2. la chiude anche con la tua chiave pubblica master (se configurata);
3. genera una chiave di recovery casuale, la chiude anch'essa con la DEK,
   e la manda una tantum via email a `recovery_email` (vedi configurazione
   SMTP sotto). Se l'invio fallisce, la chiave viene comunque stampata nel
   log: **va salvata subito**, non viene rigenerata automaticamente.

Alle sincronizzazioni successive, riusa semplicemente la configurazione
gia' creata.

### 3. Configurare l'invio email (Office 365 / Outlook)

Variabili d'ambiente (mai nel `config.yaml`):

```bash
export FILESYNC_SMTP_HOST="smtp.office365.com"   # default, puoi ometterlo
export FILESYNC_SMTP_PORT="587"                   # default, puoi ometterlo
export FILESYNC_SMTP_USER="backup@tuaazienda.it"
export FILESYNC_SMTP_PASSWORD="app-password-dedicata"
```

**Nota importante**: molti tenant Microsoft 365 disabilitano l'SMTP AUTH
"classico" di default, specialmente con l'MFA attiva. Se l'invio fallisce
con un errore di autenticazione:

- chiedi al tuo amministratore IT di abilitare "Authenticated SMTP" per la
  casella usata (Centro amministrazione Exchange → Destinatari → Caselle
  postali → Gestisci app email);
- se l'account ha l'MFA attiva, genera una **App Password** dedicata (da
  usare al posto della password normale) oppure usa un account di
  servizio pensato per l'invio automatico.
- Se la policy aziendale blocca comunque l'SMTP autenticato, come
  alternativa puoi usare un servizio transazionale (es. SendGrid/Mailgun)
  esponendo comunque un endpoint SMTP: basta puntare `FILESYNC_SMTP_HOST`
  a quello.

### 4. Password dimenticata: auto-recupero con la chiave via email

```bash
python -m filesync recover "//SERVER/Backup/PLC" \
  --recovery-key "LA-CHIAVE-RICEVUTA-VIA-EMAIL" \
  --new-password "nuova-password"
```

I file gia' cifrati non vengono toccati: viene solo aggiornato il modo in
cui la password sblocca la chiave interna. Da qui in poi usa la nuova
password (aggiorna anche `FILESYNC_PW_...`).

### 5. Recupero da parte dell'amministratore (chiave master)

Se un collega ha perso sia la password che l'email con la chiave di
recovery (es. e' andato via dall'azienda), solo tu puoi comunque
recuperare l'accesso al suo progetto:

```bash
python -m filesync recover "//SERVER/Backup/PLC" \
  --master-private-key ./keys/master_private.pem \
  --new-password "nuova-password-che-assegni-tu"
```

Ti verra' chiesta la passphrase della chiave master. Da qui puoi anche
decifrare subito tutto per controllare/recuperare i file:

```bash
python -m filesync open "//SERVER/Backup/PLC" ./PLC_recuperato \
  --master-private-key ./keys/master_private.pem
```

## Proteggere ANCHE la cartella locale (source), non solo il backup

Tutto quello visto finora protegge la **copia sul server** (`destination`):
la cartella locale (`source`) resta un progetto normale in chiaro, perche'
devi poterci lavorare con l'IDE/interprete Python senza attriti.

Se pero' anche la cartella locale e' su una macchina/VM condivisa con altri
(non solo tuo PC personale), e vuoi impedire che **altri account dello
stesso sistema** possano leggere o modificare i sorgenti prima ancora che
partano verso il server, usa:

```bash
python -m filesync protect ./MioProgettoPython     # blocca l'accesso ad altri utenti
python -m filesync unprotect ./MioProgettoPython    # ripristina i permessi di prima
```

**Cosa fa davvero**: imposta i permessi del sistema operativo in modo che
solo il tuo utente possa leggere/scrivere in quella cartella (su Linux:
`chmod` proprietario-soltanto; su Windows: ACL via `icacls` limitata al
tuo utente). Non serve "sbloccare" nulla per lavorarci: i file restano
normali file in chiaro, editabili ed eseguibili subito.

**Cosa NON fa**: non e' cifratura. Non impedisce a un amministratore/root
della macchina di leggere comunque i file, e su alcune cartelle condivise
VMware (mount `vmhgfs-fuse`) i permessi POSIX potrebbero non essere
realmente applicati dall'host Windows — verificalo prima di fidartene su
una cartella condivisa VM. Se ti serve protezione anche da un
amministratore locale, l'unica soluzione reale e' la cifratura vista
sopra, ma richiederebbe di "sbloccare/bloccare" la cartella ogni volta
che ci lavori (un container cifrato tipo VeraCrypt/BitLocker) — se ti
interessa questo livello, fammelo sapere e lo implementiamo come modalita'
a parte.

In sintesi, con `protect` + la cifratura della destinazione hai entrambe
le cose richieste con lo stesso strumento: sorgente locale bloccata per
gli altri utenti del sistema, backup sul server illeggibile senza
password/chiave.

## Cifrare/decifrare una cartella "una tantum" (senza recovery)

Per un uso manuale semplice, senza envelope/recovery/master, restano
disponibili i comandi diretti (solo password):

```bash
python -m filesync encrypt ./MioProgetto ./MioProgetto_cifrato
python -m filesync decrypt ./MioProgetto_cifrato ./MioProgetto_ripristinato
```

## Cartelle condivise VMware

VMware (Workstation/Fusion/Player) espone le "Shared Folders" del guest
come un normale percorso del filesystem, quindi non serve nessuna
integrazione specifica: basta indicare quel percorso come `source` o
`destination` nel job.

- **Guest Windows**: tipicamente `\\vmware-host\Shared Folders\NomeCondivisione`,
  oppure mappata a una lettera di rete (es. `Z:`).
- **Guest Linux**: dopo aver installato gli open-vm-tools e montato le
  shared folders (`vmhgfs-fuse`), tipicamente `/mnt/hgfs/NomeCondivisione`.

## Automatizzare l'esecuzione

### Linux/macOS (cron)

```
*/15 * * * * FILESYNC_PW_PLC="..." FILESYNC_PW_HMI="..." /usr/bin/python3 -m filesync sync -c /percorso/config.yaml >> /percorso/filesync.log 2>&1
```

### Windows (Task Scheduler)

Crea un'attivita' pianificata che esegue:

```
python -m filesync sync -c C:\percorso\config.yaml
```

impostando le variabili d'ambiente delle password a livello di
sistema/utente (Pannello di controllo → Variabili d'ambiente), non nel
task stesso in chiaro.

## Esclusioni

```yaml
exclude:
  - "*.tmp"
  - "~$*"
  - ".git"
  - "__pycache__"
```

## Test

```bash
python -m pytest tests/ -v
```

## Note di sicurezza

- La cifratura protegge il **contenuto** dei file; i nomi restano
  visibili con suffisso `.enc`.
- La chiave privata master (`master_private.pem`) e la sua passphrase sono
  l'unico modo per recuperare TUTTI i progetti: proteggile come faresti
  con la chiave di un caveau (backup offline, non su git, non sul server).
- La chiave pubblica master invece e' sicura da distribuire: non permette
  di decifrare nulla, solo di "chiudere il lucchetto" per te.
- Se un progetto non ha ne' `recovery_email` ne' `master_public_key`
  configurati, e la password personale va persa, quel progetto **non e'
  recuperabile per design** — configura sempre almeno uno dei due per i
  backup che contano.
