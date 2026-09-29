# Fedora 45 port checkpoints

Il port Fedora 45 conserva il contratto OSTree e lo stesso lifecycle
dell'OverlayFS persistente su `/usr`.
Il port non modifica l'identità della cache: resta
`STATEROOT/OSTREE_COMMIT/DEPLOYSERIAL`.

## Adattamenti Fedora 45

Fedora 45 porta configurazioni vendor DNF e chiavi RPM sotto `/usr`. `rk` tratta
quindi come policy/trust non sovrapponibile almeno:

- `/usr/share/dnf5`;
- `/usr/share/pki/rpm-gpg`;
- `/usr/lib/rpm`.

Il modello è stato ulteriormente ristretto per impedire a RPM overlay di creare
effetti persistenti o di boot fuori dalla cache ricostruibile: `sysusers.d`,
`tmpfiles.d`, udev, systemd unit/generator, PAM, polkit, sysctl, NetworkManager,
dracut e kernel policy sono namespace protetti. La validazione legge anche
`%{FILELINKTOS}` e risolve i symlink definiti nello stesso RPM prima di applicare
la transazione.

Python 3.15 ha richiesto l'aggiornamento del caricamento dei moduli nei test; la
logica runtime dell'overlay non è stata riscritta. L'installer F45 è separato
nella branch ISO.

## Base e provenance

Durante Fedora 45 Branched la build segue:

```text
quay.io/bootc-devel/fedora-bootc-45-minimal:latest
```

A ogni run `:latest` viene risolta a un digest preciso. Quel digest rende
immutabile la base usata da quel run, non l'intero dependency closure del build:
il delta KrisOS e lo stage `linux-firmware` vengono ancora risolti dai repository
Fedora firmati disponibili al momento della build. La CI deve quindi pubblicare
`owned-nevra.txt`, la NEVRA sorgente del firmware RTL e un diff contro il
payload `m1` precedente. Questi dati rendono la deriva visibile; non costituiscono
una pretesa di build bit-for-bit riproducibile.

## Stato dei gate

La pipeline container F45 verifica sorgenti, build bootc, reale integrazione
libdnf5/RPM, firma Cosign e pull immutabile. I gate VM restano separati e devono
essere eseguiti prima di dichiarare una release stable: reboot sullo stesso
deployment, cambio deployment con wipe reale dell'upper, recovery di una
transazione interrotta e controllo SELinux dopo `semodule -B`.

Il test VM usa una sentinella sotto `/usr/share/krisos-e2e` e verifica la
corrispondente copia fisica in `/var/lib/krisos/upper`, evitando `/usr/local` e
qualunque possibile redirezione verso `/var`.

## krisCC temporaneo

Il payload congela `krisCC 0.7.10-1.fc45.x86_64`, bloccato dal
lock SHA-256. Fedora 45/RPM 6 richiede la verifica firma per default e il vecchio
artefatto non è firmato, quindi il Containerfile mantiene una singola eccezione
`--nosignature` limitata a quel file dopo il controllo del lock.

Questa è una compatibilità temporanea limitata alla firma dell'asset custom:
il componente è già un RPM Fedora 45. Quando krisCC verrà dichiarato definitivo,
l'RPM dovrà avere firma nativa e/o provenance verificabile così da poter rimuovere
`--nosignature`. La policy DNF/`rk` continua nel frattempo a richiedere firme.
