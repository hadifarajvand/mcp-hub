#!/usr/bin/env bash
# Security checks against a running local hub (dev overlay). Uses REAL OAuth tokens (tests/hubclient.py).
#   ./tests/security.sh        (reads ./.env for HUBTEST_PASSWORD / HUB_OWNER_* )
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && . ./.env; set +a
BASE=${1:-http://127.0.0.1:8080}
export PYTHONPATH="$PWD/tests${PYTHONPATH:+:$PYTHONPATH}"
C="docker compose -f docker-compose.yml -f docker-compose.dev.yml"
fails=0
ok()   { echo "[PASS] $1"; }
bad()  { echo "[FAIL] $1"; fails=$((fails+1)); }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
expect() { [ "$2" = "$3" ] && ok "$1" || bad "$1 (got $2, want $3)"; }
tok()  { python3 tests/hubclient.py token "$@"; }
INIT='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"s","version":"1"}}}'
mcp()  { curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' -d "$INIT" "$@"; }

WTOK=$(tok web) || { echo "cannot obtain an OAuth token (is the stack up and .env loaded?)"; exit 2; }
[ -n "$WTOK" ] || { echo "empty token"; exit 2; }
ROUTES="dokploy transcriber github google-workspace web latex"

echo "== Authentication (OAuth bearer, validated by hub-auth via forward_auth) =="
for route in $ROUTES; do
  expect "$route: no token -> 401"               "$(mcp $BASE/$route/mcp)" 401
  expect "$route: garbage token -> 401"          "$(mcp -H 'Authorization: Bearer hat_wrong' $BASE/$route/mcp)" 401
  expect "$route: empty bearer -> 401"           "$(mcp -H 'Authorization: Bearer ' $BASE/$route/mcp)" 401
  expect "$route: wildcard bearer -> 401"        "$(mcp -H 'Authorization: Bearer *' $BASE/$route/mcp)" 401
  expect "$route: token in query -> 401"         "$(mcp "$BASE/$route/mcp?access_token=$WTOK")" 401
  expect "$route: Basic scheme -> 401"           "$(mcp -H "Authorization: Basic $WTOK" $BASE/$route/mcp)" 401
  h=$(curl -s -D- -o /dev/null -X POST $BASE/$route/mcp)
  if grep -qiE '^www-authenticate: Bearer resource_metadata=".*/.well-known/oauth-protected-resource/'"$route"'/mcp", scope="' <<<"$h"; then ok "$route: 401 carries resource_metadata + scope hint"; else bad "$route: 401 challenge malformed"; fi
  [ "$route" = web ] || expect "$route: a valid /web token is rejected here (audience binding)" "$(mcp -H "Authorization: Bearer $WTOK" $BASE/$route/mcp)" 401
done
expect "web: valid token -> 200"                       "$(mcp -H "Authorization: Bearer $WTOK" $BASE/web/mcp)" 200
expect "web: lowercase 'bearer' scheme is accepted (RFC 7235)" "$(mcp -H "Authorization: bearer $WTOK" $BASE/web/mcp)" 200
for p in /x/../web/mcp //web/mcp /WEB/mcp/../../verify; do
  c=$(mcp --path-as-is $BASE$p)
  [ "$c" != 200 ] && ok "path trick $p without token -> $c (never 200)" || bad "path trick $p reached upstream without a token"
done
expect "unknown route -> 404"                          "$(code $BASE/nope/mcp)" 404
expect "/healthz open -> 200"                          "$(code $BASE/healthz)" 200
[ "$(curl -s $BASE/healthz)" = "ok" ] && ok "/healthz leaks nothing" || bad "/healthz body"
expect "internal /verify is NOT reachable from outside" "$(code $BASE/verify)" 404
expect "...even with a spoofed route header and a valid token" "$(code -H 'X-Hub-Route: web' -H "Authorization: Bearer $WTOK" $BASE/verify)" 404
expect "oauth2callback reachable without bearer (Google redirect)" \
  "$([ "$(code "$BASE/google-workspace/oauth2callback?code=x&state=bogus")" != 401 ] && echo y)" y
expect "oauth callback is the ONLY bypass: /google-workspace/mcp -> 401" "$(code $BASE/google-workspace/mcp)" 401
h=$(curl -s -D- -o /dev/null -H "Authorization: Bearer $WTOK" $BASE/web/health)
if grep -qi '^server:' <<<"$h"; then bad "Server header exposed"; else ok "no Server header"; fi

echo "== hub-auth fails closed on missing/weak configuration =="
GOODH=$HUB_OWNER_PASSWORD_HASH; GOODT=$HUB_OWNER_TOTP_SECRET
trycfg() { # name, env...
  name=$1; shift
  out=$(docker run --rm "$@" mcp-hub-hub-auth 2>&1); rc=$?
  if [ $rc -ne 0 ] && grep -q FATAL <<<"$out"; then ok "hub-auth refuses: $name"; else bad "hub-auth STARTED with: $name"; fi
}
trycfg "no configuration at all"
trycfg "plain-http public URL" -e PUBLIC_BASE_URL=http://evil.example.com -e HUB_OWNER_PASSWORD_HASH="$GOODH" -e HUB_OWNER_TOTP_SECRET="$GOODT"
trycfg "public URL with a path" -e PUBLIC_BASE_URL=https://x.example.com/app -e HUB_OWNER_PASSWORD_HASH="$GOODH" -e HUB_OWNER_TOTP_SECRET="$GOODT"
trycfg "plaintext password instead of a hash" -e PUBLIC_BASE_URL=https://x.example.com -e HUB_OWNER_PASSWORD_HASH=hunter2 -e HUB_OWNER_TOTP_SECRET="$GOODT"
trycfg "weak argon2 parameters" -e PUBLIC_BASE_URL=https://x.example.com -e HUB_OWNER_PASSWORD_HASH='$argon2id$v=19$m=8,t=1,p=1$c29tZXNhbHQ$aGFzaA' -e HUB_OWNER_TOTP_SECRET="$GOODT"
trycfg "short TOTP secret" -e PUBLIC_BASE_URL=https://x.example.com -e HUB_OWNER_PASSWORD_HASH="$GOODH" -e HUB_OWNER_TOTP_SECRET=ABCDEFGH
trycfg "missing TOTP secret" -e PUBLIC_BASE_URL=https://x.example.com -e HUB_OWNER_PASSWORD_HASH="$GOODH"

echo "== Network isolation =="
for s in dokploy transcriber github google-workspace web searxng latex latex-worker hub-auth dokploy-stub web-fixture; do
  [ -z "$($C port $s 2>/dev/null)" ] && ok "$s publishes no host port" || bad "$s publishes a host port"
done
for p in 3000 8000 8082 9000 9100; do
  curl -s -m 2 -o /dev/null http://127.0.0.1:$p/ && bad "port $p reachable on host" || ok "port $p not reachable on host"
done
gw=$($C ps -q gateway); pub=$(docker port $gw 2>/dev/null | grep -v '^8080/tcp -> 127.0.0.1:8080$' | grep -v '^$' || true)
[ -z "$pub" ] && ok "gateway binds only 127.0.0.1:8080 in dev" || bad "unexpected gateway ports: $pub"
for n in latexnet authnet; do
  [ "$(docker network inspect mcp-hub_$n --format '{{.Internal}}' 2>/dev/null)" = true ] && ok "$n is an internal network (no egress)" || bad "$n is NOT internal"
done
netsof() { docker inspect "$($C ps -q $1)" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}'; }
[ "$(netsof latex-worker)" = "mcp-hub_latexnet " ] && ok "latex-worker is attached to latexnet only" || bad "latex-worker networks: $(netsof latex-worker)"
[ "$(netsof hub-auth)" = "mcp-hub_authnet " ] && ok "hub-auth is attached to authnet only (gateway is its only peer)" || bad "hub-auth networks: $(netsof hub-auth)"
[ "$(netsof web)" = "mcp-hub_fetchnet " ] && ok "web is attached to fetchnet only" || bad "web networks: $(netsof web)"
peers=$(docker network inspect mcp-hub_authnet --format '{{range .Containers}}{{.Name}}{{"\n"}}{{end}}' | sort | xargs)
[ "$peers" = "mcp-hub-gateway-1 mcp-hub-hub-auth-1" ] && ok "authnet contains exactly the gateway and hub-auth" || bad "authnet members: $peers"

echo "== Container hardening =="
for s in gateway dokploy github transcriber google-workspace web searxng latex latex-worker hub-auth; do
  id=$($C ps -q $s)
  j=$(docker inspect $id --format '{{.Config.User}}|{{.HostConfig.CapDrop}}|{{.HostConfig.SecurityOpt}}|{{.HostConfig.ReadonlyRootfs}}|{{.HostConfig.Privileged}}')
  IFS='|' read -r user cap sec ro priv <<<"$j"
  [ -n "$user" ] && [ "$user" != "0" ] && [ "$user" != "root" ] && ok "$s runs non-root ($user)" || bad "$s runs as root"
  [[ "$cap" == *ALL* ]] && ok "$s cap_drop ALL" || bad "$s keeps capabilities ($cap)"
  [[ "$sec" == *no-new-privileges* ]] && ok "$s no-new-privileges" || bad "$s allows privilege escalation"
  [ "$ro" = true ] && ok "$s read-only rootfs" || bad "$s writable rootfs"
  [ "$priv" = false ] && ok "$s not privileged" || bad "$s privileged"
  mounts=$(docker inspect $id --format '{{range .Mounts}}{{.Source}} {{end}}')
  [[ "$mounts" == *docker.sock* ]] && bad "$s mounts docker.sock" || true
done
mode=$($C exec -T hub-auth stat -c %a /data/hubauth.db 2>/dev/null)
[ "$mode" = 600 ] && ok "hub-auth database is mode 600" || bad "hub-auth database mode is '$mode' (want 600)"

echo "== Secret hygiene =="
SECRETS=("$WTOK" "$HUBTEST_PASSWORD" "$GOODT" "$GOODH")
for img in mcp-hub-gateway mcp-hub-dokploy mcp-hub-github mcp-hub-transcriber mcp-hub-google-workspace mcp-hub-web mcp-hub-latex mcp-hub-latex-worker mcp-hub-hub-auth; do
  hist=$(docker history --no-trunc $img 2>/dev/null)
  leak=0; for sec in "${SECRETS[@]}"; do [ -n "$sec" ] && grep -qF -- "$sec" <<<"$hist" && leak=1; done
  [ $leak = 0 ] && ok "$img image history holds no token / owner secret" || bad "$img image history contains a secret"
done
# Capture output first: `grep -q` in a pipeline SIGPIPEs the producer, which under pipefail turns a match into a false PASS.
for s in gateway hub-auth dokploy github transcriber google-workspace web searxng latex latex-worker; do
  logs=$($C logs $s 2>&1); leak=0
  for sec in "${SECRETS[@]}"; do [ -n "$sec" ] && grep -qF -- "$sec" <<<"$logs" && leak=1; done
  [ $leak = 0 ] && ok "$s logs hold no token / owner secret" || bad "$s logs contain a secret"
done
logs=$($C logs gateway dokploy 2>&1)
if grep -q 'stub-dokploy-api-key' <<<"$logs"; then bad "logs leak Dokploy API key"; else ok "logs have no Dokploy API key"; fi
DTOK=$(tok dokploy)
body=$(curl -s -X POST -H "Authorization: Bearer $DTOK" -H 'Content-Type: application/json' -d "$INIT" $BASE/dokploy/mcp)
if grep -qF -- "$DTOK" <<<"$body"; then bad "token echoed in response"; else ok "token not echoed in responses"; fi

echo "== Dokploy secret redaction =="
out=$(python3 - "$BASE" <<'PY'
import asyncio, sys, httpx, hubclient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
async def main():
    h = httpx.AsyncClient(auth=hubclient.HubAuth("dokploy"), timeout=60)
    async with Client(streamable_http_client(sys.argv[1] + "/dokploy/mcp", http_client=h)) as c:
        r = await c.call_tool("project-all", {})
        print(r.model_dump_json())
asyncio.run(main())
PY
)
if grep -q 'super-secret-value-should-be-redacted' <<<"$out"; then bad "Dokploy MCP leaked env secret"; else ok "Dokploy env secret redacted"; fi
if grep -q 'stub-project' <<<"$out"; then ok "(sanity) stub data was returned"; else bad "no stub data returned"; fi

echo "== Transcriber SSRF =="
ssrf() { python3 - "$BASE" "$1" <<'PY'
import asyncio, sys, httpx, hubclient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
async def main():
    h = httpx.AsyncClient(auth=hubclient.HubAuth("transcriber"), timeout=60)
    async with Client(streamable_http_client(sys.argv[1] + "/transcriber/mcp", http_client=h)) as c:
        r = await c.call_tool("transcribe", {"audio_url": sys.argv[2]})
        print(r.model_dump_json())
asyncio.run(main())
PY
}
for u in http://169.254.169.254/latest/meta-data http://dokploy:3000/health http://dokploy-stub:3000/api/project.all http://127.0.0.1:8000/health http://gateway:8080/healthz http://hub-auth:9000/verify "http://[::1]:8000/" file:///etc/passwd; do
  res=$(ssrf "$u")
  if grep -qE 'Refusing|Only http|Cannot resolve|not allowed|credentials' <<<"$res"; then ok "SSRF blocked: $u"; else bad "SSRF NOT blocked: $u"; fi
done

echo; [ $fails -eq 0 ] && echo "ALL SECURITY CHECKS PASSED" || echo "$fails SECURITY CHECK(S) FAILED"
exit $((fails>0))
