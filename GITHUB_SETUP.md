# GitHub bootstrap — `kazakavtobus/capcut-auto-editor`

The user must create or authorize the new repository. Do not put the personal CapCut template in this repository.

## Upload source

```powershell
# Run inside the unpacked Source_GitHub folder AFTER creating empty repo.
git init
git branch -M main
git add .
git status --short
# Inspect the files in git status: no personal media/template/tokens.
git commit -m "CapCut Auto Editor v7.5: song library, subtitle timeline, updater"
git remote add origin https://github.com/kazakavtobus/capcut-auto-editor.git
git push -u origin main
```

Go to Actions -> Windows EXE + Installer release -> Run workflow. Verify the artifact locally before publishing.

## Tag after Windows test

```powershell
git tag v7.5.0
git push origin v7.5.0
```

After release: update BOTH `version.py` and `installer/capcut.iss`, tag that same commit. Do not re-tag old versions. The app compares versions and checks installer SHA-256. A checksum published from the same compromised repo does not replace signed binary release security.
