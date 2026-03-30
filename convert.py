#!/usr/bin/env python3
"""Convert Death Stranding Director's Cut savegames between Steam and Mac App Store (iCloud) formats."""

import argparse
import plistlib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Constants ---

SAVE_TYPES = ("autosave", "manualsave", "quicksave")
PROFILE_FILES = ("bindings.cfg", "game_settings.cfg", "profile.dat")
DOTNET_EPOCH_DIFF = 621355968000000000  # .NET ticks offset from Unix epoch
TICKS_PER_SECOND = 10_000_000

STEAM_AUTOCLOUD_VDF = '"steam_autocloud.vdf"\n{\n\t"accountid"\t\t"0"\n}\n'

# --- Format Detection ---


def detect_format(path: Path) -> str:
    """Detect whether a save directory is Steam or iCloud format."""
    if not path.is_dir():
        sys.exit(f"Error: '{path}' is not a directory.")

    for entry in path.iterdir():
        if entry.is_dir() and entry.suffix == ".bundle":
            return "icloud"
        if entry.is_dir() and re.match(r"(autosave|manualsave|quicksave)\d+$", entry.name):
            if (entry / "checkpoint.dat").exists():
                return "steam"
    if (path / "steam_autocloud.vdf").exists():
        return "steam"

    sys.exit(f"Error: Cannot detect save format in '{path}'.")


# --- Discovery ---


def enumerate_steam_saves(path: Path) -> list[tuple[str, Path]]:
    """Return (relative_path, absolute_path) for all save files in a Steam directory."""
    saves = []
    for entry in sorted(path.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name == "profile":
            for f in sorted(entry.iterdir()):
                if not f.name.startswith("."):
                    saves.append((f"profile/{f.name}", f))
        else:
            checkpoint = entry / "checkpoint.dat"
            if checkpoint.exists():
                saves.append((f"{entry.name}/checkpoint.dat", checkpoint))
    return saves


def enumerate_icloud_bundles(path: Path) -> list[tuple[str, Path]]:
    """Return (bundle_stem, absolute_bundle_path) for all .bundle dirs in an iCloud directory."""
    bundles = []
    for entry in sorted(path.iterdir()):
        if entry.is_dir() and entry.name.endswith(".bundle"):
            data_file = entry / "data"
            if data_file.exists():
                stem = entry.name.removesuffix(".bundle")
                bundles.append((stem, entry))
    return bundles


# --- Path Mapping ---


def steam_relpath_to_bundle_stem(relpath: str) -> str:
    """Convert 'autosave0/checkpoint.dat' -> 'autosave0.checkpoint.dat'."""
    return relpath.replace("/", ".")


def bundle_stem_to_steam_relpath(stem: str) -> str:
    """Convert 'autosave0.checkpoint.dat' -> 'autosave0/checkpoint.dat'."""
    # Profile files: 'profile.bindings.cfg' -> 'profile/bindings.cfg'
    if stem.startswith("profile."):
        rest = stem.removeprefix("profile.")
        return f"profile/{rest}"
    # Save files: 'autosave0.checkpoint.dat' -> 'autosave0/checkpoint.dat'
    m = re.match(r"((?:autosave|manualsave|quicksave)\d+)\.(.*)", stem)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    # Fallback: split on first dot
    parts = stem.split(".", 1)
    return "/".join(parts)


# --- Metadata ---


def get_device_name() -> str:
    """Get the Mac model identifier."""
    if sys.platform != "darwin":
        return "Unknown"
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.model"], capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "Unknown"


def parse_modification_time_from_header(data: bytes) -> datetime | None:
    """Extract ModificationTime from [Slot] header (.NET ticks) and convert to datetime."""
    # Look for ModificationTime field in the text header
    header_end = data.find(b"\x00", 0x18)  # Header is null-terminated after initial fields
    if header_end == -1:
        header_end = min(len(data), 4096)
    header = data[:header_end]
    m = re.search(rb"ModificationTime\s+=\s+(\d+)", header)
    if m:
        ticks = int(m.group(1))
        unix_ts = (ticks - DOTNET_EPOCH_DIFF) / TICKS_PER_SECOND
        return datetime.fromtimestamp(unix_ts, tz=timezone.utc)
    return None


def get_modification_time(filepath: Path) -> datetime:
    """Get modification time from save header or filesystem."""
    data = filepath.read_bytes()
    dt = parse_modification_time_from_header(data)
    if dt:
        return dt
    return datetime.fromtimestamp(filepath.stat().st_mtime, tz=timezone.utc)


def create_metadata_plist(device_name: str, mod_date: datetime) -> bytes:
    """Create a binary plist with deviceName and modificationDate."""
    # plistlib requires naive datetime for binary plist
    naive_date = mod_date.replace(tzinfo=None) if mod_date.tzinfo else mod_date
    metadata = {
        "deviceName": device_name,
        "modificationDate": naive_date,
    }
    return plistlib.dumps(metadata, fmt=plistlib.FMT_BINARY)


# --- Backup ---


def backup_destination(dest: Path) -> Path | None:
    """Back up existing destination directory. Returns backup path or None."""
    if not dest.exists() or not any(dest.iterdir()):
        return None
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = dest.parent / f"{dest.name}.backup.{timestamp}"
    shutil.copytree(dest, backup_path)
    print(f"Backed up existing saves to: {backup_path}")
    return backup_path


# --- Quarantine ---


def remove_quarantine_xattrs(path: Path) -> None:
    """Remove com.apple.quarantine xattrs recursively."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(
            ["xattr", "-rd", "com.apple.quarantine", str(path)],
            capture_output=True,
        )
    except FileNotFoundError:
        pass


# --- Conversion ---


def convert_steam_to_icloud(source: Path, dest: Path, dry_run: bool) -> None:
    """Convert Steam saves to Mac App Store (iCloud) format."""
    saves = enumerate_steam_saves(source)
    if not saves:
        sys.exit("Error: No saves found in source directory.")

    device_name = get_device_name()
    print(f"Converting {len(saves)} files: Steam -> iCloud")
    print(f"Device name: {device_name}\n")

    if not dry_run:
        backup_destination(dest)
        # Clean existing bundles
        if dest.exists():
            for entry in dest.iterdir():
                if entry.is_dir() and entry.name.endswith(".bundle"):
                    shutil.rmtree(entry)
        else:
            dest.mkdir(parents=True)

    for relpath, filepath in saves:
        bundle_stem = steam_relpath_to_bundle_stem(relpath)
        bundle_dir = dest / f"{bundle_stem}.bundle"
        size_kb = filepath.stat().st_size / 1024

        if dry_run:
            print(f"  [dry-run] {relpath} ({size_kb:.0f} KB) -> {bundle_dir.name}")
            continue

        bundle_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(filepath, bundle_dir / "data")

        mod_date = get_modification_time(filepath)
        metadata_bytes = create_metadata_plist(device_name, mod_date)
        (bundle_dir / "metadata").write_bytes(metadata_bytes)

        print(f"  {relpath} ({size_kb:.0f} KB) -> {bundle_dir.name}")

    if not dry_run:
        # Create Documents dir
        (dest / "Documents").mkdir(exist_ok=True)
        # Remove cloudsave.dat
        cloudsave = dest / "cloudsave.dat"
        if cloudsave.exists():
            cloudsave.unlink()
            print("  Removed cloudsave.dat")
        # Remove quarantine
        remove_quarantine_xattrs(dest)

    print(f"\nDone! Converted {len(saves)} files.")
    print("Launch the game to regenerate the cloud sync manifest.")


def convert_icloud_to_steam(source: Path, dest: Path, dry_run: bool) -> None:
    """Convert Mac App Store (iCloud) saves to Steam format."""
    bundles = enumerate_icloud_bundles(source)
    if not bundles:
        sys.exit("Error: No save bundles found in source directory.")

    print(f"Converting {len(bundles)} files: iCloud -> Steam\n")

    if not dry_run:
        backup_destination(dest)
        dest.mkdir(parents=True, exist_ok=True)

    for stem, bundle_path in bundles:
        relpath = bundle_stem_to_steam_relpath(stem)
        data_file = bundle_path / "data"
        dest_file = dest / relpath
        size_kb = data_file.stat().st_size / 1024

        if dry_run:
            print(f"  [dry-run] {bundle_path.name} ({size_kb:.0f} KB) -> {relpath}")
            continue

        dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(data_file, dest_file)
        print(f"  {bundle_path.name} ({size_kb:.0f} KB) -> {relpath}")

    if not dry_run:
        vdf_path = dest / "steam_autocloud.vdf"
        if not vdf_path.exists():
            vdf_path.write_text(STEAM_AUTOCLOUD_VDF)
            print("  Created steam_autocloud.vdf")

    print(f"\nDone! Converted {len(bundles)} files.")


# --- CLI ---


def main():
    parser = argparse.ArgumentParser(
        description="Convert Death Stranding DC savegames between Steam and iCloud formats."
    )
    parser.add_argument("source", type=Path, help="Path to source save directory")
    parser.add_argument("destination", type=Path, help="Path to destination save directory")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    dest = args.destination.expanduser().resolve()
    fmt = detect_format(source)

    print(f"Source: {source} (detected: {fmt})")
    print(f"Destination: {dest}\n")

    if fmt == "steam":
        convert_steam_to_icloud(source, dest, args.dry_run)
    else:
        convert_icloud_to_steam(source, dest, args.dry_run)


if __name__ == "__main__":
    main()
