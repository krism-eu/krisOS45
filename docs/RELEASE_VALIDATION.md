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

## VM harness

Esempio per il gate completo:

```bash
export KRISOS_E2E_TARGET=qa@192.0.2.10
export KRISOS_E2E_SWITCH_IMAGE=ghcr.io/krism-eu/krisos45@sha256:<digest>
export KRISOS_EXPECT_IMAGE="$KRISOS_E2E_SWITCH_IMAGE"
export KRISOS_EXPECT_KRISCC=<version-release.fc45.x86_64>
export KRISOS_EXPECT_ADMIN_USER=qa
tests/run-release-vm.sh
```

La VM deve essere usa-e-getta e l'utente SSH deve avere sudo non interattivo.
Se `KRISOS_E2E_SWITCH_IMAGE` non è impostata, il harness può provare il reboot
sullo stesso deployment ma **non** soddisfa il gate di cambio deployment.

Dopo lo switch il harness esegue `semodule -B`; il successivo release check deve
ancora risolvere correttamente i context di `/var/home`. Questo verifica che il
policy store persistente sotto `/var/lib/selinux` non renda fragile il fix al
cambio immagine. Il harness arma inoltre un `pending` sintetico su VM usa-e-getta,
riavvia e pretende che l'hook scarti l'upper, rimuova `pending`, completi il retry
`needs-sync` e faccia sparire la sentinella precedente.

## Gate `rk`

1. test sorgente/policy;
2. container Fedora con solver reale, firme, install/remove e no-op transaction;
3. qcow2 fresca con `rk plan`, `rk add`, reboot e rpmdb/upper persistenti;
4. cambio deployment, wipe dell'upper e recovery da transazione interrotta.

Solo i gate realmente eseguiti possono essere dichiarati passati. Il container
non prova boot, OverlayFS reale, reboot o recovery.

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

`sync-kriscc.yml` accetta un tag stable `vX.Y.Z` (per esempio `v0.8.0`), valida
il candidato in una build KrisOS45 e apre una PR che modifica il lock. Non pusha
più direttamente su `main`. Il merge deliberato della PR avvia il
normale workflow della branch release.

Il payload Fedora 45 usa soltanto l'artefatto `fc45`; alla stable F45 definitiva
deve adottare un build `fc45` con una trust chain più forte e rimuovere
`--nosignature`.

Gli smoke test krisCC sono volutamente due: la build payload prova l'avvio
foreground, mentre adoption/release-check provano `--background`. `Hidden=true`
nel file autostart significa che l'avvio automatico è disabilitato di default;
non rende invalida la modalità background, che resta un percorso runtime da
verificare esplicitamente.

## Promotion

`promote-m1.yml` serializza le promotion con una concurrency dedicata e usa
l'environment `stable-promotion`. **Prerequisito operativo della release:**
configurare in GitHub Settings almeno un required reviewer per quell'environment;
la dichiarazione YAML da sola non crea una policy di approvazione. La checklist
di promotion deve considerare non configurata questa protezione finché una run
non mostra effettivamente lo stato di attesa/approvazione dell'environment.
