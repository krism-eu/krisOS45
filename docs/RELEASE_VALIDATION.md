# KrisOS45 release validation

La sorgente runtime è `main`. La ISO è un percorso secondario di
installazione/recovery e deve incorporare esattamente un payload immutabile già
costruito e firmato da quella branch.

## Controllo runtime

`tests/release-check.sh` riusa `tests/boot-check.sh` e verifica, tra le altre
cose, SELinux enforcing, hardening sysctl effettivo, immagine bootc attesa,
krisCC, initramfs/microcode, stato `rk`, timer di retry, `/var/home` e identità
del deployment.

L'identità non viene certificata da un solo algoritmo. `boot-check.sh` confronta:

```text
bootlink indicato da ostree=
        ==
status.booted.ostree di bootc status --format json --format-version 1
        ==
/var/lib/krisos/deployment
```

`release-state.py` deve essere distribuito insieme agli shell check.

## Persistenza e invalidazione dell'upper

La sentinella E2E vive in `/usr/share/krisos-e2e`, non in `/usr/local`. In fase
di preparazione il test pretende che lo stesso file esista fisicamente sotto
`/var/lib/krisos/upper/share/krisos-e2e`.

Sul reboot dello stesso deployment entrambe le viste devono sopravvivere. Prima
di un `bootc switch` viene creata una sentinella analoga; dopo il reboot su un
commit differente la sentinella deve essere assente sia dal merged `/usr` sia
dal nuovo upper. In questo modo il test certifica direttamente il contratto
principale di invalidazione M0/M1.

## Validazione host manuale

`tests/boot-check.sh` e `tests/release-check.sh` restano disponibili per controlli
manuali su un sistema installato. `promote-m1.yml` non li esegue e non dipende da
secret o connettività SSH verso una VM.

Il modo `check` verifica lo stato corrente. I modi `prepare-reboot`,
`verify-reboot`, `prepare-switch`, `verify-switch`, `prepare-recovery` e
`verify-recovery` mantengono le sentinelle e gli assert necessari per un drill
manuale quando si vuole certificare reboot, cambio deployment o recovery reale.
L'operatore coordina esplicitamente reboot/switch; non esiste più un orchestratore
VM nel repository.

## Gate `rk`

1. test sorgente/policy;
2. container Fedora con solver reale, firme, install/remove e no-op transaction;
3. controlli manuali opzionali su host installato per reboot/persistenza;
4. drill manuale opzionale di cambio deployment e recovery.

Solo i gate realmente eseguiti possono essere dichiarati passati. Il container
non prova boot, OverlayFS reale, reboot o recovery; i controlli host restano
separati e non bloccano `promote-m1.yml`.

## Provenance del build

La base bootc Branched segue `:latest` ma viene risolta a digest per ogni build, mentre i pacchetti delta sono risolti dai
repo Fedora live. Ogni run conserva quindi:

- `fedora45-base.txt`;
- `owned-nevra.txt`;
- `firmware-source-nevra.txt`;
- `previous-owned-nevra.txt` quando il tag `m1` precedente è disponibile e leggibile;
- `package-drift.txt`;

Il confronto prova prima accesso GHCR autenticato con il `GITHUB_TOKEN` della
build (utile anche con package privati) e ripiega su accesso anonimo. L'assenza
di un baseline `m1` resta non bloccante e viene annotata nel report.
- digest/firma/log del payload pubblicato.

Il diff NEVRA è diagnostica e non blocca automaticamente un aggiornamento: la
review deve stabilire se la deriva è attesa.

## Adozione krisCC

`sync-kriscc.yml` accetta un tag release stabile pubblicata `vX.Y.Z` (per esempio `v0.8.2`), valida
il candidato in una build KrisOS45 e apre una PR che modifica il lock. Non pusha
più direttamente su `main`. Il merge deliberato della PR avvia il
normale workflow della branch release.

Se la policy GitHub vieta ad Actions di creare PR, la validazione conserva la
branch pronta e mostra nel riepilogo il link per aprire manualmente la PR.
Questo caso produce un avviso esplicito, non un falso errore di build; ogni
altro errore nell'apertura della PR resta bloccante. Per automatizzare anche
l'apertura, abilitare nelle impostazioni Actions del repository
`Allow GitHub Actions to create and approve pull requests`.

Il payload Fedora 45 usa soltanto l'artefatto `fc45`; alla stable F45 definitiva
deve adottare un build `fc45` con una trust chain più forte e rimuovere
`--nosignature`.

La build payload verifica integrità RPM (`rpm -V`), binario, desktop file e
metadati installati; non avvia krisCC durante il `Containerfile`. Lo smoke runtime
viene eseguito nei gate adoption/release-check con `--background` e backend Qt
offscreen. `Hidden=true` nel file autostart significa che l'avvio automatico è
disabilitato di default; non rende invalida la modalità background, che resta un
percorso runtime da verificare esplicitamente.

## Promotion

`promote-m1.yml` serializza le promotion con una concurrency dedicata e usa
l'environment `stable-promotion`. La promotion verifica il digest firmato e la
workflow identity Cosign, quindi copia esattamente quel digest sul tag `m1`.
**Prerequisito operativo della release:** configurare in
GitHub Settings almeno un required reviewer per quell'environment; la
dichiarazione YAML da sola non crea una policy di approvazione. La checklist di
promotion deve considerare non configurata questa protezione finché una run non
mostra effettivamente lo stato di attesa/approvazione dell'environment.
