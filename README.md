> [!WARNING]
> **USE AT YOUR OWN RISK.**
> This tool is provided as-is, without any warranty or guarantee of any kind. The owner of this repository is not responsible for any data loss, save corruption, or other damage resulting from the use of this tool. Always back up your save files before converting.

# Death Stranding Director's Cut Savegame Porter

Convert Death Stranding Director's Cut savegames between **Steam** and **Mac App Store (iCloud)** formats.

## Requirements

- Python 3.10+
- macOS (for iCloud sync and metadata generation)

## Usage

```bash
python3 convert.py <source> <destination> [--dry-run]
```

The tool auto-detects the source format and converts to the other.

### Steam to Mac App Store

```bash
python3 convert.py \
  ~/Downloads/DeathStranding \
  ~/Library/Mobile\ Documents/iCloud~com~505games~deathstranding
```

### Mac App Store to Steam

```bash
python3 convert.py \
  ~/Library/Mobile\ Documents/iCloud~com~505games~deathstranding \
  ~/path/to/steam/saves
```

### Dry run

Preview what would happen without writing anything:

```bash
python3 convert.py --dry-run ~/Downloads/DeathStranding /tmp/output
```

## Save locations

| Version | Path |
|---|---|
| Steam | `~/Library/Application Support/Steam/userdata/<id>/1850570/remote/` |
| Mac App Store | `~/Library/Mobile Documents/iCloud~com~505games~deathstranding/` |

## How it works

The save data is identical between both versions. The only difference is the directory structure:

- **Steam**: `autosave0/checkpoint.dat` (plain files in folders)
- **Mac App Store**: `autosave0.checkpoint.dat.bundle/data` + `metadata` (bundled with a binary plist containing device name and modification date)

The tool:

1. Backs up the destination directory before overwriting
2. Copies save data between formats
3. Generates/strips `.bundle` metadata as needed
4. Removes macOS quarantine flags (for iCloud compatibility)
5. Removes `cloudsave.dat` when writing to iCloud (the game regenerates it on launch)

## After converting

1. Make sure the game is closed
2. Run the converter
3. Wait for iCloud to sync (if converting to Mac App Store)
4. Launch the game — it will regenerate its sync manifest automatically
5. If prompted about cloud vs local saves, choose the one you just wrote

## Tested on

- Savegame transfer from Windows Steam to M1 Pro MacBook, so after iCloud sync I can play on my M4 iPad Pro on vacation.

## Known issues

- **Game does not recognize save games** — quit the game completely and start it again.

---

*Keep on keeping on!*
