# K1.0 Fedora 45 locked payload

The K1 installer consumes one exact signed KrisOS45 payload image. It does not
rebuild the OS and it does not use a mutable channel tag.

- KrisOS45 payload commit: `650786a97209bed438a29d5c4a42c7344ca1842d`
- Immutable ref: `ghcr.io/krism-eu/krisos45:650786a97209bed438a29d5c4a42c7344ca1842d`
- Manifest digest: `sha256:08f98504645b99a5d685b67ebe4d1a6f14ece9dd7799a0daf7315baf57782581`
- Fedora 45 Minimal base digest: `sha256:9d010fe35ac8db7f0bcb8576b530ea443feed2d7c428a40a06c2f0c98aa86437`
- krisCC in payload: `0.7.9-1.fc44.x86_64`
- Validated Build M1 run: `36538748619`

That payload build passed source invariants, exact krisCC verification, bootc
image build, real RK package-layer integration on Fedora 45 / Python 3.15,
Cosign signing/verification and anonymous registry pull verification.

Any runtime change requires a new successful payload build and a deliberate
update of `KrisOS-payload.lock` before another ISO is produced.
