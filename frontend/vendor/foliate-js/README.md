# foliate-js (vendored subset)

The in-browser reader renders books with [foliate-js](https://github.com/johnfactotum/foliate-js)
by John Factotum, MIT licensed (see `LICENSE`). These files are byte-for-byte copies
from the maintained fork at
[readest/foliate-js](https://github.com/readest/foliate-js), commit
`6d74298546a59a5d64e531ccee1ba0809d967bf4` (2026-10-18). GitHub's source
tarball for that commit had SHA-256
`3e81917bfb6e8ec24ebc80115c5b8c7fcca149085e66627e79b0734fe9c76630`.
Nothing here comes from the Readest application, and the npm package named
`foliate-js` is unrelated and not used.

| File | SHA-256 |
|---|---|
| `LICENSE` | `b621ffc351fe263bc9b09dd0bc1c9332fda9c462a3904c1e4f0b4d3236b9c28c` |
| `epub.js` | `5326553896410cc2f4d1dd21c7a824058afd2bf986fee8e584fd81339eadcb54` |
| `epubcfi.js` | `89c0610cb6d3b482dde1552da2bc02e37ec804bc7b1916a1a86299e3c979d221` |
| `overlayer.js` | `f0ef045950656ff6c0fefe01249d83215c58ba149bde528e26a6db531c349268` |
| `paginator.js` | `edbdfc66f771ab14869e7a864f32c5aa374256e6eab9e7ca5dfc47e87e876a8c` |
| `progress.js` | `e9a6ba8b0b45802677de2ac7c6722299ab1d45df2cb780ea623ab2dc6d7cfd15` |
| `search.js` | `e69ca1a6ac0f89964fbb2c4e96613d2b2174ee84b0a850e968134d70e53fbce0` |
| `section-chunks.js` | `0d84803c201ce5b7d29f158f3bd7715291a01c697247aecd9fa6dde45e779f46` |
| `text-walker.js` | `a9ba231c192ee214ef664b2e01f712d199700bcf2be1c20a38c1b26024428aff` |
| `view.js` | `c9ee7ce3a5e7bb6b3e52a29d5bec7ac2bd14bd117c935f9343edb53cdd4855f1` |

Only the EPUB path is copied. The engine's own zip reader, PDF.js, MOBI, FB2,
comic, fixed-layout and speech modules are absent; `reader-page.ts` resolves the
engine's references to them to a module that refuses to load, so the build cannot
include them. `src/reader/book.ts` supplies the archive through fflate and cleans
every document before the engine turns it into a frame.

To update: download a newer pinned commit, replace these files unchanged, record
the commit, tarball hash and file hashes here, and rerun the reader's hostile-book
tests and the headless browser check.
