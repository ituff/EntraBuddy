English | [简体中文](README.zh-CN.md)

<div align="center">

# EntraBuddy

**A local tool for troubleshooting Microsoft Entra ID identity issues on macOS & Windows**

See exactly which Microsoft accounts are signed in on this machine, which apps hold them, and which tenant the device is registered to.

[![Platform](https://img.shields.io/badge/platform-macOS%2011%2B%20%7C%20Windows%2010%2B-lightgrey)](#)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](#)
[![Dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)](#)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

<img src="docs/accounts.png" alt="Account overview" width="880" />

</div>

## The problem it solves

When troubleshooting Entra ID sign-in issues, the time-consuming part is usually not the fix — it's figuring out the current state:

- Office keeps prompting for sign-in even though the user is already signed in — which account is actually in effect?
- Which tenant is this machine registered to? Why isn't Intune pushing policies down?
- After switching companies, are the old tenant identities still lingering locally?
- The user insists they're signed in with the company account, so why does the license show a personal subscription?

Both platforms scatter the answers across the same categories of storage — the OneAuth identity store, Office license caches, Edge profiles, OneDrive account settings, system MDM state — but their locations and formats differ entirely, and most of them have no official viewer.

EntraBuddy consolidates all of it into one readable view, and **only reads local files and the registry. It never touches any credentials.**

## Features

### Account inventory

Distinguishes organizational accounts (OrgId) from personal accounts (MSA), recognizes global vs. 21Vianet (China) clouds, and shows tenant name, tenant ID, object ID, CID, and last-active time.

### App associations

Answers "who is using it, and as whom". Each account is tagged with its role in every app that holds it:

| Role | Meaning |
|------|---------|
| Active sign-in | The identity the app is currently using |
| License | The account that authorizes the app's subscription |
| Sync account | Bound to sync clients such as OneDrive |
| Browser profile | Signed-in state of an Edge profile |
| Identity cache | Present only in local cache, not in use |
| Device policy | Associated with MDM / endpoint protection |

This step often pins the problem down directly: **Office signed in with a work account while the license comes from a personal subscription** is the classic mixed-identity failure.

### Device & compliance self-check

Device identity, Entra ID registration status, MDM enrollment, and legacy AD, plus seven locally verifiable compliance signals —

- macOS: FileVault / SIP / firewall / OS version / endpoint protection, etc.
- Windows: BitLocker / firewall / OS version / Defender onboarding / SmartScreen, etc.

"Non-compliant" and "cannot determine" are strictly distinguished — if a value can't be read, the tool says so instead of guessing. For example, BitLocker status is unreadable without elevation on Windows, so it's reported as "cannot determine: requires administrator", never as a false non-compliance.

### Change tracking

Every scan records a snapshot and diffs it against previous ones, surfacing accounts that appeared, disappeared, or changed — invaluable for "it worked yesterday" incidents.

### Backup-first cleanup

Stale identity caches can be cleaned, but **always backed up first**, and cleanup is **scope-selectable**:

| Scope | Storage touched | Effect |
|-------|-----------------|--------|
| Identity cache | OneAuth blobs (default) | The sign-in cache shared by the Office family and the new OneDrive client; apps require re-login afterwards |
| Office only | License files + Office identity registry records | Deactivates Office and removes its identity records; **OneDrive / Edge untouched** |
| OneDrive only | The OneDrive account registry key | Unbinds the sync account; local folders are kept and sync resumes after re-login |

Edge sign-in state lives inside Chromium profile files where automated cleanup risks corruption, so the UI says so and points to in-app sign-out. Registry keys are fully snapshotted into the backup before deletion and rebuilt as they were on rollback.
: files are copied to the local data directory (macOS `~/Library/Application Support/EntraBuddy/backups`, Windows `%LOCALAPPDATA%\EntraBuddy\backups`) and verified one by one — any failure aborts the whole operation. Single-account and batch cleanup supported, with one-click rollback.

## Quick start

### Browser mode

```bash
# macOS
./run.sh                 # http://127.0.0.1:8765
./run.sh --port 9000
```

```bat
:: Windows
run.cmd
run.cmd --port 9000
```

The backend has zero third-party dependencies — Python standard library only.

### Demo mode

```bash
./run.sh --demo          # or: run.cmd --demo
```

Renders the full UI with fictional accounts; all write operations are disabled.

### Native macOS app (Apple Silicon)

Download from [Releases](https://github.com/ituff/EntraBuddy/releases), or build from source:

```bash
./desktop/build_app.sh   # produces dist/EntraBuddy.app with bundled Python + PyObjC
```

A native window (PyObjC + WKWebView) that starts the local service on a random port and shuts it down on exit.

### Windows desktop mode (optional)

```bat
pip install pywebview
python desktop_win.py    :: pywebview + WebView2 native window
pip install pyinstaller pywebview
desktop\build_app.cmd    :: produces a single-file dist\EntraBuddy.exe
```

## Releasing (automated dual-platform builds)

The repo ships a GitHub Actions workflow (`.github/workflows/release.yml`). Pushing a version tag builds on both a macOS and a Windows runner and attaches both artifacts to the same Release:

```bash
git tag v0.3.0
git push origin v0.3.0
# → EntraBuddy-v0.3.0-macos-arm64.zip (.app)
# → EntraBuddy-v0.3.0-windows-x64.zip (single-file exe)
```

You can also trigger a dry run from the Actions page (workflow_dispatch). Neither artifact can be cross-compiled — the .app bundles a macOS Python runtime and the exe relies on PyInstaller — which is exactly why the CI matrix runs on two runners. The macOS build is ad-hoc signed; proper distribution still requires developer-ID signing and notarization. The Windows exe is unsigned, so SmartScreen may warn on first run.

## How it works

Both platforms scan the same semantic data with entirely different implementations:

| Data | macOS | Windows |
|------|-------|---------|
| OneAuth identity store | `~/Library/Group Containers/UBF8T346G9.com.microsoft.oneauth/BlobStore/` | `%LOCALAPPDATA%\Microsoft\OneAuth\blobs\` (same library, identical structure) |
| Office active identity | `defaults read com.microsoft.office` (OCPS-LastSuccessfulUserId) | Registry `Common\Identity\ConnectedOneAuthAccountId` |
| Office licenses | `~/Library/Group Containers/UBF8T346G9.Office/Licenses/` | `%LOCALAPPDATA%\Microsoft\Office\Licenses\` (same JSON format) |
| Edge | `~/Library/Application Support/Microsoft Edge/` | `%LOCALAPPDATA%\Microsoft\Edge\User Data\` (same Chromium structure) |
| OneDrive | `UBF8T346G9.OneDriveSyncClientSuite.plist` | Registry `HKCU\...\OneDrive\Accounts\<slot>` |
| Device registration | Company Portal container + keychain certificates (heuristic) | `dsregcmd /status` (gives AzureAdJoined directly) |
| MDM | `profiles status` | Registry `HKLM\...\Enrollments` |
| Disk encryption | `fdesetup` (FileVault) | `manage-bde` (BitLocker) |
| Endpoint protection | `mdatp health` | Defender ATP `OrgId` registry value |

### Findings from the cross-platform port

**OneAuth is the same cross-platform library.** The blobs under `%LOCALAPPDATA%\Microsoft\OneAuth\blobs\` on Windows follow the exact same naming and JSON structure as macOS's `BlobStore` (`*_identity_provider`, `*_graph_organization`, `*_hrd`), so the parsing and objectId inference logic is shared.

**objectId inference for OrgId accounts.** For OrgId accounts the OneAuth blob prefix is the user's `objectId`, not the `tenantId`, and there is no UPN → objectId mapping table. Matching is done by normalizing "tenant display name ↔ email domain" (`Fabrikam Inc` ↔ `fabrikam.com`), with timestamps only as a tiebreaker, and a confidence level is reported.

**An MSA's three IDs are the same value.** OneAuth accountId = Edge `gaia_id` / the cid behind `user_name` = OneDrive `cid` (a 16-digit hex string) — they can be cross-verified.

**OneDrive's business `cid` is actually the objectId (Windows).** In the registry, `Accounts\Business1`'s `cid` value is the account's objectId (GUID) inside the tenant; it is mapped to `object_id` rather than `cid` to keep license-CID cross-matching from crossing wires.

**Office license files share the same format across platforms.** Windows license files are likewise UTF-16LE `{"License":"<base64>"}` JSON, so the token decoding logic is shared.

## Security & privacy

- **No credentials are read.** Token caches are encrypted; the tool parses account metadata only and never touches access tokens / refresh tokens
- **No network access.** The service listens on `127.0.0.1` only and makes zero remote requests
- **Write operations are guarded.** A custom request header is required (cross-site requests can't set it); cleanup always backs up and verifies first, and a changed file manifest forces re-confirmation
- **Cleanup scope is restricted.** Operates only inside the OneAuth directory, matches only whitelisted prefixes for that account, and rejects symlinks and path traversal

## Good fit / not a fit

**Good fit**

- Troubleshooting mixed-up Office / Teams / Edge / OneDrive account identities on a machine
- Checking whether a device is registered to Entra ID and managed by MDM
- Cleaning up leftover identity caches after offboarding or tenant switches

**Not a fit**

- Reading or exporting token contents (by design)
- Replacing Intune's compliance verdict (that requires Graph authorization)

## Development

```
app.py                    HTTP service, routes, write guards (shared)
desktop_mac.py            PyObjC + WKWebView desktop shell
desktop_win.py            pywebview + WebView2 desktop shell
entrabuddy/
  _platform.py            platform detection
  scan.py                 orchestration: merge sources, build associations, insights (shared)
  cleanup.py              backup / delete / rollback (shared)
  snapshots.py            snapshots & diff (shared)
  demo.py                 demo data (shared structure, per-platform device block)
  util.py                 paths / defaults / registry / safe reads
  collectors/
    __init__.py           platform dispatch: office/onedrive/environment/device pick *_mac/*_win
    oneauth.py            OneAuth identity store (shared on both platforms)
    edge.py               Edge profiles (shared on both platforms)
    office_mac.py         Office identity (defaults) & licenses (macOS)
    office_win.py         Office identity (registry) & licenses (Windows)
    onedrive_mac.py       OneDrive plist (macOS)
    onedrive_win.py       OneDrive registry (Windows)
    environment_mac.py    installed apps / MDM / Defender (macOS)
    environment_win.py    installed apps / MDM / Defender (Windows)
    device_mac.py         device identity, registration, compliance (macOS)
    device_win.py         dsregcmd, device identity, compliance (Windows)
web/                      GUI (vanilla JS, no build step; copy follows the platform field)
tests/                    isolated cleanup-pipeline tests
desktop/build_app.sh      macOS .app packaging
desktop/build_app.cmd     Windows exe packaging
```

Platform dispatch happens only at the collector layer: adding a new platform means one set of `*_xxx.py` collectors and one line in `collectors/__init__.py` — orchestration and UI need no `if` at all.

```bash
python tests/test_cleanup.py
```

The tests run the full plan → backup → delete → restore pipeline in a temporary directory, covering both single-account and batch paths, platform-independent.

## Roadmap

- [ ] Token details: parse readable JWT claims and show actual expiry times
- [ ] Graph integration: read the real Intune compliance verdict and device objects
- [ ] Export: dump accounts and app associations to CSV / JSON for audit trails
- [ ] Distribution: macOS signing & notarization; Windows icon and installer

## License

[MIT](LICENSE)

---

<div align="center">
<sub>Not affiliated with or endorsed by Microsoft. Microsoft, Entra ID, and Microsoft 365 are trademarks of Microsoft Corporation.</sub>
</div>
