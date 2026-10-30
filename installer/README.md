# Xray Installer

## One-command interactive install/update

For a Linux host with systemd, run the interactive wrapper as root:

```bash
sudo bash installer/one-click.sh
```

It detects the CPU architecture, asks whether to install or update, downloads
the exact artifact from `manifest.json`, verifies its filename/version/SHA-256,
then delegates file installation to `install.sh`. An update keeps the existing
configuration and generation state. If the service restart fails, the previous
Xray binary and data files are restored when available.

When the repository is published under an immutable tag and is publicly
readable, the same flow can be started with one command from a clean Linux
host:

```bash
tmp="$(mktemp)" && curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
  --output "$tmp" https://raw.githubusercontent.com/shiyi-log/X-ray/v0.8.0/installer/one-click.sh \
  && sudo bash "$tmp"; status=$?; rm -f "$tmp"; exit "$status"
```

The remote wrapper downloads the helper files from the same immutable release
tag. To run a non-interactive online update on an existing Linux host, keep the
same bootstrap and set the action explicitly:

```bash
tmp="$(mktemp)" && curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
  --output "$tmp" https://raw.githubusercontent.com/shiyi-log/X-ray/v0.8.0/installer/one-click.sh \
  && sudo env XRAY_ONE_CLICK_ACTION=update XRAY_NONINTERACTIVE=1 bash "$tmp"; status=$?; rm -f "$tmp"; exit "$status"
```

Set `XRAY_INSTALLER_REF` when intentionally selecting another immutable tag or
commit. The Xray archive itself is always selected from the pinned manifest and
checked by SHA-256; no `latest` release is resolved.

This repository is currently private. Anonymous `curl` access to the raw GitHub
URL therefore returns `404`; use a host-side authenticated `gh api` download or
publish the repository/installer through an authorized public artifact host
before using the bootstrap command without credentials. The installer itself
does not accept or print GitHub credentials.

The interactive wrapper installs only the Xray runtime and service helpers. It
does not create subscription credentials, generate node configuration, or
print secrets. Configuration is still applied through the structured JSON
contract described below.

The installer accepts only an operator-supplied archive whose filename,
platform, version, and SHA-256 match `manifest.json`. It performs no network
download and never resolves a `latest` release.

Run `install.sh /path/to/Xray-<platform>.zip` on the target Linux host, then
send structured JSON on stdin to `apply-config.sh`. Configuration apply exit
codes are 10 for invalid input, 20 for invalid configuration, 30 for a stale
generation or lock conflict, and 40 for a service restart/recovery failure.

Security changes do not restore the previous configuration when restart
fails. The control plane must quarantine the node and reconcile it before any
reopen operation.

On Linux with systemd enabled, installation also places the apply and verify
helpers in `/opt/xray-manager`. Reinstalling preserves the current generation
and configuration. The service uses a systemd dynamic user and receives the
root-only configuration through `LoadCredential`; no static `xray` user or
broader configuration file permissions are required.
