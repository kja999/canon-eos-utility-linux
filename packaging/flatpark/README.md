# FlatPark packaging

Draft package for listing Canon EOS Utility on [FlatPark](https://flatpark.org),
the community Flatpak hub that repackages a vendor's *prebuilt* download as
`extra-data` (it never builds from source).

## How it works

FlatPark fetches the tarball we publish on our GitHub releases, unpacks it at
install time and runs it. The tarball is a **self-contained PyInstaller bundle**
(built by `../build_tarball.sh`) carrying its own Python + PySide6/Qt, so it
needs nothing from the runtime but the display/GL/fontconfig stacks that
`org.freedesktop.Platform` provides.

```
registry/org.problem_child.CanonEOSUtility/
  flatpark.yml                        # descriptor
  org.problem_child.CanonEOSUtility.yml      # Flatpak manifest (extra-data)
  org.problem_child.CanonEOSUtility.metainfo.xml
  org.problem_child.CanonEOSUtility.desktop
  org.problem_child.CanonEOSUtility.png      # 512x512
  apply_extra.sh                      # unpacks the tarball
  canon-eos-utility-wrapper           # execs the unpacked binary
  resolve-update.sh                   # resolves the latest release
```

## Submitting (one-time)

Onboarding is meant to run through an AI agent, so it can be driven end to end.
The steps, per FlatPark's publishing guide:

1. **Fork** [`flatpark/flatpark`](https://github.com/flatpark/flatpark) and copy
   this directory to `registry/org.problem_child.CanonEOSUtility/`.
2. **Pin** the current release: run `resolve-update.sh`, then put its `url` into
   the `# BEGIN/END MANAGED EXTRA-DATA` block and fill in the real `sha256`/`size`
   (FlatPark's tooling does this automatically once a release exists).
3. **Validate and test-build** with FlatPark's tooling:
   ```sh
   flatpak install flathub org.flatpak.Builder
   node scripts/read-descriptor.mjs registry/org.problem_child.CanonEOSUtility/flatpark.yml
   ./scripts/publish.sh --verify org.problem_child.CanonEOSUtility
   ```
4. **Actually install and run it** (isolated installation or a throwaway remote),
   connect to a camera, and record in the PR body what you exercised. A `--verify`
   pass alone is not "tested" by FlatPark's bar.
5. **Open the PR.** `pr-checks` validates the descriptor and builds the app; on
   merge it is published to the `flatpark` remote.

## Updates

`resolve-update.sh` reads the latest GitHub release. To have FlatPark pick up new
releases the moment they are published (rather than its daily poll), add
[`flatpark/publish-action`](https://github.com/flatpark/publish-action) to the
release workflow:

```yaml
- uses: flatpark/publish-action@v1
  with:
    app-id: org.problem_child.CanonEOSUtility
```

## Notes

- Only `org.freedesktop.Platform`'s current major is used, matching the catalog.
- Permissions stay tight: network (PTP/IP + mDNS), the standard media folders,
  and a persisted config dir. No optional capability is granted by default.
- The metainfo and desktop file are copies of the ones in `../`; keep them in
  sync (the release workflows read the metainfo's latest `<release>` as the
  version anchor).
