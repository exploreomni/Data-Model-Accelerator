# Training font provenance

Four fonts are bundled solely for deterministic training graphics and PDF builds. They are not installed into the operating system. The original WOFF2 files came from the following Fontsource packages at version 5.3.0; TTFs were decompressed with FontTools 4.63.0 without altering outlines or licensing.

| Bundled TTF | Upstream package and path | Original WOFF2 SHA-256 |
| --- | --- | --- |
| CalSans-Latin-400.ttf | `@fontsource/cal-sans@5.3.0`, `files/cal-sans-latin-400-normal.woff2` | `f42a64c6f1183b77af393b3db49ca5c8c2da0481bb8aeca7ee5e65834e5fc639` |
| IBMPlexSans-Latin-400.ttf | `@fontsource/ibm-plex-sans@5.3.0`, `files/ibm-plex-sans-latin-400-normal.woff2` | `3b646991d30055a93a4ecc499713d4347953a74a947ecab435ab72070cbdab0e` |
| IBMPlexSans-Latin-500.ttf | `@fontsource/ibm-plex-sans@5.3.0`, `files/ibm-plex-sans-latin-500-normal.woff2` | `0717336fb31fcdcde4b8deb3675bb4a0f7f6d484864afcd6751ac29975962203` |
| IBMPlexMono-Latin-500.ttf | `@fontsource/ibm-plex-mono@5.3.0`, `files/ibm-plex-mono-latin-500-normal.woff2` | `01d285447409c8a588692162439a038b8cbd7871309ee20267b0d2d91c6e8e22` |

Retain the unchanged SIL Open Font License files: [Cal Sans](LICENSE-Cal-Sans.txt), [IBM Plex Sans](LICENSE-IBM-Plex.txt), [IBM Plex Mono](LICENSE-IBM-Plex-Mono.txt). The [conversion record](CONVERSION.md) contains the TTF hashes. Fontsource upstream packages: [Cal Sans](https://www.npmjs.com/package/@fontsource/cal-sans/v/5.3.0), [IBM Plex Sans](https://www.npmjs.com/package/@fontsource/ibm-plex-sans/v/5.3.0), [IBM Plex Mono](https://www.npmjs.com/package/@fontsource/ibm-plex-mono/v/5.3.0).
