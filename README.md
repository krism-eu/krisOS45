# KrisOS45

Fedora 45 bootc Minimal con SELinux enforcing e un OverlayFS persistente e
ricostruibile su `/usr`. La base immutabile resta proprietà di bootc/OSTree;
KrisOS aggiunge il lifecycle dell'overlay, il package layer ristretto `rk`, i
controlli di recovery e la propria pipeline di release.

## Branch e artefatti

La branch runtime è `main`. Costruisce e firma l'immagine bootc
`ghcr.io/krism-eu/krisos45:<commit>`. La branch `k1.0-final-iso` contiene solo
l'installer e incorpora per digest un payload già validato e firmato; non
ricostruisce una seconda copia del sistema operativo.

Durante Fedora 45 Branched il `Containerfile` segue `fedora-bootc-45-minimal:latest`; ogni build risolve `latest` a un digest esatto e il delta
RPM installato durante il build viene invece risolto dai repository Fedora
firmati disponibili in quel momento: per questo una ricostruzione successiva
può scegliere NEVRA differenti. Ogni build salva `owned-nevra.txt`, la
provenance del firmware RTL e un diff informativo rispetto al tag `m1` promosso.
L'output pubblicato resta identificato in modo immutabile dal digest OCI e dalla
firma Cosign.

## Overlay `/usr`

Il mount avviene in real-root userspace dopo `ostree-remount.service` e prima di
`local-fs.target`. Lo stato è in `/var/lib/krisos/`:

```text
/var/lib/krisos/
├── deployment      # stateroot/OSTREE_COMMIT/DEPLOYSERIAL
├── packages.list   # richieste RPM esplicite dell'utente
├── pending         # transazione RPM interrotta, se presente
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
`needs-sync` armato. Prima di montare un
nuovo upper viene resa persistente con `sync -f` la transizione di recovery, in
modo che una nuova identità non possa diventare durevole prima del reset della
vecchia cache.

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
file speciali, setuid/setgid e `%{FILECAPS}` sono rifiutati,
così non possono usare un percorso apparentemente innocuo per uscire da `/usr`
o raggiungere un namespace protetto.

Gli RPM overlay non hanno un timer di upgrade autonomo. Il ciclo supportato per
rivalutare le versioni richieste è la ricostruzione dell'upper dopo un cambio
deployment. `krisos-sync.timer` non è un refresh DNF: ritenta soltanto una
ricostruzione già richiesta da `needs-sync`.

## Cadenza immagini

Durante Fedora 45 Branched una build automatica giornaliera segue la Minimal `:latest`. GitHub risolve `:latest` a un digest preciso, esegue tutti i gate e aggiorna `ghcr.io/krism-eu/krisos45:m1` soltanto se la build è verde. Il sistema installato non si aggiorna da solo: `m1` è semplicemente l'ultima immagine pronta quando l'utente decide di eseguire l'update. Dopo Fedora 45 stable la stessa build passa a cadenza settimanale.

`krisCC` non avvia automaticamente nuove build KrisOS: resta congelato nell'immagine finché la versione applicativa non viene dichiarata definitiva.

## Build locale

```bash
bash scripts/fetch-kriscc-component.sh
sudo podman build -t localhost/krisos45:m1 .
```

La release CI esegue i test di policy, costruisce l'immagine, prova una vera
transazione libdnf5/RPM in container, cattura la provenance pacchetti e, sul
percorso publish, pubblica un tag per commit, firma il digest con Cosign e
verifica il pull anonimo.

Il componente image-owned è congelato su `krisCC 0.7.10-1.fc45` mentre il lavoro applicativo prosegue separatamente
con la precedente release. È l'eccezione nota del port F45: il successivo lavoro
sul componente deve produrre un RPM `fc45` con firma/provenance verificabile e
rimuovere l'uso locale di `rpm --nosignature`. Questa eccezione non modifica la
policy di firma di DNF/`rk`.

## Validazione VM

I container non certificano OverlayFS reale, reboot o recovery. Il gate VM usa
`tests/run-release-vm.sh`. Con `KRISOS_E2E_SWITCH_IMAGE` impostato verifica sia
la persistenza sullo stesso deployment sia l'invalidazione su cambio deployment:
la sentinella viene scritta sotto `/usr/share/krisos-e2e` e deve esistere anche
fisicamente in `/var/lib/krisos/upper`; dopo `bootc switch` deve sparire da
entrambi. Il test confronta inoltre l'identità derivata dal bootlink con
`bootc status --format json --format-version 1` e con il file `deployment`.

Dopo uno switch il harness ricostruisce anche il policy store SELinux con
`semodule -B`; i successivi controlli `matchpathcon` assicurano che il contratto
`/var/home` sopravviva all'upgrade.

Vedi `docs/RELEASE_VALIDATION.md` e `docs/RK.md` per i gate completi.

## Layout repository

```text
.
├── .containerignore
├── .github/workflows/
│   ├── build-m1.yml
│   ├── promote-m1.yml
│   └── sync-kriscc.yml
├── ARCHITECTURE.md
├── Containerfile
├── README.md
├── bin/
│   └── rk
├── build_files/
│   ├── 55-krisos-hardening.conf
│   ├── 90-krisos-privacy.repo
│   ├── 99krisos-nss/
│   ├── KDE-UserFeedback.conf
│   ├── NetworkManager.state
│   ├── base-packages.txt
│   ├── dnf-krisos.conf
│   ├── krisCC-autostart.desktop
│   ├── krisCC.lock
│   └── tmpfiles-krisos.conf
├── docs/
│   ├── FEDORA45-PORT.md
│   ├── M1-NOTES.md
│   ├── RELEASE_VALIDATION.md
│   ├── RK.md
│   └── corrective-update-0.7.0-6.md
├── scripts/
│   ├── check-initramfs-accounts.sh
│   ├── fetch-kriscc-component.sh
│   └── repair-home-labels.sh
├── systemd/
│   ├── krisos-overlay.service
│   ├── krisos-overlay.sh
│   ├── krisos-sync.service
│   └── krisos-sync.timer
├── tests/
│   ├── boot-check.sh
│   ├── release-check.sh
│   ├── release-state.py
│   ├── run-release-vm.sh
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

## Recovery

Aggiungere temporaneamente `krisos.overlay=off` alla kernel command line. L'hook
salta il mount senza cancellare cache o intent e il sync automatico resta
inibito. SELinux enforcing rimane parte del contratto supportato.
