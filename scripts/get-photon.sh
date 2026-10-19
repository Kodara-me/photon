#!/bin/sh
# Installs the latest Photon release as a root systemd service:
#
#   curl -fsSL https://github.com/jstmichel/photon/releases/latest/download/get-photon.sh | sh
#
# Usage: get-photon.sh [--version <tag>] [--yes] [--dry-run] [--help]
#
#   --version <tag>  install this release (for example v0.1.0) instead of the latest
#   --yes            answer yes to every question
#   --dry-run        download and check, then print the install command without running it
#
# Exit codes: 0 installed or already installed, 1 failure or refusal.

set -u

releases=${PHOTON_RELEASES_URL:-https://github.com/jstmichel/photon/releases}
tag=""
yes=0
dry_run=0

usage() {
    sed -n '2,12s/^# \{0,1\}//p' "$0" 2>/dev/null || echo "Usage: get-photon.sh [--version <tag>] [--yes] [--dry-run]"
}

say() {
    printf '%s\n' "$*"
}

fail() {
    printf 'error: %s\n' "$*" >&2
    exit 1
}

while [ $# -gt 0 ]; do
    case $1 in
        --version)
            [ $# -ge 2 ] || fail "--version needs a tag, for example v0.1.0"
            tag=$2
            shift 2
            ;;
        --yes) yes=1; shift ;;
        --dry-run) dry_run=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) fail "unknown option: $1 (see --help)" ;;
    esac
done

# Under `curl … | sh`, standard input is this script: questions and sudo read the terminal
# instead.
if [ -t 0 ]; then
    tty=/dev/stdin
elif (: </dev/tty) 2>/dev/null; then
    tty=/dev/tty
else
    tty=""
fi

# ask <question>: 0 for yes.
ask() {
    [ "$yes" -eq 1 ] && return 0
    [ -n "$tty" ] || fail "$1 Run again with --yes to answer yes."
    printf '%s [y/N] ' "$1"
    read -r answer <"$tty" || answer=""
    case $answer in
        y|Y|yes|Yes|o|O|oui|Oui) return 0 ;;
        *) return 1 ;;
    esac
}

# run <command…>: runs it on the terminal, or only prints it with --dry-run.
run() {
    if [ "$dry_run" -eq 1 ]; then
        say "  would run: $*"
        return 0
    fi
    if [ -n "$tty" ]; then
        "$@" <"$tty"
    else
        "$@" </dev/null
    fi
}

[ "$(id -u)" -ne 0 ] || fail "do not run this script as root; it calls sudo for the step that needs it"
[ "$(uname -s)" = Linux ] || fail "Photon runs on Linux only"
[ "$(uname -m)" = x86_64 ] || fail "Photon's bundle is built for x86_64, not $(uname -m)"
for tool in curl sha256sum mktemp sudo; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is needed"
done

# The bundle is run from this folder, so it must not sit on a noexec /tmp.
cache=${XDG_CACHE_HOME:-$HOME/.cache}
mkdir -p "$cache" || fail "cannot create $cache"
work=$(mktemp -d "$cache/photon-install.XXXXXX") || fail "cannot create a temporary folder"
trap 'rm -rf "$work"' EXIT
trap 'exit 1' INT TERM

if [ -n "$tag" ]; then
    base="$releases/download/$tag"
else
    base="$releases/latest/download"
fi

say "Looking for ${tag:-the latest release}…"
curl -fsSL -o "$work/SHA256SUMS" "$base/SHA256SUMS" || fail "cannot download $base/SHA256SUMS"
version=$(sed -n 's/^[0-9a-f]\{64\}  photon-\(.*\)\.tar\.gz$/\1/p' "$work/SHA256SUMS" | head -n 1)
[ -n "$version" ] || fail "the release's SHA256SUMS names no version"
grep -q '^[0-9a-f]\{64\}  photon$' "$work/SHA256SUMS" || fail "the release lists no photon bundle"

installed=""
if command -v photon >/dev/null 2>&1; then
    installed=$(photon --version 2>/dev/null | sed -n 's/^photon //p')
fi
if [ "$installed" = "$version" ]; then
    say "Photon $version is already installed."
    exit 0
fi

say "Downloading Photon $version…"
curl -fsSL -o "$work/photon" "$base/photon" || fail "cannot download $base/photon"
(cd "$work" && grep '  photon$' SHA256SUMS | sha256sum -c --status) \
    || fail "photon does not match the release's SHA256SUMS; nothing was installed"
chmod +x "$work/photon"
say "Checksum verified."

"$work/photon" service check || fail "the dependencies above are missing; nothing was installed"

if [ -n "$installed" ]; then
    question="Upgrade Photon $installed to $version?"
elif command -v kira-lights >/dev/null 2>&1; then
    say "KiraLights is installed: Photon replaces its service and keeps its color."
    question="Replace KiraLights with Photon $version?"
else
    question="Install Photon $version as a root systemd service?"
fi
ask "$question" || fail "nothing was installed"

say "Installing Photon $version…"
run sudo "$work/photon" service install || fail "the service was not installed"

if [ "$dry_run" -eq 1 ]; then
    say "Dry run: nothing was installed."
    exit 0
fi

say ""
say "Photon $version is installed and running. Stop Solaar and OpenRGB if they run."
say "Color: /etc/photon/config.toml, then sudo photon service restart."
say "Status: photon service status"
