#!/usr/bin/env python3
"""Launch inbox_server in-process, directly under the TCC-authorized interpreter.

WHY THIS EXISTS (do not collapse back into a bash wrapper):

macOS TCC grants Full Disk Access to a *responsible process*, determined by the
code signature of the process that actually performs the protected open(). When
launchd spawns a bash script (daemon-wrapper → run_server_daemon.sh) and that
shell later `exec`s python, TCC walks the responsible-process chain up to the
shell — the FDA grant on python3.12 never attaches, and iMessage / Notes /
Reminders reads silently return empty (sqlite "unable to open database file").

The durable fix is to make launchd exec the signed interpreter AS
ProgramArguments[0], with no shell hop in between, and do all environment setup
inside this same process (no `os.execv`). The frozen, ad-hoc-signed interpreter
at ~/Applications/inbox-python312/bin/python3.12 must never be re-signed or
rebuilt — its cdhash IS the Full Disk Access identity.
"""
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

# Project dependencies live in the uv venv, not in the frozen interpreter's own
# site-packages. Load them explicitly. Glob over python*/ so a future uv-managed
# interpreter version bump does not hard-break startup.
venv_site_packages = sorted(
    glob.glob(os.path.join(ROOT, ".venv", "lib", "python*", "site-packages")),
    reverse=True,
)
for sp in venv_site_packages:
    if sp not in sys.path:
        sys.path.insert(0, sp)
sys.path.insert(0, ROOT)

# Load runtime config from ~/.config/inbox/server.env (mode 600). This keeps the
# bearer token OUT of the public dotfiles repo. Missing keys are not fatal.
_env_file = os.path.expanduser("~/.config/inbox/server.env")
if os.path.isfile(_env_file):
    with open(_env_file, "r", encoding="utf-8") as fh:
        for _line in fh:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            _v = _v.strip()
            if len(_v) >= 2 and _v[0] == _v[-1] and _v[0] in {"'", '"'}:
                _v = _v[1:-1]
            os.environ.setdefault(_k.strip(), _v)

# Google Maps credential lives in the login Keychain, not the repo/server.env.
# Unavailable → Maps features stay disabled, everything else keeps running.
_keychain_account = os.environ.get("USER") or os.path.basename(os.path.expanduser("~"))
_maps = subprocess.run(
    [
        "/usr/bin/security",
        "find-generic-password",
        "-a",
        _keychain_account,
        "-s",
        "inbox-google-maps-api-key",
        "-w",
    ],
    capture_output=True,
    text=True,
)
if _maps.returncode == 0 and _maps.stdout.strip():
    os.environ["GOOGLE_MAPS_API_KEY"] = _maps.stdout.strip()
else:
    os.environ.pop("GOOGLE_MAPS_API_KEY", None)

import uvicorn

import inbox_server

_port = int(os.environ.get("INBOX_SERVER_PORT", inbox_server.PORT))
uvicorn.run(inbox_server.app, host="127.0.0.1", port=_port, log_level="info")
