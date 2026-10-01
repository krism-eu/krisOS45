# KrisOS45 build cadence

Until Fedora 45 stable, main rebuilds once per day from
quay.io/bootc-devel/fedora-bootc-45-minimal:latest.

Every run resolves latest to the exact digest used for that build.
If the validation and publication gates pass, CI publishes and signs an immutable
candidate digest. The mobile tag `ghcr.io/krism-eu/krisos45:m1` does **not** move
automatically: it advances only through the separate `promote-m1.yml` workflow,
after protected-environment authorization and Cosign verification. The VM harness
is a separate manual validation and is not part of automatic promotion. Installed
systems never update automatically; the user decides when to run
the bootc update.

After Fedora 45 stable, the same refresh becomes weekly.

krisCC is not an automatic trigger for KrisOS builds during its
development phase. It is tested manually until its final version is
deliberately incorporated into KrisOS.
