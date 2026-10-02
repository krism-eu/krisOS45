# M1 notes — contratto del package layer

**Stato:** implementato; i controlli su host installato restano manuali e non bloccano `promote-m1.yml`.

M1 aggiunge `rk` sopra DNF5. `packages.list` contiene solo le richieste
esplicite e l'overlay `/usr` è cache ricostruibile.

## Ownership e architettura

`/usr/share/krisos/owned-packages.txt` e `owned-nevra.txt` descrivono l'immagine
finale. Le transazioni overlay non possono toccare pacchetti owned. KrisOS è
single-arch: `x86_64`/`noarch`, niente i686 o multilib.

Durante Fedora 45 Branched la build segue la Minimal `:latest`, risolta ogni volta a un digest esatto. Il delta RPM di build è risolto dai repository
Fedora firmati live: la CI conserva la NEVRA esatta per rendere visibile la
deriva fra build.

## Metadata e timer

`dnf-makecache.timer` e `dnf5-makecache.timer` sono mascherati: non esiste un
refresh metadata periodico. `krisos-sync.timer` è diverso: è un retry
condizionato della ricostruzione e resta inerte quando `needs-sync` non esiste.

## Transazioni

`rk add/rm/sync` usano libdnf5/RPM reali. Nessun package item dopo il solver
significa no-op: niente `pending`, niente `tx.run()`, ma l'intent può essere
sincronizzato. Le dipendenze restano responsabilità di DNF.

Dopo un cambio deployment, una recovery `pending` oppure il rilevamento di
upper/work mancanti sullo stesso deployment, M0/M1 ricrea upper/work, rende
durevole `needs-sync`
prima di poter registrare la nuova identità e `rk sync` reinstalla le richieste
contro la nuova base.

## Stato fuori da `/usr`

Limitarsi a controllare il prefisso `/usr` non è sufficiente: `sysusers.d`,
`tmpfiles.d`, udev, systemd, PAM, polkit e altri namespace possono modificare o
condizionare `/etc`, `/var` o il boot. Sono quindi protetti insieme ai namespace
Fedora 45 di repo/trust e alla rpmdb. Anche i symlink interni all'RPM vengono
risolti dal manifest prima della transazione.

I trigger di pacchetti Fedora già installati possono ancora avere effetti
collaterali; i controlli manuali su host installato restano utili per osservarli,
ma non fanno parte del gate automatico di promotion.

## Aggiornamenti overlay

Non esiste un timer di upgrade degli RPM installati da `rk`. Le richieste vengono
risolte di nuovo quando un nuovo deployment invalida l'upper. Questa è una
scelta intenzionale della linea M1 e deve essere mostrata chiaramente nella UI.
