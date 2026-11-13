# WireGuard widget for OmniWM 0.8.0

A menu bar button that toggles a tunnel configured in the WireGuard macOS app. Click **VPN ON / VPN OFF** to connect or disconnect. Right-click for connection controls, status refresh, and Open WireGuard.

## Requirements

- macOS with **OmniWM 0.8.0**, installed at `/Applications/OmniWM.app`.
- OmniWM’s **Default** style, with its normal `focus-ribbon` island root (or this widget’s `wireguard` root).
- The WireGuard macOS app with a tunnel already imported and authorized to create a VPN connection.
- Python **3.11 or newer** only if using the bundled installer. The widget itself uses macOS’s built-in Perl and `scutil`.

This widget uses OmniWM 0.8.0’s native provider API. It does not require AWS, the ECS widget, Homebrew WireGuard tools, or administrator access.

## Install from a downloaded source archive

Download and extract the source, then open Terminal. Choose the method matching the files you downloaded.

### Complete package: use the installer

If the download contains `install.py` and a `wireguard/` directory, change into the directory containing `install.py`:

```sh
cd "$HOME/Downloads/wireguard-widget"
python3 --version
python3 install.py --dry-run
python3 install.py
```

Adjust the `cd` path to match the extracted folder. The dry run previews the configuration without writing files. With one WireGuard tunnel, the installer selects it automatically. With several tunnels, specify the name or service UUID on both commands:

```sh
python3 install.py --dry-run --tunnel 'Your tunnel name'
python3 install.py --tunnel 'Your tunnel name'
```

The installer copies the widget to `~/.config/omniwm/shell/widgets/wireguard/`, updates `~/.config/omniwm/shell/shell.toml`, and saves a timestamped backup in `~/.config/omniwm/shell/backups/wireguard-TIMESTAMP/`. It preserves other bar items and existing component entries. It refuses to replace a custom island root or install on another OmniWM version.

### Widget-only source: install manually

If the download contains `init.luau`, `component.luau`, `component.toml`, `focus-ribbon.luau`, and `provider.pl` directly, use this method.

1. Run OmniWM once and select the **Default** style so its shell configuration exists.
2. Back up your shell configuration before editing it:

   ```sh
   cp -R "$HOME/.config/omniwm/shell" \
     "$HOME/.config/omniwm/shell-backup-$(date +%Y%m%d-%H%M%S)"
   ```

3. In Terminal, change into the extracted directory containing `init.luau`, then copy the files:

   ```sh
   mkdir -p "$HOME/.config/omniwm/shell/widgets/wireguard"
   cp init.luau component.luau component.toml focus-ribbon.luau provider.pl README.md \
     "$HOME/.config/omniwm/shell/widgets/wireguard/"
   chmod 755 "$HOME/.config/omniwm/shell/widgets/wireguard/provider.pl"
   ```

4. Find your tunnel’s service UUID:

   ```sh
   /usr/sbin/scutil --nc list
   ```

   Locate the entry containing `(com.wireguard.macos)` and your tunnel’s name. Copy the UUID immediately before `VPN`.

5. Edit `~/.config/omniwm/shell/shell.toml`. In the existing `[profiles.default]` table, add `"wireguard"` to the `trailing` array, for example immediately before `"wifi"`. Keep all its existing entries. If `trailing` is inherited, copy its current list from `~/.config/omniwm/shell/default/shell.toml` before adding the widget: a user array replaces the inherited array.

6. Set the Default island root and add the provider component, replacing `YOUR-SERVICE-UUID` with the UUID from step 4:

   ```toml
   [profiles.default.island]
   root = "wireguard"

   [[profiles.default.island.components]]
   id = "wireguard-vpn"
   widget = "wireguard"
   enabled = true
   tunnel = "YOUR-SERVICE-UUID"
   pollSeconds = 3
   ```

   Merge these settings into existing tables; do not duplicate table headers or an existing `wireguard-vpn` component. Preserve all other component entries. If components are inherited, copy those entries from `default/shell.toml` before adding this one, because the component array also replaces the inherited array. Stop if you use a custom island root: this widget only preserves the bundled Default Focus Ribbon. The island itself can remain disabled.

### Approve the helper and check the widget

OmniWM normally reloads saved shell files automatically. Relaunch OmniWM if the button does not appear.

Approve **WireGuard** when OmniWM asks to trust `provider.pl`, or approve it under **OmniWM → Settings → Network & Permissions → Programs**. Editing the helper can require approval again.

The menu bar should display **VPN ON** or **VPN OFF**. Installation does not change the VPN connection. Click the button to test toggling when you are ready; this changes the selected tunnel’s connection state.

## Configuration and troubleshooting

The selected tunnel is the `tunnel` option in the `wireguard-vpn` component in `shell.toml`. A service UUID is preferred; reimporting a tunnel can change it. Rerun `scutil --nc list` and update the option if necessary.

Read the connection status without changing it:

```sh
"$HOME/.config/omniwm/shell/widgets/wireguard/provider.pl" --status 'Your tunnel name or UUID'
```

If the button shows **VPN !**, right-click to read the error. Check the program approval, tunnel name/UUID, and executable permission on `provider.pl`. Open WireGuard to check macOS VPN authorization. To restart a stopped helper, re-save the installed `init.luau` or relaunch OmniWM.

The helper polls every three seconds and only controls services belonging to `com.wireguard.macos`. It never reads WireGuard keys. “Connected” reports the macOS tunnel state; it does not verify a peer handshake or network reachability. WireGuard’s on-demand rules may reconnect a tunnel after you disconnect it.

OmniWM IPC is optional. If already enabled under **Settings → Advanced**, these commands can help inspect the widget:

```sh
omniwmctl query shell-widgets
omniwmctl shell toggle wireguard
```

## Update or remove

To update, back up your existing widget and configuration, then install the new source using the same method. Reapprove `provider.pl` if prompted.

To remove, edit `shell.toml`: remove `"wireguard"` from Default’s `trailing` array, remove only the `wireguard-vpn` component, and restore the island root to `"focus-ribbon"`. Then remove `~/.config/omniwm/shell/widgets/wireguard/` and relaunch OmniWM if needed. Leave unrelated components and settings intact. Restoring a whole backup also restores every other shell setting from the time it was made.

## Sources and license

- [OmniShell menu guide](https://omniwm.app/omnishell/guides/menus/)
- [Native provider API](https://omniwm.app/omnishell/reference/providers/)
- [OmniWM 0.8.0 component loading](https://github.com/OmniNull/OmniWM/blob/v0.8.0/Sources/OmniWM/Core/Shell/ShellWidgetHost%2BLoading.swift)
- `focus-ribbon.luau` is the GPL-2.0-only Default Focus Ribbon from OmniWM 0.8.0, copyright 2026 OmniNull, adapted by making `render` local and returning it as a module. [Original source](https://github.com/OmniNull/OmniWM/blob/v0.8.0/Sources/OmniWM/ShellDefault/widgets/focus-ribbon/init.luau).

This widget is distributed under GPL-2.0-only. The complete source package includes `LICENSE`.
