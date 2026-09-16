# Xray Offline Installer

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
