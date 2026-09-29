# KrisOS — branch installer K1

Questa branch contiene **solo** il percorso di installazione ISO di KrisOS.

Il sistema operativo installato non viene costruito qui. La sorgente di verità è
`k1.0-final-payload`, che pubblica l'immagine bootc Fedora 45 firmata. L'ISO accetta esclusivamente il
payload immutabile indicato in `build_files/KrisOS-payload.lock`, ne verifica
digest, firma Cosign, commit OCI e versione krisCC prima di incorporarlo.

Ruoli:

- `k1.0-final-payload`: runtime KrisOS45, `rk`, overlay, pacchetti, krisCC e immagine bootc;
- `k1.0-final-iso`: runtime Anaconda/ISO e contratto di installazione;
- nessun sorgente runtime viene duplicato su questa branch.

La build supportata è `.github/workflows/build-k1-final-iso.yml`. Storage e
creazione utente restano interattivi. Dettagli in `installer/README.md`.
