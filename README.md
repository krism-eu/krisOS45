# KrisOS45

Fedora 45 bootc Minimal con SELinux enforcing e un OverlayFS persistente e
ricostruibile su `/usr`. La base immutabile resta proprietà di bootc/OSTree;
KrisOS aggiunge il lifecycle dell'overlay, il package layer ristretto `rk`, i
controlli di recovery e la propria pipeline di release.

## Branch e artefatti

La branch runtime è `main`. Costruisce e firma l'immagine bootc
`ghcr.io/krism-eu/krisos45:build-<run_id>-<attempt>`. La branch `iso` contiene il
percorso installer/ISO separato e incorpora un payload immutabile già validato;
non ricostruisce una seconda implementazione del sistema operativo.

Durante Fedora 45 Branched il `Containerfile` segue
`fedora-bootc-45-minimal:latest`; ogni build risolve `latest` a un digest esatto
e il delta RPM installato durante il build viene invece risolto dai repository
Fedora firmati disponibili in quel momento: per questo una ricostruzione
successiva può scegliere NEVRA differenti. Ogni build salva `owned-nevra.txt`,
la provenance del firmware RTL e un diff informativo rispetto al tag `m1`
precedente. L'output pubblicato resta identificato in modo immutabile dal digest
OCI e dalla firma Cosign.

## Overlay `/usr`

Il mount avviene in real-root userspace dopo `ostree-remount.service` e prima di
`local-fs.target`. Lo stato è in `/var/lib/krisos/`:

```text
/var/lib/krisos/
├── deployment      # stateroot/OSTREE_COMMIT/DEPLOYSERIAL
├── packages.list   # richieste RPM esplicite dell'utente
├── pending         # rebuild richiesto o transazione RPM interrotta
├── needs-sync      # ricostruzione package layer richiesta
├── lock            # lock di rk
├── upper/          # cache OverlayFS ricostruibile
└── work/
```

`BOOTCSUM` serve a localizzare il bootlink ma non identifica la cache. L'hook
risolve il target OSTree e usa `STATEROOT/COMMIT/DEPLOYSERIAL`. Stesso deployment
significa upper conservato **solo se** entrambe le directory `upper/` e `work/`
sono ancora presenti. Deployment differente, identità assente, transazione
interrotta oppure cache mancante/invalida significano upper/work ricreati e
`needs-sync` armato. Prima di montare un nuovo upper viene resa persistente con
`sync -f` la transizione di recovery, in modo che una nuova identità non possa
diventare durevole prima del reset della vecchia cache.

Qualunque errore dell'hook resta fail-open: il sistema continua sulla `/usr`
immutabile e il sync automatico non viene considerato pronto.

## `rk`

`rk` usa libdnf5 e la rpmdb reale sotto `/usr`. È deliberatamente più ristretto
di DNF generico: solo nomi pacchetto esatti, `x86_64`/`noarch`, nessuna modifica
di pacchetti immutabili, firme RPM obbligatorie, niente scriptlet o trigger del
pacchetto entrante e niente payload che controlli trust, boot o stato
persistente.

Oltre ai namespace Fedora 45 di repository/chiavi/RPM, sono protetti tra gli
altri `sysusers.d`, `tmpfiles.d`, udev, unit e generator systemd, PAM, polkit,
sysctl, NetworkManager, dracut e kernel policy. I symlink dichiarati dentro lo
stesso RPM vengono risolti dal manifest `%{FILELINKTOS}` prima della transazione;
file speciali, setuid/setgid e `%{FILECAPS}` sono rifiutati, così non possono
usare un percorso apparentemente innocuo per uscire da `/usr` o raggiungere un
namespace protetto.

Gli RPM overlay non hanno un timer di upgrade autonomo. Le versioni richieste
vengono rivalutate quando l'upper viene ricostruito dopo un cambio deployment o
quando root arma manualmente `sudo rk refresh`; quest'ultimo valida prima, senza
modifiche RPM, le richieste contro i repository correnti e poi usa `pending` per
forzare il rebuild al reboot. `krisos-sync.timer` non è un refresh DNF: ritenta
soltanto una ricostruzione già richiesta da `needs-sync`.

## Cadenza immagini

Durante Fedora 45 Branched una build automatica ogni due giorni segue la Minimal
`:latest`. GitHub risolve `:latest` a un digest preciso, esegue i gate e, sul
percorso di pubblicazione, produce e firma un candidate immutabile. Il tag mobile
`ghcr.io/krism-eu/krisos45:m1` non viene aggiornato automaticamente: avanza solo
tramite `promote-m1.yml`, dopo autorizzazione dell'environment protetto e verifica
Cosign del digest firmato. La promotion confronta inoltre le label
`org.opencontainers.image.revision` e accetta normalmente solo candidate il cui
commit discende da quello dell'attuale `m1`; un rollback richiede l'input manuale
esplicito `allow_rollback=true`. I controlli su host installato restano manuali e
separati dalla promotion. Il sistema installato non si aggiorna da solo:
`bootc-fetch-apply-updates.timer` è mascherato nell'immagine e l'utente decide
quando eseguire l'update. Dopo Fedora 45 stable la build candidate passa a
cadenza settimanale.

`krisCC` non avvia automaticamente nuove build KrisOS: resta congelato
nell'immagine finché una release non viene adottata deliberatamente.

## Build locale

```bash
bash scripts/fetch-kriscc-component.sh
resolved_base="$(bash scripts/resolve-base.sh)"
sudo podman build --pull=always --build-arg "BASE_IMAGE=$resolved_base" \
  -t localhost/krisos45:m1 .
```

Per il gate locale completo usare `./tests/local-hardening-check.sh`, che esegue
la stessa risoluzione a digest prima della build.

La release CI esegue i test di policy, costruisce l'immagine, prova una vera
transazione libdnf5/RPM in container, cattura la provenance pacchetti e, sul
percorso publish, pubblica un tag immutabile per build, firma il digest con
Cosign e verifica il pull anonimo.

La release image-owned di krisCC è definita esclusivamente da
`build_files/krisCC.lock`, che contiene tag, nome dell'RPM e SHA-256. L'asset è
installato con l'eccezione locale `rpm --nosignature` dopo la verifica del lock;
questa eccezione non modifica la policy di firma di DNF/`rk`.

## Validazione host manuale

I container non certificano OverlayFS reale, reboot o recovery.
`tests/boot-check.sh` e `tests/release-check.sh` restano strumenti manuali per
controllare un sistema installato; non sono invocati dalla promotion automatica
di `m1`. `release-check.sh` conserva i modi prepare/verify per verificare, quando
serve, persistenza sullo stesso deployment, invalidazione dopo un cambio
deployment e recovery da una transazione interrotta. L'orchestrazione SSH/VM
dedicata è stata rimossa perché non faceva più parte del percorso di release.

Vedi `docs/RELEASE_VALIDATION.md` e `docs/RK.md` per i gate completi.

## Layout repository

```text
.
├── .containerignore
├── .github/workflows/
│   ├── promote-m1.yml
│   ├── publish-candidate.yml
│   └── sync-kriscc.yml
├── ARCHITECTURE.md
├── Containerfile
├── HARDENING_FINAL.md
├── README.md
├── bin/
│   └── rk
├── build_files/
│   ├── 55-krisos-hardening.conf
│   ├── 60-krisos-runtime-state.conf
│   ├── 90-krisos-privacy.repo
│   ├── 99krisos-nss/
│   ├── KDE-UserFeedback.conf
│   ├── NetworkManager.state
│   ├── base-packages.txt
│   ├── dnf-krisos.conf
│   ├── krisCC.lock
│   └── tmpfiles-krisos.conf
├── docs/
│   ├── BUILD-CADENCE.md
│   ├── FEDORA45-PORT.md
│   ├── M1-NOTES.md
│   ├── RELEASE_VALIDATION.md
│   └── RK.md
├── scripts/
│   ├── check-initramfs-accounts.sh
│   ├── fetch-kriscc-component.sh
│   ├── repair-home-labels.sh
│   └── resolve-base.sh
├── systemd/
│   ├── krisos-overlay.service
│   ├── krisos-overlay.sh
│   ├── krisos-sync.service
│   └── krisos-sync.timer
├── tests/
│   ├── boot-check.sh
│   ├── local-hardening-check.sh
│   ├── release-check.sh
│   ├── release-state.py
│   ├── source-hardening-check.sh
│   ├── test_overlay_identity.py
│   ├── test_overlay_recovery.py
│   ├── test_release_shell.py
│   ├── test_release_state.py
│   ├── test_rk.py
│   ├── test_rk_container.py
│   └── test_rk_recovery.py
└── tools/
    └── source_snapshot.py
```

## Riparazione manuale delle label SELinux della home

L'immagine installa `/usr/libexec/krisos/repair-home-labels` come strumento
manuale e conservativo per diagnosticare o ripristinare le label SELinux sui
quattro percorsi persistenti già previsti dalla policy KrisOS: `$HOME`,
`$HOME/.config`, `$HOME/.local` e `$HOME/.local/share`.

La home dell'utente deve risolversi direttamente sotto `/var/home`; una home
annidata o non canonica viene rifiutata. Senza `--apply` lo script usa
`restorecon -n -v` e mostra soltanto l'anteprima. La modifica reale richiede
root:

```bash
sudo /usr/libexec/krisos/repair-home-labels USER
sudo /usr/libexec/krisos/repair-home-labels --apply USER
```

Non è un servizio e non viene eseguito automaticamente al boot. Il gate
container esercita il percorso di anteprima valido e il rifiuto di una home
annidata.

## Recovery

Aggiungere temporaneamente `krisos.overlay=off` alla kernel command line. L'hook
salta il mount senza cancellare cache o intent e il sync automatico resta
inibito. SELinux enforcing rimane parte del contratto supportato.
