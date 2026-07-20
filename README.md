# filesync

Strumento a riga di comando per tenere sincronizzate cartelle di progetto
(es. progetti PLC) tra il computer locale e un server aziendale, con
supporto per cartelle condivise VMware e cifratura opzionale dei file
in destinazione.

## Funzionalita'

- **Sync incrementale**: copia solo i file nuovi o modificati (confronto
  su dimensione e data di modifica), non ricopia tutto ogni volta.
- **Modalita' mirror opzionale**: se un file viene cancellato dalla
  sorgente, puo' essere cancellato anche dal backup (`mirror: true`),
  oppure lasciato come archivio storico (`mirror: false`, default).
- **Piu' progetti in un unico file di configurazione** (`config.yaml`),
  ognuno con la propria sorgente/destinazione/regole.
- **Modalita' watch**: gira in loop e sincronizza automaticamente ad
  intervalli regolari (utile per un backup "sempre attivo").
- **Cifratura delle cartelle**: i file possono essere cifrati (AES via
  `cryptography.Fernet`, chiave derivata dalla password con
  PBKDF2-HMAC-SHA256) prima di finire sul server, cosi' chi ha accesso
  al server non puo' leggere il codice sorgente. Disponibile sia come
  comando standalone (`encrypt`/`decrypt`) sia integrata nella sync
  (`encrypt: true` nel job).
- **Percorsi VMware Shared Folders**: nessuna integrazione speciale
  necessaria, vedi sotto.

## Installazione

```bash
pip install -r requirements.txt
```

Richiede Python 3.9+.

## Uso rapido

1. Copia `config.example.yaml` in `config.yaml` e modifica sorgenti/destinazioni:

   ```bash
   cp config.example.yaml config.yaml
   ```

2. Esegui una sincronizzazione singola:

   ```bash
   python -m filesync sync -c config.yaml
   ```

3. Oppure lasciala girare in continuo (ogni 60 secondi di default):

   ```bash
   python -m filesync sync -c config.yaml --watch --interval 60
   ```

4. Prova prima senza modificare nulla con `--dry-run`:

   ```bash
   python -m filesync sync -c config.yaml --dry-run
   ```

### Sincronizzare un solo progetto

```bash
python -m filesync sync -c config.yaml --job ProgettoPLC1
```

## Cifrare/decifrare una cartella manualmente

```bash
# cifra tutti i file di una cartella (chiede la password in modo sicuro)
python -m filesync encrypt ./MioProgettoPLC ./MioProgettoPLC_cifrato

# decifra (serve la stessa password usata in fase di cifratura)
python -m filesync decrypt ./MioProgettoPLC_cifrato ./MioProgettoPLC_ripristinato
```

I nomi dei file cifrati diventano `<nome>.enc`; la struttura delle
sottocartelle viene mantenuta. Il "salt" usato per derivare la chiave
viene salvato (in chiaro, non e' un segreto) in un file `.filesync_salt`
nella cartella di destinazione: serve per rigenerare la stessa chiave a
partire dalla password nelle sincronizzazioni successive, senza dover
ricifrare tutto ogni volta.

## Cifratura integrata nella sync (job con `encrypt: true`)

Nel `config.yaml`:

```yaml
jobs:
  - name: "ProgettoPLC2-VMwareShared"
    source: "/mnt/hgfs/SharedVM/PLC2"
    destination: "//SERVER/Backup/PLC2"
    mirror: true
    encrypt: true
    password_env: "FILESYNC_PASSWORD"
```

**La password non va mai scritta nel file di configurazione.** Va
impostata come variabile d'ambiente (qui `FILESYNC_PASSWORD`) prima di
lanciare lo script, ad esempio:

```bash
export FILESYNC_PASSWORD="una-password-lunga-e-robusta"
python -m filesync sync -c config.yaml
```

Su Windows (PowerShell):

```powershell
$env:FILESYNC_PASSWORD = "una-password-lunga-e-robusta"
python -m filesync sync -c config.yaml
```

In questo modo sul server arrivano solo file cifrati: chi ha accesso
alla cartella di rete non puo' aprire/leggere il codice sorgente senza
conoscere la password.

## Cartelle condivise VMware

VMware (Workstation/Fusion/Player) espone le "Shared Folders" del
guest come un normale percorso del filesystem, quindi non serve nessuna
integrazione specifica: basta indicare quel percorso come `source` o
`destination` nel job.

- **Guest Windows**: la cartella condivisa compare tipicamente come
  `\\vmware-host\Shared Folders\NomeCondivisione`, oppure puoi mapparla
  a una lettera di rete (es. `Z:`).
- **Guest Linux**: dopo aver installato gli open-vm-tools e montato le
  shared folders (`vmhgfs-fuse`), il percorso e' tipicamente
  `/mnt/hgfs/NomeCondivisione`.

Esempio: se i tuoi progetti PLC sono su una VM e la cartella e'
condivisa verso l'host, puoi impostare `source` sul percorso montato
(`/mnt/hgfs/...` o `\\vmware-host\Shared Folders\...`) e `destination`
sul percorso di rete del server aziendale: lo script fa da ponte tra i
due, con backup automatico se lanciato in `--watch` o pianificato (vedi
sotto).

## Automatizzare l'esecuzione

### Linux/macOS (cron)

```
*/15 * * * * FILESYNC_PASSWORD="..." /usr/bin/python3 -m filesync sync -c /percorso/config.yaml >> /percorso/filesync.log 2>&1
```

### Windows (Task Scheduler)

Crea un'attivita' pianificata che esegue:

```
python -m filesync sync -c C:\percorso\config.yaml
```

impostando la variabile d'ambiente `FILESYNC_PASSWORD` a livello di
sistema/utente (Pannello di controllo -> Variabili d'ambiente), non nel
task stesso in chiaro.

## Esclusioni

Ogni job puo' avere una lista `exclude` di pattern glob (applicati sia
al nome file/cartella sia al percorso relativo), utile per ignorare
file temporanei, cartelle `.git`, cache dei tool PLC, ecc.:

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

- La cifratura protegge il **contenuto** dei file (il codice sorgente);
  i nomi dei file restano visibili con suffisso `.enc`.
- Password deboli rendono la cifratura inutile: usa una password lunga
  e non riutilizzata altrove.
- Se perdi la password, i file cifrati **non sono recuperabili**: non
  esiste un meccanismo di recupero per design.
