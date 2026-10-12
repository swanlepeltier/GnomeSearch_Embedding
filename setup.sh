#!/usr/bin/env bash
#
# Install the GNOME Embedding Search backend and GNOME Shell extension.
#
#   1. create a Python virtual environment and install dependencies
#   2. create .env from .env.example (if missing)
#   3. install and start the systemd --user service
#   4. install the GNOME Shell extension
#
# It is safe to re-run: existing files are preserved.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
EXT_UUID="embedding-search@gnome-search-embedding"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }

# --- 1. Python environment --------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtual environment in $VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi
info "Installing Python dependencies (this can take a while)"
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r "$PROJECT_DIR/backend/requirements.txt"

# --- 2. Make the system PyGObject (gi) visible ------------------------------
# pydbus needs PyGObject, which is a distribution package that pip cannot build
# reliably inside an isolated virtual environment. We therefore let the venv
# include the system site-packages (the standard "system-site-packages" flag),
# which exposes the system `gi` module without shadowing the venv's own packages.
if [ -f "$VENV_DIR/pyvenv.cfg" ]; then
    if grep -q '^include-system-site-packages' "$VENV_DIR/pyvenv.cfg"; then
        sed -i 's/^include-system-site-packages = .*/include-system-site-packages = true/' \
            "$VENV_DIR/pyvenv.cfg"
    else
        echo 'include-system-site-packages = true' >> "$VENV_DIR/pyvenv.cfg"
    fi
fi
if ! "$PYTHON_BIN" -c 'import gi' >/dev/null 2>&1; then
    warn "PyGObject ('gi') is not available to the virtual environment."
    warn "Install it from your package manager and re-run this script:"
    warn "  Fedora:  sudo dnf install python3-gobject"
    warn "  Debian:  sudo apt install python3-gi"
fi

# --- 3. Configuration -------------------------------------------------------
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    info "Created .env from .env.example — edit it to match your machine"
else
    info "Keeping existing .env"
fi

# --- 4. systemd user service ------------------------------------------------
SYSTEMD_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_DIR"
sed -e "s|@PROJECT_DIR@|$PROJECT_DIR|g" \
    -e "s|@PYTHON@|$PYTHON_BIN|g" \
    "$PROJECT_DIR/systemd/gnome-embedding-search.service.in" \
    > "$SYSTEMD_DIR/gnome-embedding-search.service"
info "Installed systemd user service"
if command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload
    systemctl --user reset-failed gnome-embedding-search.service 2>/dev/null || true
    systemctl --user enable --now gnome-embedding-search.service || \
        warn "Could not start the service now; start it manually with 'systemctl --user start gnome-embedding-search'"
fi

# --- 5. GNOME Shell extension -----------------------------------------------
EXT_DIR="$HOME/.local/share/gnome-shell/extensions/$EXT_UUID"
mkdir -p "$EXT_DIR"
cp "$PROJECT_DIR/extension/"*.js "$EXT_DIR/"
cp "$PROJECT_DIR/extension/"*.json "$EXT_DIR/"
cp "$PROJECT_DIR/extension/"*.css "$EXT_DIR/"
info "Installed extension to $EXT_DIR"

if command -v gnome-extensions >/dev/null 2>&1; then
    gnome-extensions enable "$EXT_UUID" 2>/dev/null || \
        warn "Enable the extension via 'gnome-extensions enable $EXT_UUID' (log out and back in first on Wayland)"
fi

info "Done!"
info "The model is downloaded on first run and the initial index starts automatically."
info "Follow progress with:  journalctl --user -u gnome-embedding-search -f"
