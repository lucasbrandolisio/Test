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
- **Versioni storiche dei file modificati** (`keep_versions`, default 5):
  prima di sovrascrivere un file cambiato in destinazione, la versione
  precedente viene conservata. Protegge da ransomware: se un malware
  cifra/corrompe i file in locale, la sync propaga inevitabilmente anche
  quella versione, ma le versioni buone precedenti restano recuperabili
  con `filesync versions`/`restore-version`. Vedi la sezione dedicata.
- **Modalita' watch**: gira in loop e sincronizza automaticamente ad
  intervalli regolari.
- **Cifratura delle cartelle** (AES via `cryptography.Fernet`) cosi' chi
  ha accesso al server non puo' leggere il codice sorgente.
- **Vault locale (`lock`/`unlock`)**: protegge anche la cartella dove
  lavori, non solo il backup. Quando chiudi l'IDE/TIA Portal e blocchi il
  vault, i file (nomi compresi) vengono cifrati e la cartella in chiaro
  viene cancellata: chi altro usa lo stesso PC non trova ne' il contenuto
  ne' i nomi dei file. `protect`/`unprotect` offrono invece un livello piu'
  leggero (permessi del sistema operativo, nessun blocco/sblocco).
- **Configurazione visuale** (`filesync setup` / `filesync tray`,
  opzionale): aggiungi/rimuovi progetti scegliendo le cartelle da una
  finestra ("Sfoglia..."), senza mai editare `config.yaml` a mano; le
  password finiscono nel gestore credenziali del sistema operativo, non
  in un file. Pensato per essere installato su piu' PC di colleghi senza
  bisogno di configurazione manuale su ciascuno.
- **Icona nella system tray** (`filesync tray`, opzionale): sync
  automatica in background + blocco/sblocco vault dal menu con un click +
  notifica se un vault resta sbloccato troppo a lungo. Vedi sezione
  dedicata piu' sotto.
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

Richiede Python 3.9+. Nessuna dipendenza aggiuntiva per l'email, le
chiavi master o i vault: usano solo `cryptography` (gia' richiesta) e la
libreria standard di Python. Solo la GUI a icona (`filesync tray`, vedi
sotto) richiede pacchetti extra, in `requirements-tray.txt`.

## Avvio rapido per i colleghi (senza editare file a mano)

Questo e' il percorso pensato per installare filesync sul PC di un
collega senza dover editare YAML, impostare variabili d'ambiente o
lavorare da riga di comando:

```bash
pip install -r requirements.txt -r requirements-tray.txt
python -m filesync tray -c config.yaml
```

Al primo avvio (o se `config.yaml` non esiste ancora) si apre subito una
finestra dove si aggiungono i progetti scegliendo le cartelle con
"Sfoglia...", senza toccare nessun file: **Aggiungi vault locale**
(protegge una cartella con `lock`/`unlock`, vedi sotto) o **Aggiungi
backup su server** (sync verso una cartella di rete, con cifratura
opzionale). Le password inserite li' vengono salvate nel gestore di
credenziali del sistema operativo (Windows Credential Manager / Keychain
/ Secret Service) tramite `keyring`, **mai** nel file di configurazione:
non serve piu' `password_env` ne' variabili d'ambiente per l'uso normale.

Da quel momento resta un'icona nella system tray con tutto il necessario
nel menu (sync manuale, blocca/sblocca vault, riapri "Gestisci
progetti..." per aggiungerne altri o rimuoverne). Puoi riaprire la stessa
finestra in qualsiasi momento anche senza la tray:

```bash
python -m filesync setup -c config.yaml
```

(richiede solo `keyring`, non `pystray`/`Pillow`: se non vuoi l'icona in
tray ma solo configurare/usare da riga di comando puoi installare solo
quello: `pip install keyring`)

## Uso rapido da riga di comando (avanzato / scripting)

Per automazione, scheduler (Task Scheduler/cron) o chi preferisce
editare `config.yaml` a mano, resta disponibile il percorso classico:

```bash
cp config.example.yaml config.yaml   # poi modifica sorgenti/destinazioni
python -m filesync sync -c config.yaml            # sincronizzazione singola
python -m filesync sync -c config.yaml --watch     # in continuo (ogni 60s)
python -m filesync sync -c config.yaml --dry-run   # prova senza modificare nulla
python -m filesync sync -c config.yaml --job PLC   # solo un progetto
```

Con `password_env`, come descritto nelle sezioni successive, se preferisci
gestire le password tramite variabili d'ambiente invece del gestore
credenziali del sistema (es. per l'uso su uno scheduler/server).

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

## Protezione da ransomware: versioni storiche dei file

**Limite onesto da capire prima**: filesync da solo NON blocca un
ransomware. Se un malware infetta il PC locale e cifra/corrompe i tuoi
file in-place (stesso nome, contenuto compromesso), la prossima sync vede
"il file e' cambiato" e lo ricopia sul server — **sovrascrivendo l'ultima
copia buona con quella gia' compromessa**. Nessun tool di sync puro puo'
evitarlo del tutto: il PC che sincronizza ha per forza accesso in
scrittura alla destinazione.

Quello che filesync PUO' fare, e fa di default, e' tenere una **cronologia
delle versioni precedenti**, cosi' anche se l'ultima sync propaga il
danno, le versioni buone di prima restano recuperabili:

```yaml
jobs:
  - name: "PLC"
    ...
    keep_versions: 5   # default gia' 5; 0 disattiva lo storico
```

Prima di sovrascrivere un file cambiato, la versione precedente finisce in
`<destinazione>/.filesync_versions/<percorso>/<timestamp>`, tenendo solo
le ultime `keep_versions` per file (le piu' vecchie vengono scartate
automaticamente). Per vedere ed recuperare una versione:

```bash
python -m filesync versions "//SERVER/Backup/PLC" main.st
# elenca i timestamp disponibili, es. 20260718-091500, 20260719-140212, ...

python -m filesync restore-version "//SERVER/Backup/PLC" main.st 20260718-091500 ./recuperato.st
```

Per un file di un job **cifrato**, usa lo stesso percorso con `.enc` e
passa la password/chiave di recovery/chiave master come per `open`:

```bash
python -m filesync restore-version "//SERVER/Backup/PLC" main.st.enc 20260718-091500 ./recuperato.st --password "..."
```

**Quanto ti protegge davvero**: se il ransomware agisce e viene notato
entro poche sincronizzazioni, hai le versioni buone precedenti a
disposizione. Se il ransomware resta silente per settimane prima di
agire (tattica comune), `keep_versions: 5` potrebbe non bastare — alza il
numero (a costo di piu' spazio disco) se ti preoccupa questo scenario. Per
una protezione seria servono anche misure lato server che questo tool non
puo' sostituire: snapshot immutabili (Volume Shadow Copy di Windows,
snapshot ZFS/BTRFS o del tuo NAS), un account di scrittura dedicato al
backup con permessi il piu' possibile limitati, e idealmente una copia
offline/air-gapped periodica.

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

Ci sono due livelli, a seconda di chi puo' accedere al tuo computer.

### Livello 1 — `protect`: altri utenti dello stesso sistema operativo

```bash
python -m filesync protect ./MioProgettoPython     # blocca l'accesso ad altri utenti
python -m filesync unprotect ./MioProgettoPython    # ripristina i permessi di prima
```

Imposta i permessi del sistema operativo (chmod proprietario-soltanto su
Linux, ACL via `icacls` su Windows). Comodo perche' non serve "sbloccare"
nulla per lavorarci. **Ma non impedisce a un amministratore/root della
stessa macchina di leggere comunque i file** — se il PC puo' essere usato
anche da colleghi con un loro account (o con accesso admin), questo livello
non basta.

### Livello 2 — `lock`/`unlock`: vault cifrato, protezione reale

Se il computer puo' essere preso in mano da altri colleghi, l'unico modo
per essere sicuri che **nessuno** possa aprire i tuoi `.py` (o vedere
anche solo che file ci sono) e' non lasciarli mai in chiaro sul disco
quando non ci stai lavorando. Per questo esiste il vault:

```bash
# 1. lavori normalmente su ./MioProgetto con VS Code / TIA Portal
# 2. quando hai finito (o ti allontani dal PC):
#    CHIUDI PRIMA l'editor/TIA Portal, poi:
python -m filesync lock ./MioProgetto ./MioProgetto.vault --password "una-password-lunga"
```

Cosa succede: ogni file viene cifrato con un nome casuale (nessuna traccia
del nome o della struttura originale) dentro `MioProgetto.vault`, e solo
DOPO aver verificato che tutto ridecifra correttamente, `./MioProgetto`
viene **cancellata per davvero**. A quel punto un collega che apre quella
cartella non trova assolutamente nulla — non esiste piu' — e se apre
`MioProgetto.vault` trova solo file con nomi tipo `9f2a...blob`, contenuto
illeggibile, nessun `.py` visibile.

Quando vuoi tornare a lavorarci:

```bash
python -m filesync unlock ./MioProgetto.vault ./MioProgetto --password "una-password-lunga"
# ...apri VS Code / TIA Portal, lavori...
# poi richiudi l'editor e rilancia 'lock'
```

Anche qui vale il sistema di recupero password a tre livelli (vedi sopra):
puoi passare `--recovery-email` e/o `--master-public-key` a `lock` la
prima volta che crei un vault, cosi' se dimentichi la password (o vuoi
poter recuperare i vault dei colleghi come amministratore) non perdi
l'accesso:

```bash
python -m filesync lock ./MioProgetto ./MioProgetto.vault \
  --recovery-email "tu@azienda.it" \
  --master-public-key ./keys/master_public.pem
```

**Compromesso da accettare**: mentre il vault e' sbloccato (mentre ci
lavori con l'editor aperto), i file sono in chiaro sul disco come sempre
— e' inevitabile, un IDE deve poter leggere file veri. La protezione vale
per il tempo in cui NON stai lavorando (PC lasciato incustodito, spento,
prestato). Per la massima sicurezza anche mentre lavori, puoi combinare i
due livelli: `protect` sulla cartella sbloccata mentre e' aperta.

### Backup sul server: il vault e' gia' pronto per la sync

Il vault e' gia' cifrato: per fare il backup sul server basta un job di
sync **senza** `encrypt: true`, con `source` uguale alla cartella vault —
i file vengono copiati cosi' come sono, gia' illeggibili:

```yaml
jobs:
  - name: "MioProgetto-vault"
    source: "./MioProgetto.vault"
    destination: "//SERVER/Backup/MioProgetto"
    mirror: false
    encrypt: false   # non serve: il contenuto e' gia' cifrato dal vault
```

Nota: ogni `lock` rigenera nomi casuali nuovi per tutti i blob (anche per
i file non modificati), quindi la sync successiva ricarichera' l'intero
vault invece che solo le differenze — un compromesso accettabile dato che
di solito si blocca/sblocca poche volte al giorno, non in continuo.

## Icona nella system tray (GUI)

Per non dover lanciare i comandi a mano ogni volta, `filesync tray` mette
un'icona nella barra delle applicazioni che:

- al primo avvio (o con "Gestisci progetti...") apre la finestra per
  aggiungere/rimuovere progetti scegliendo le cartelle con "Sfoglia...",
  senza editare `config.yaml` a mano (vedi "Avvio rapido per i colleghi"
  piu' sopra);
- sincronizza automaticamente i job in background (come `sync --watch`,
  ma senza tenere un terminale aperto);
- mostra nel menu i vault configurati con un'unica voce **Blocca/Sblocca**
  per ciascuno — click, inserisci la password (o la legge dal gestore
  credenziali del sistema se l'hai salvata dalla GUI), fatto;
- avvisa con una notifica se un vault resta sbloccato per piu' di
  `warn_after_minutes` (default 30), ripetendo il promemoria finche' non
  lo blocchi — pensato esattamente per il caso "mi allontano dal PC e me
  ne dimentico";
- avvisa con una notifica anche in caso di errore di sincronizzazione.

### Installazione e avvio

```bash
pip install -r requirements-tray.txt   # pystray + Pillow, non servono al resto di filesync
python -m filesync tray -c config.yaml
```

Su Windows e macOS non serve altro (tkinter, usato per le finestre di
richiesta password, e' incluso nell'installer ufficiale di Python). Su
Linux con desktop minimale potrebbe servire anche il pacchetto di sistema
`python3-tk`, e un ambiente con supporto system tray (su GNOME serve
l'estensione AppIndicator/KStatusNotifierItem — senza un desktop grafico
con tray, tipo una sessione SSH pura, non puo' funzionare).

Per avviarla automaticamente all'accesso, aggiungila alle app di avvio di
Windows (Esegui → `shell:startup`, crea un collegamento a
`pythonw -m filesync tray -c C:\percorso\config.yaml`, usando `pythonw`
invece di `python` per non aprire una finestra di console).

**Nota**: la parte visiva (icona/menu/notifiche) e' stata scritta e
documentata con cura ma non e' stata verificabile in questo ambiente di
sviluppo (nessun display grafico disponibile) — la logica sottostante
(quando sincronizzare, quando avvisare) e' invece coperta da test
automatici. Provala sulla tua macchina e segnala eventuali problemi.

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
