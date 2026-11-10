#!/system/bin/sh
prefix='@TERMUX_PREFIX@'
binary="$prefix/libexec/codex/codex"
if [ "${CODEX_HOME+x}" ]; then
    exec "$binary" "$@"
fi

state="$prefix/var/lib/codex"
legacy="${HOME:+$HOME/.codex}"

prepare_home() (
    umask 077
    if [ ! -e "$state" ] && [ ! -L "$state" ]; then
        "$prefix/bin/mkdir" -p -- "${state%/*}" || exit 1
        if [ -n "$legacy" ] && [ -d "$legacy" ]; then
            stage=$("$prefix/bin/mktemp" -d "${state%/*}/.codex-migrate.XXXXXX") || exit 1
            trap '"$prefix/bin/rm" -rf -- "$stage"' EXIT
            trap 'exit 1' HUP INT TERM
            "$prefix/bin/cp" -RP --preserve=timestamps -- "$legacy/." "$stage" || exit 1
            # A simultaneous launch can win the rename. Keep its complete state.
            "$prefix/bin/mv" --update=none -T -- "$stage" "$state" || exit 1
        else
            "$prefix/bin/mkdir" -p -- "$state" || exit 1
        fi
    fi
    [ -d "$state" ] && [ ! -L "$state" ]
)

if ! prepare_home; then
    printf 'Codex: could not prepare the private state directory %s\n' "$state" >&2
    exit 1
fi
export CODEX_HOME="$state"
exec "$binary" "$@"
