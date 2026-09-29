# KrisOS45 build cadence

Until Fedora 45 stable, main rebuilds once per day from
quay.io/bootc-devel/fedora-bootc-45-minimal:latest.

Every run resolves latest to the exact digest used for that build.
If all gates pass, ghcr.io/krism-eu/krisos45:m1 advances to that
green image. Installed systems never update automatically; the user
decides when to run the bootc update.

After Fedora 45 stable, the same refresh becomes weekly.

krisCC is not an automatic trigger for KrisOS builds during its
development phase. It is tested manually until its final version is
deliberately incorporated into KrisOS.
