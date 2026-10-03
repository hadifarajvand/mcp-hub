#!/usr/bin/env bash
# Security checks against a running local hub (dev overlay).
#   MCP_HUB_TOKEN=... ./tests/security.sh
set -uo pipefail
cd "$(dirname "$0")/.."
BASE=${1:-http://127.0.0.1:8080}
TOKEN=${MCP_HUB_TOKEN:?set MCP_HUB_TOKEN}
C="docker compose -f docker-compose.yml -f docker-compose.dev.yml"
fails=0
ok()   { echo "[PASS] $1"; }
bad()  { echo "[FAIL] $1"; fails=$((fails+1)); }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
expect() { [ "$2" = "$3" ] && ok "$1" || bad "$1 (got $2, want $3)"; }

echo "== Authentication =="
for route in dokploy transcriber github google-workspace; do
  expect "$route: no token -> 401"          "$(code -X POST $BASE/$route/mcp)" 401
  expect "$route: wrong token -> 401"       "$(code -X POST -H 'Authorization: Bearer wrong' $BASE/$route/mcp)" 401
  expect "$route: empty bearer -> 401"      "$(code -X POST -H 'Authorization: Bearer ' $BASE/$route/mcp)" 401
  expect "$route: wildcard bearer -> 401"   "$(code -X POST -H 'Authorization: Bearer *' $BASE/$route/mcp)" 401
  expect "$route: token in query -> 401"    "$(code -X POST "$BASE/$route/mcp?token=$TOKEN")" 401
  expect "$route: Basic scheme -> 401"      "$(code -X POST -H "Authorization: Basic $TOKEN" $BASE/$route/mcp)" 401
  expect "$route: lowercase 'bearer' -> 401" "$(code -X POST -H "Authorization: bearer $TOKEN" $BASE/$route/mcp)" 401
done
expect "path traversal /x/../dokploy no token -> 401" "$(code --path-as-is $BASE/x/../dokploy/mcp)" 401
expect "double slash //dokploy/mcp no token -> 401"   "$(code --path-as-is $BASE//dokploy/mcp)" 401
expect "case variant /DOKPLOY/mcp no token -> 401"    "$(code $BASE/DOKPLOY/mcp)" 401
expect "unknown route with token -> 404"              "$(code -H "Authorization: Bearer $TOKEN" $BASE/nope/mcp)" 404
expect "unknown route without token -> 401 (no route enumeration)" "$(code $BASE/nope/mcp)" 401
expect "/healthz open -> 200"                          "$(code $BASE/healthz)" 200
[ "$(curl -s $BASE/healthz)" = "ok" ] && ok "/healthz leaks nothing" || bad "/healthz body"
expect "oauth2callback reachable without bearer (Google redirect)" \
  "$([ "$(code "$BASE/google-workspace/oauth2callback?code=x&state=bogus")" != 401 ] && echo y)" y
expect "oauth callback is the ONLY bypass: /google-workspace/mcp -> 401" "$(code $BASE/google-workspace/mcp)" 401
h=$(curl -s -D- -o /dev/null -H "Authorization: Bearer $TOKEN" $BASE/dokploy/health)
if grep -qi '^server:' <<<"$h"; then bad "Server header exposed"; else ok "no Server header"; fi

echo "== Gateway fails closed =="
for t in "" "short" "has*star-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"; do
  out=$(docker run --rm -e MCP_HUB_TOKEN="$t" mcp-hub-gateway 2>&1); rc=$?
  if [ $rc -ne 0 ] && grep -q FATAL <<<"$out"; then ok "gateway refuses token '${t:0:10}'"; else bad "gateway started with token '$t'"; fi
done

echo "== Network isolation =="
for s in dokploy transcriber github google-workspace dokploy-stub; do
  [ -z "$($C port $s 2>/dev/null)" ] && ok "$s publishes no host port" || bad "$s publishes a host port"
done
for p in 3000 8000 8082; do
  curl -s -m 2 -o /dev/null http://127.0.0.1:$p/health && bad "port $p reachable on host" || ok "port $p not reachable on host"
done
gw=$($C ps -q gateway); pub=$(docker port $gw 2>/dev/null | grep -v '^8080/tcp -> 127.0.0.1:8080$' | grep -v '^$' || true)
[ -z "$pub" ] && ok "gateway binds only 127.0.0.1:8080 in dev" || bad "unexpected gateway ports: $pub"
net=$(docker network inspect mcp-hub_hub --format '{{.Internal}}' 2>/dev/null)
echo "   (hub network internal flag: $net)"

echo "== Container hardening =="
for s in gateway dokploy github transcriber google-workspace; do
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

echo "== Secret hygiene =="
for img in mcp-hub-gateway mcp-hub-dokploy mcp-hub-github mcp-hub-transcriber mcp-hub-google-workspace; do
  hist=$(docker history --no-trunc $img 2>/dev/null)
  if grep -qF -- "$TOKEN" <<<"$hist"; then bad "$img history contains hub token"; else ok "$img history clean"; fi
done
# Capture output first: `grep -q` in a pipeline SIGPIPEs the producer, which under
# pipefail turns a match into a false PASS.
for s in gateway dokploy github transcriber google-workspace; do
  logs=$($C logs $s 2>&1)
  if grep -qF -- "$TOKEN" <<<"$logs"; then bad "$s logs contain hub token"; else ok "$s logs have no hub token"; fi
done
logs=$($C logs gateway dokploy 2>&1)
if grep -q 'stub-dokploy-api-key' <<<"$logs"; then bad "logs leak Dokploy API key"; else ok "logs have no Dokploy API key"; fi
# Client Authorization must not be forwarded upstream.
body=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" $BASE/dokploy/mcp -d '{}' ) 
if grep -qF -- "$TOKEN" <<<"$body"; then bad "token echoed in response"; else ok "token not echoed in responses"; fi

echo "== Dokploy secret redaction =="
out=$(MCP_HUB_TOKEN=$TOKEN python3 - "$BASE" <<'PY'
import asyncio, os, sys, httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
async def main():
    h = httpx.AsyncClient(headers={"Authorization": "Bearer " + os.environ["MCP_HUB_TOKEN"]})
    async with Client(streamable_http_client(sys.argv[1] + "/dokploy/mcp", http_client=h)) as c:
        r = await c.call_tool("project-all", {})
        print(r.model_dump_json())
asyncio.run(main())
PY
)
if grep -q 'super-secret-value-should-be-redacted' <<<"$out"; then bad "Dokploy MCP leaked env secret"; else ok "Dokploy env secret redacted"; fi
if grep -q 'stub-project' <<<"$out"; then ok "(sanity) stub data was returned"; else bad "no stub data returned"; fi

echo "== Transcriber SSRF =="
ssrf() { MCP_HUB_TOKEN=$TOKEN python3 - "$BASE" "$1" <<'PY'
import asyncio, os, sys, httpx
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
async def main():
    h = httpx.AsyncClient(headers={"Authorization": "Bearer " + os.environ["MCP_HUB_TOKEN"]})
    async with Client(streamable_http_client(sys.argv[1] + "/transcriber/mcp", http_client=h)) as c:
        r = await c.call_tool("transcribe", {"audio_url": sys.argv[2]})
        print(r.model_dump_json())
asyncio.run(main())
PY
}
for u in http://169.254.169.254/latest/meta-data http://dokploy:3000/health http://dokploy-stub:3000/api/project.all http://127.0.0.1:8000/health http://gateway:8080/healthz "http://[::1]:8000/" file:///etc/passwd; do
  res=$(ssrf "$u")
  if grep -qE 'Refusing|Only http|Cannot resolve|not allowed|credentials' <<<"$res"; then ok "SSRF blocked: $u"; else bad "SSRF NOT blocked: $u"; fi
done

echo; [ $fails -eq 0 ] && echo "ALL SECURITY CHECKS PASSED" || echo "$fails SECURITY CHECK(S) FAILED"
exit $((fails>0))
