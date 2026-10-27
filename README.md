# CapCut Auto Editor

Windows app (PySide6) that generates **editable CapCut drafts** from a song.

- Automatic beat-matched video sequencing, experimental Pinterest source, transitions, effects and captions.
- Subtitles can be edited and saved to a persistent song library; verified edits are reused for repeat songs.
- Windows EXE/installer built by [GitHub Actions](.github/workflows/windows-release.yml).
- In-app update checks use GitHub Releases and SHA-256 verification.

**Setup:** read [README_RU.md](README_RU.md) (Russian), then import your own CapCut template locally.
No CapCut templates, music, private media, credentials, browser profiles or model weights are stored in this repository.

**Build status:** the Windows installer requires a successful GitHub Actions run; Python unit tests alone do not validate runtime behavior on Windows.

Pinterest automation is experimental and cannot bypass access controls. Obtain permission for footage before redistribution. This app is not affiliated with CapCut or Pinterest.
