#!/bin/sh
# Fail closed: never start the gateway with a missing or weak token,
# otherwise "Bearer " (empty) would be accepted as a valid credential.
set -eu

if [ "${#MCP_HUB_TOKEN}" -lt 32 ]; then
	echo "FATAL: MCP_HUB_TOKEN must be set to at least 32 characters (try: openssl rand -hex 32)" >&2
	exit 1
fi

# Caddy's header matcher treats "*" as a wildcard; allow only safe characters.
check_charset() {
	case "$2" in
	*[!A-Za-z0-9_-]*)
		echo "FATAL: $1 may only contain A-Z a-z 0-9 _ -" >&2
		exit 1
		;;
	esac
}
check_charset MCP_HUB_TOKEN "$MCP_HUB_TOKEN"

# The rotation slot must never be empty, or it would match "Bearer ".
if [ -z "${MCP_HUB_TOKEN_2:-}" ]; then
	MCP_HUB_TOKEN_2="unset-$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
elif [ "${#MCP_HUB_TOKEN_2}" -lt 32 ]; then
	echo "FATAL: MCP_HUB_TOKEN_2 is set but shorter than 32 characters" >&2
	exit 1
fi
check_charset MCP_HUB_TOKEN_2 "$MCP_HUB_TOKEN_2"
export MCP_HUB_TOKEN_2
export GITHUB_PERSONAL_ACCESS_TOKEN="${GITHUB_PERSONAL_ACCESS_TOKEN:-}"

exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
