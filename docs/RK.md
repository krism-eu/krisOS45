# rk: persistent RPM policy layer

`rk` è l'interfaccia RPM ristretta di KrisOS per pacchetti additivi sul
persistent `/usr` overlay.

```bash
rk status
rk status --json
rk plan tree
sudo rk add tree
sudo rk rm tree
sudo rk sync
```

`packages.list` contiene solo le richieste esplicite. La rpmdb e lo state
libdnf5 restano quelli del sistema sotto `/usr`; non esistono una seconda rpmdb
o un dependency graph proprietario.

## Policy di transazione

Sono accettati solo nomi pacchetto esatti da repository già abilitati,
`x86_64`/`noarch`. `rk` rifiuta modifiche ai pacchetti owned dall'immagine,
replacement, upgrade/downgrade della base, rimozioni indirette, RPM locali, URL
e opzioni DNF da riga di comando. Le firme RPM e `tx.test()` sono obbligatorie.

Le transazioni vuote vengono cortocircuitate dopo il solver: l'intent può essere
aggiornato, ma non viene creato `pending` e non viene chiamato `tx.run()` su una
transaction priva di package items.

## Payload consentito

Un RPM entrante deve avere payload canonico sotto `/usr`, non può sovrascrivere
file già esistenti e non può avere scriptlet, trigger o file trigger propri.
`validate_payload()` legge anche `%{FILELINKTOS}` e `%{FILECAPS}`: un symlink
creato dallo stesso RPM viene risolto insieme ai suoi discendenti prima
dell'installazione. Un symlink che esce da `/usr` o raggiunge un namespace
protetto rende il pacchetto non supportato. Sono inoltre rifiutati file speciali
(device/FIFO/socket), bit setuid/setgid e file capabilities: il layer è destinato
a payload applicativi non privilegiati. La query del manifest viene letta in
forma raw, senza applicare `.strip()` all'output RPM, così i campi finali vuoti
`FILELINKTOS`/`FILECAPS` dell'ultima entry restano distinguibili.

In particolare, un RPM che installa unit systemd (system o user), preset,
configurazione systemd-networkd, generator o override globali `*.conf.d` **non è
supportato** dal layer overlay. Questi componenti appartengono alla policy di
sistema e devono entrare nell'immagine bootc immutabile, non tramite `rk`.

Namespace protetti includono policy/trust Fedora e percorsi che possono produrre
effetti persistenti o di boot fuori dall'upper, tra cui:

```text
/usr/share/dnf5
/usr/share/pki/rpm-gpg
/usr/lib/rpm
/usr/lib/sysimage
/usr/lib/ostree
/usr/lib/modules
/usr/share/krisos
/usr/lib/sysusers.d
/usr/lib/tmpfiles.d
/usr/lib/udev
/usr/lib/systemd              # units, presets, networkd, global *.conf.d, generators
/usr/lib/firewalld
/usr/lib/selinux
/usr/share/selinux
/usr/lib/pam.d
/usr/lib/security
/usr/lib64/security
/usr/share/polkit-1
/usr/lib/polkit-1
/usr/lib/sysctl.d
/usr/lib/modules-load.d
/usr/lib/modprobe.d
/usr/lib/NetworkManager
/usr/lib/dracut
/usr/lib/kernel
```

I trigger appartenenti a pacchetti Fedora già installati possono comunque
reagire a una transazione RPM; per questo il modello non promette compatibilità
con RPM desktop arbitrari e i gate VM restano necessari.

## Recovery

`pending` viene scritto solo immediatamente prima di una vera transazione RPM.
Se il processo viene interrotto, al reboot l'hook elimina upper/work, rende
persistente `needs-sync`, elimina `pending` e ricostruisce le richieste salvate.
Il package intent viene aggiornato atomicamente soltanto dopo successo.

Dopo un cambio deployment, `krisos-sync.service` parte soltanto se esistono sia
`/var/lib/krisos/needs-sync` sia `/run/krisos/overlay-mounted`. Il relativo
`krisos-sync.timer` è un **retry timer condizionato**: dopo il boot e poi ogni 10
minuti può ritentare una recovery ancora pendente. Non è un timer di refresh dei
metadata DNF e non avvia lavoro quando `needs-sync` non esiste.

## Aggiornamenti degli RPM overlay

Non esiste un `rk upgrade` automatico. Un pacchetto richiesto può quindi restare
alla stessa NEVRA finché l'upper corrente rimane valido. Il ciclo supportato per
rivalutare le richieste contro i repository correnti è la ricostruzione
successiva a un cambio deployment. Questo compromesso deve essere visibile nella
UI: gli RPM overlay non hanno una cadenza di security update indipendente dalla
release immutabile KrisOS.

## Status API

`rk status --json` emette `schema: 1` con stato overlay, mount, errore,
`pending_recovery`, `needs_sync` e richieste. I consumer devono usare questo JSON
versionato, non analizzare il testo human-readable.

## Gate di validazione

1. source policy tests;
2. disposable Fedora container con libdnf5/RPM reali, incluse install/remove e
   transazione no-op;
3. qcow2 fresca con reboot e persistenza reale dell'upper/rpmdb;
4. cambio deployment con wipe dell'upper e recovery di transazione interrotta.

Solo i gate effettivamente eseguiti possono essere riportati come passati.
