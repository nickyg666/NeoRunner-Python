#!/usr/bin/env sh
# NeoForge 26.x run script - properly configured
# Uses hardcoded path since we know the version

BASEDIR="$(cd "$(dirname "$0")" && pwd)"

# Use absolute path to the correct unix_args.txt
UNIX_ARGS_FILE="$BASEDIR/libraries/net/neoforged/neoforge/26.1.2.22-beta/unix_args.txt"

exec java "@$BASEDIR/user_jvm_args.txt" "@$UNIX_ARGS_FILE" "$@"