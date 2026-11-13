#!/usr/bin/env python3
"""Install the WireGuard bar widget into OmniWM 0.8.0's Default style."""
import argparse
import datetime
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

SOURCE = Path(__file__).resolve().parent / "wireguard"
SERVICE = re.compile(
    r'^\s*\*?\s*\([^)]+\)\s+([A-Fa-f0-9-]{36})\s+VPN\s+'
    r'\(com\.wireguard\.macos\)\s+"(.*)"\s+\[VPN:com\.wireguard\.macos\]\s*$', re.M
)


def set_value(text, section, key, value):
    """Change one key in one table, retaining comments and unrelated TOML."""
    header = re.search(r"^\[" + re.escape(section) + r"\][ \t]*(?:#.*)?$", text, re.M)
    encoded = json.dumps(value, ensure_ascii=False)
    if header is None:
        return text.rstrip() + f"\n\n[{section}]\n{key} = {encoded}\n"
    following = re.search(r"^\[", text[header.end():], re.M)
    end = header.end() + following.start() if following else len(text)
    body = text[header.end():end]
    if isinstance(value, list):
        pattern = r"^" + re.escape(key) + r"\s*=\s*\[[\s\S]*?\]"
    else:
        pattern = r"^" + re.escape(key) + r"[ \t]*=[^\n]*"
    body, count = re.subn(pattern, lambda _: f"{key} = {encoded}", body, count=1, flags=re.M)
    if count == 0:
        body = "\n" + f"{key} = {encoded}\n" + body.lstrip("\n")
    return text[:header.end()] + body + text[end:]


def configure(original, tunnel, inherited):
    data = tomllib.loads(original)
    if data.get("profile", "default") != "default":
        raise ValueError("Select the Default style first; this package preserves Default’s Focus Ribbon.")
    profile = data.get("profiles", {}).get("default", {})
    island = profile.get("island", {})
    root = island.get("root", inherited.get("island", {}).get("root", "focus-ribbon"))
    if root not in ("focus-ribbon", "wireguard"):
        raise ValueError(f"Default already uses the custom island root {root!r}; refusing to replace it.")
    trailing = list(profile.get("trailing", inherited.get("trailing", [])))
    if "wireguard" not in trailing:
        trailing.insert(trailing.index("wifi") if "wifi" in trailing else 0, "wireguard")
    updated = set_value(original, "profiles.default", "trailing", trailing)
    updated = set_value(updated, "profiles.default.island", "root", "wireguard")
    components = island.get("components", inherited.get("island", {}).get("components", []))
    existing = next((c for c in components if c.get("id") == "wireguard-vpn"), None)
    if existing:
        if existing.get("widget") != "wireguard" or existing.get("tunnel") != tunnel:
            raise ValueError("A wireguard-vpn component already exists with different settings. Edit shell.toml to update it.")
    else:
        # Arrays override inherited lists. Materialize any inherited instances
        # before appending ours, so existing components are retained.
        if "components" not in island:
            for component in components:
                if any(isinstance(v, dict) for v in component.values()):
                    raise ValueError("Inherited component capabilities need a manual merge in shell.toml.")
                updated += "\n[[profiles.default.island.components]]\n"
                updated += "".join(f"{k} = {json.dumps(v, ensure_ascii=False)}\n" for k, v in component.items())
        updated += "\n[[profiles.default.island.components]]\n"
        updated += 'id = "wireguard-vpn"\nwidget = "wireguard"\nenabled = true\n'
        updated += f"tunnel = {json.dumps(tunnel, ensure_ascii=False)}\npollSeconds = 3\n"
    tomllib.loads(updated)  # Reject invalid TOML before writing anything.
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tunnel", help="WireGuard tunnel name or service UUID; auto-detected if there is only one")
    parser.add_argument("--shell-dir", type=Path, default=Path.home() / ".config/omniwm/shell")
    parser.add_argument("--dry-run", action="store_true", help="Print the proposed configuration without writing files")
    args = parser.parse_args()
    app = Path("/Applications/OmniWM.app")
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleShortVersionString") != "0.8.0":
        raise ValueError("This installer targets OmniWM 0.8.0. Review compatibility before using another release.")
    listing = subprocess.run(["/usr/sbin/scutil", "--nc", "list"], check=True, capture_output=True, text=True, timeout=10).stdout
    services = SERVICE.findall(listing)
    matches = [(uid, name) for uid, name in services
               if not args.tunnel or args.tunnel.lower() == uid.lower() or args.tunnel == name]
    if len(matches) != 1:
        raise ValueError("Choose exactly one WireGuard tunnel with --tunnel NAME_OR_UUID. Found: " + repr(services))
    tunnel, name = matches[0]
    shell = args.shell_dir.expanduser().resolve()
    config = shell / "shell.toml"
    inherited = tomllib.loads((shell / "default/shell.toml").read_text())
    original = config.read_text() if config.exists() else ""
    updated = configure(original, tunnel, inherited)
    destination = shell / "widgets/wireguard"
    if config.is_symlink():
        raise ValueError("shell.toml is a symlink. Apply the config.example.toml changes in its authoritative source.")
    print(f"Tunnel: {name} ({tunnel})\nWidget: {destination}")
    if args.dry_run:
        print("\nProposed shell.toml:\n" + updated)
        return
    if destination.is_symlink():
        raise ValueError("The wireguard widget is a symlink; refusing to replace it.")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = shell / "backups" / ("wireguard-" + stamp)
    backup.mkdir(parents=True, exist_ok=False)
    if config.exists():
        shutil.copy2(config, backup / "shell.toml")
    if destination.exists():
        shutil.copytree(destination, backup / "wireguard")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".wireguard-install-", dir=shell) as temporary:
        staging = Path(temporary)
        shutil.copytree(SOURCE, staging / "wireguard")
        os.chmod(staging / "wireguard/provider.pl", 0o755)
        (staging / "shell.toml").write_text(updated)
        if config.exists():
            shutil.copymode(config, staging / "shell.toml")
        if config.exists() and config.read_text() != original:
            raise ValueError("shell.toml changed during installation. Retry after saving your settings.")
        old = staging / "old-widget"
        if destination.exists():
            destination.rename(old)
        try:
            (staging / "wireguard").rename(destination)
            (staging / "shell.toml").replace(config)
        except Exception:
            if destination.exists():
                shutil.rmtree(destination)
            if old.exists():
                old.rename(destination)
            raise
    print(f"Installed. Backup: {backup}")
    print("Approve the WireGuard program in OmniWM > Settings > Network & Permissions > Programs.")
    print("Click VPN to toggle; right-click for the menu. No VPN connection was changed by installation.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
