# K1.0 locked main payload

The K1 installer consumes one exact signed KrisOS main image. It does not rebuild
the OS and it does not use the mutable `m1` tag.

- KrisOS commit: `6212322d22ccf170562976bef3c288d531f98bb2`
- Immutable ref: `ghcr.io/krism-eu/krisos:6212322d22ccf170562976bef3c288d531f98bb2`
- Manifest digest: `sha256:7f1e12e8fbf3b94acb389045dc920d30d998458ca170453a8493810ffdebecff`
- krisCC in payload: `0.7.0-4.fc44.x86_64`
- Validated Build M1 run: `35496301045`

That main build passed source invariants, exact krisCC verification, bootc image
build, real RK package-layer integration, Cosign signing/verification and
anonymous registry pull verification.

Any runtime change requires a new successful main build and a deliberate update
of `KrisOS-payload.lock` before another ISO is produced.
