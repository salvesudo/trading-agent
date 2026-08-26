#!/usr/bin/env bash
# ============================================================
# FYERS Trading Agent -- fresh-machine bootstrap script
# ============================================================
# Run this on any fresh Linux machine (a new/replacement EC2 instance,
# most likely) to get it ready to run this agent from nothing but a
# base OS image. Safe to re-run -- every step checks whether it's
# already done before repeating it, so re-running after a partial
# failure or to pick up a `git pull` is fine.
#
# Two ways to run it:
#
#   1. You already have git and a clone of the repo:
#        cd trading-agent
#        bash scripts/bootstrap_ec2.sh
#
#   2. Truly bare instance (nothing installed yet) -- curl is
#      preinstalled on every stock Amazon Linux / Ubuntu AWS AMI, so
#      this single line bootstraps everything, including cloning the
#      repo itself:
#        curl -fsSL https://raw.githubusercontent.com/salvesudo/trading-agent/main/scripts/bootstrap_ec2.sh | bash
#
# Supports Amazon Linux (yum/dnf) and Ubuntu/Debian (apt). Tested by
# reasoning + syntax-checking from a Windows dev machine that can't run
# yum/apt directly -- NOT yet run end-to-end on a real fresh EC2
# instance from this environment. Run it for real once and report back
# what broke, same as everything else in this project that needed a
# live environment to actually confirm.
#
# What this script does NOT do -- these are one-time, manual, and
# outside what a script running ON the instance can safely automate:
#   - AWS Security Group / firewall changes (needs AWS console/CLI
#     access from OUTSIDE this instance)
#   - Allocating/associating an Elastic IP
#   - Filling in real secrets into .env (FYERS credentials, DATABASE_URL, etc.)
#   - Registering a redirect URL in the FYERS app dashboard
#   - Standing up a real PostgreSQL server (SQLite works fine for local
#     dev/testing without one -- see app/db/base.py)
# ============================================================
set -euo pipefail

REPO_URL="https://github.com/salvesudo/trading-agent.git"
REPO_DIR="${REPO_DIR:-$HOME/trading-agent}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "============================================================"
echo "FYERS Trading Agent -- bootstrap"
echo "============================================================"

# --- 1. Detect package manager ---
if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt"
elif command -v dnf >/dev/null 2>&1; then
    PKG_MANAGER="dnf"
elif command -v yum >/dev/null 2>&1; then
    PKG_MANAGER="yum"
else
    echo "ERROR: no supported package manager found (looked for apt-get/dnf/yum)." >&2
    echo "This script supports Ubuntu/Debian and Amazon Linux/RHEL/Fedora." >&2
    exit 1
fi
echo "Detected package manager: $PKG_MANAGER"

# --- 2. Install system packages: git, python3, pip, venv, a compiler
#     as a fallback for any dependency without a prebuilt wheel ---
echo "--- Installing system packages ---"
case "$PKG_MANAGER" in
    apt)
        sudo apt-get update -y
        sudo apt-get install -y git python3 python3-pip python3-venv build-essential
        ;;
    dnf)
        sudo dnf install -y git python3 python3-pip gcc python3-devel
        ;;
    yum)
        sudo yum install -y git python3 python3-pip gcc python3-devel
        ;;
esac

# --- 3. Clone the repo, or pull latest if it's already there ---
if [ -d "$REPO_DIR/.git" ]; then
    echo "--- Repo already present at $REPO_DIR, pulling latest ---"
    git -C "$REPO_DIR" pull
else
    echo "--- Cloning repo into $REPO_DIR ---"
    git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

# --- 4. Create the virtual environment ---
if [ ! -f "venv/bin/activate" ]; then
    echo "--- Creating virtual environment ---"
    "$PYTHON_BIN" -m venv venv
else
    echo "--- Virtual environment already exists ---"
fi

# --- 5. Make sure pip actually exists inside the venv. On at least one
#     real run of this project, `python -m venv` silently produced a
#     venv with no pip.exe/pip launcher (ensurepip didn't fire) -- this
#     bootstraps/repairs it unconditionally rather than assuming it's fine. ---
echo "--- Ensuring pip is present in the venv ---"
venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1 || true
venv/bin/python -m pip install --upgrade pip

# --- 6. Install project dependencies ---
echo "--- Installing Python dependencies (this can take a few minutes) ---"
venv/bin/pip install -r requirements.txt

# --- 7. Create .env from the template if one doesn't exist yet.
#     NEVER overwrites an existing .env -- it holds real secrets once
#     filled in, and .env is gitignored so a `git pull` never touches it. ---
if [ ! -f ".env" ]; then
    echo "--- Creating .env from .env.example ---"
    cp .env.example .env
    NEW_ENV_CREATED=1
else
    echo "--- .env already exists, leaving it untouched ---"
    NEW_ENV_CREATED=0
fi

# --- 8. Sanity checks: config loads, and the full test suite passes
#     using only fakes/mocks -- no live network or real DB needed for
#     this to succeed, so it's a fair "is this machine ready" signal. ---
echo "--- Running config_check ---"
venv/bin/python -m app.core.config_check || true

echo "--- Running the test suite ---"
venv/bin/python -m pytest tests/ -q

echo "============================================================"
echo "Bootstrap complete: $REPO_DIR"
echo "============================================================"
if [ "$NEW_ENV_CREATED" = "1" ]; then
    echo "!!! .env was just created from the template with placeholder"
    echo "    values -- edit it now before anything live will work:"
    echo "    FYERS_APP_ID, FYERS_SECRET_ID, FYERS_REDIRECT_URI,"
    echo "    FYERS_STATIC_IP, DATABASE_URL, etc."
    echo
fi
echo "Still needed before this instance can do anything with FYERS:"
echo "  1. Edit .env with real values (if not already done above)."
echo "  2. Open inbound TCP on whatever port the FYERS redirect callback"
echo "     uses, in THIS instance's AWS Security Group -- that's an AWS"
echo "     console/CLI action from outside this machine, not something"
echo "     this script can do for you."
echo "  3. Register that redirect URL in the FYERS app dashboard."
echo "  4. Run the daily login:"
echo "       cd $REPO_DIR && source venv/bin/activate"
echo "       python -m app.broker.auth            # manual copy/paste flow"
echo "       # or: python -m app.broker.callback_server   # if the port is reachable"
echo "  5. Verify everything: python -m app.security.compliance_check"
