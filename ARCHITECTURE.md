# KrisOS — Architettura e invarianti

`KrisOS` è un desktop Fedora bootc minimale con SELinux enforcing e un
OverlayFS persistente su `/usr`.

Ogni build risolve la Fedora 45 Minimal corrente a un digest OCI esatto; l'`upper` è cache
ricostruibile, non una seconda base del sistema. Il progetto mantiene codice,
RPM, repository e formati di stato propri.

## Ambito M0

M0 valida una sola cosa: il lifecycle del nostro overlay `/usr`.

- Fedora 45 bootc Minimal con contratto di deployment OSTree (`ostree=`).
- Fedora può presentare la root immutabile tramite composefs/OverlayFS; quel
  mount resta proprietà di bootc/OSTree.
- KrisOS monta un OverlayFS persistente dedicato soltanto su `/usr`.
- Il mount avviene in early real-root userspace: dopo `ostree-remount.service`
  e prima di `local-fs.target`.
- Stesso deployment con cache integra: `upper/` viene conservato.
- Deployment diverso, cache mancante/non valida o recovery `pending`: `upper/` e
  `work/` vengono ricreati vuoti e viene armato `needs-sync`.
- Se setup o mount falliscono, il servizio termina con successo e il boot
  continua sulla `/usr` immutabile.
- M0 descrive il solo lifecycle dell’overlay; nell’immagine M1 attuale il ripristino RPM è gestito separatamente da `rk` e `krisos-sync`.
- Nessun codice custom dell'overlay nell'initramfs; l'initramfs include solo il piccolo modulo `krisos-nss` necessario a garantire la risoluzione account nel boot Fedora.

Questa collocazione è intenzionale. In initrd il deployment composefs esponeva
una root preparata con semantiche diverse dalla normale real root; dopo
switch-root `/var` è persistente e scrivibile, SELinux è pienamente operativo e
possiamo montare `/usr` prima dei normali servizi senza duplicare il lavoro di
bootc.

## Stato persistente

Lo stato specifico del progetto vive in `/var/lib/krisos/`:

```text
/var/lib/krisos/
├── packages.list   # M1: richieste RPM esplicite dell'utente
├── deployment      # identità OSTree per cui upper/ è valido
├── pending         # M1: rebuild richiesto o transazione RPM interrotta
├── needs-sync      # M1: marker per ricostruire i pacchetti richiesti
├── lock            # lock transazionale rk
├── upper/          # cache OverlayFS ricostruibile
└── work/
```

`packages.list` sarà la fonte di verità per ricostruire il payload RPM
nell'overlay `/usr`, non l'intero stato della macchina. `/etc` e `/var` restano
stato host secondo le normali semantiche bootc.

## Identità del deployment

OSTree passa normalmente una riga kernel del tipo:

```text
ostree=/ostree/boot.BOOTVERSION/OSNAME/BOOTCSUM/TREEBOOTSERIAL
```

`BOOTCSUM` identifica gli artefatti di boot (kernel/initramfs/device tree), non
l'intero filesystem immutabile. Due immagini con lo stesso kernel e initramfs
possono quindi avere lo stesso `BOOTCSUM` pur contenendo `/usr` differenti: non
è sufficiente per decidere se una cache OverlayFS è ancora valida.

In real-root userspace il pathname indicato da `ostree=` è un bootlink OSTree.
KrisOS legge quel symlink e usa il basename del target, nel formato:

```text
COMMIT.DEPLOYSERIAL
```

Il `COMMIT` è il checksum del commit OSTree che rappresenta l'intero tree del
deployment. M0 persiste quindi:

```text
OSNAME/COMMIT/DEPLOYSERIAL
```

`boot.0` / `boot.1`, `BOOTCSUM` e `TREEBOOTSERIAL` servono a localizzare e
validare il bootlink ma non fanno parte dell'identità persistita. Lo stateroot
viene ricavato dalla cmdline e validato; commit e deploy serial vengono ricavati
dal target del bootlink. In questo modo qualsiasi cambiamento dell'immagine
immutabile, anche soltanto sotto `/usr` e senza cambio kernel, invalida la cache.

## Cambio deployment e first boot

Un'identità assente o diversa, una recovery `pending`, oppure `upper/`/`work/`
mancanti o non-directory producono la stessa ricostruzione della cache:

1. crea `needs-sync` e rende durevole l’intento di recovery con `sync -f /var/lib/krisos`;
2. elimina completamente `upper/` e `work/`;
3. se il wipe o la ricreazione falliscono, non monta l’overlay e continua sulla base lasciando `needs-sync` persistente;
4. ricrea `upper/` e `work/`, elimina l’eventuale marker `pending` e rende durevole lo stato ricostruito;
5. copia sulla radice di `upper/` il contesto SELinux della `/usr` immutabile;
6. monta l’overlay persistente su `/usr`;
7. pubblica il marker runtime e registra la nuova identità solo dopo un mount riuscito.

`needs-sync` viene armato anche al first boot. In M0 il factory `packages.list`
è vuoto e il marker è innocuo; in M1 segnalerà che le richieste esplicite vanno
ricostruite sulla nuova base.

## Invarianti

1. **Boot, rete e login appartengono alla base immutabile.** Nessun pacchetto
   overlay è requisito per raggiungere il desktop.
2. **Fail open verso la base.** Un errore del nostro servizio non deve impedire
   il boot.
3. **Mai riutilizzare cache di provenienza incerta.** Identità assente o diversa,
   cache mancante/non valida o recovery `pending` implicano upper vuoto prima del
   mount e `needs-sync` armato.
4. **Upper e work sono disposable.** La recovery consiste nel ricrearli e, da
   M1, reinstallare le richieste esplicite.
5. **Additive-only è una policy tecnica.** Un pacchetto overlay non deve
   sostituire, aggiornare, fare downgrade o rimuovere pacchetti dell'immagine.
6. **SELinux resta enforcing.** Non viene eseguito alcun `restorecon -R`
   sull'upper. Prima del mount `chcon --reference=/usr` etichetta soltanto la
   directory radice `upper/`; i payload vengono creati tramite i pathname
   logici di `/usr`.
7. **Single-arch.** KrisOS usa soltanto `x86_64` e `noarch`; i686/multilib
   sono esclusi dalla policy DNF e non devono comparire nell'immagine.
8. **Niente refresh DNF periodico.** I timer makecache sono mascherati; il
   refresh metadata è esplicito e legato alle operazioni package che lo
   richiedono.
9. **Nessuna dipendenza runtime o build-time da componenti esterni al progetto,**
   oltre alla base Fedora e ai normali pacchetti Fedora dichiarati.
10. **Repo, trust e policy di boot restano proprietà della base.** Gli RPM
    installati tramite `rk` non possono scrivere nei namespace vendor che
    controllano DNF/RPM, systemd, sysusers/tmpfiles, udev, firewall, SELinux,
    PAM/polkit, sysctl, NetworkManager, dracut/kernel o stato KrisOS. La
    validazione del manifest rifiuta inoltre symlink che eludono questi confini,
    file speciali, setuid/setgid e file capabilities.

## M1

M1 aggiunge il comando `rk` sopra DNF5 senza introdurre una seconda rpmdb o un
dependency graph proprietario. `/usr/share/krisos/owned-packages.txt`
protegge l'intera immagine immutabile (base Fedora + delta KrisOS); `packages.list`
contiene soltanto richieste esplicite dell'utente.

La policy già congelata per M1 è:

- solo `x86_64`/`noarch`, niente i686 o multilib;
- nessun refresh metadata periodico in background;
- niente update/downgrade/remove/replace di pacchetti owned;
- dopo cambio deployment o perdita della cache, reinstallazione delle sole
  richieste esplicite;
- nessun upgrade periodico autonomo dei pacchetti overlay sullo stesso
  deployment; `krisos-sync.timer` ritenta soltanto recovery con `needs-sync`;
- `rk rm` usa una vera transazione DNF/RPM, senza pseudo-autoremove;
- `rk refresh` può armare manualmente un rebuild al reboot soltanto dopo un
  controllo read-only delle richieste contro i repository correnti.

Il wrapper implementa la protezione transazionale additive-only e rifiuta
payload con effetti non supportati fuori da `/usr`; la policy resta
intenzionalmente conservativa invece di promettere compatibilità RPM generica.
I symlink dichiarati dagli RPM vengono validati sull'intero insieme della
transazione; un symlink incoming non può essere annidato sotto un altro
symlink incoming, perché la posizione fisica del figlio e la semantica dei
target relativi dipenderebbero dall'ordine di estrazione. Un symlink già
presente può essere ri-dichiarato soltanto se è root-owned e il target testuale
è identico, dopo che la destinazione è comunque risultata confinata a `/usr` e
fuori dai namespace protetti.
Le directory preesistenti devono mantenere ownership e mode identici alla base;
l'unica eccezione per una directory esistente che sia un symlink è l'alias
UsrMerge Fedora `/usr/sbin -> /usr/bin`, verificato esplicitamente e senza
allentare la policy per altri symlink.

## Milestone

- **M0**: overlay early-userspace; reboot; invalidazione al cambio deployment;
  fallback degradato.
- **M1**: wrapper `rk`, policy additive-only, sync post-deployment.
- **M2**: cleanup/polish e test automatici solo dove danno valore reale.

## Alternative registrate e non scelte

- **Overlay custom in initrd**: abbandonato; interagiva male con il deployment
  composefs preparato prima dello switch-root senza offrire vantaggi rispetto
  al mount early-userspace.
- **systemd-sysext**: ottimo per estensioni strettamente additive, ma troppo
  restrittivo per RPM generici con scriptlet/configurazione.
- **split rpmdb custom**: esclusa; ricreerebbe la parte più complessa di un
  package manager.
- **Rust per il mount M0**: escluso; lo shell hook usa primitive filesystem
  semplici e mantiene piccola la superficie di manutenzione.
