#!/usr/bin/env bash
# Evidence suite for the skills registry MCP plugin.
# Measures bytes (token-proxy) + latency for the four discovery loops.
set -u
URL="https://ca-cowork-mcp.lemonsea-9c8971ad.uksouth.azurecontainerapps.io/api/mcp"
H_CT="Content-Type: application/json"
H_AC="Accept: application/json, text/event-stream"

# --- 1. initialize, capture session id ---------------------------------
INIT_BODY='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"evidence-suite","version":"1.0"}}}'
HDR=$(mktemp); BODY=$(mktemp)
curl -s -D "$HDR" -o "$BODY" -H "$H_CT" -H "$H_AC" -X POST "$URL" -d "$INIT_BODY" > /dev/null
SID=$(grep -i '^mcp-session-id:' "$HDR" | awk '{print $2}' | tr -d '\r\n')
echo "session: $SID"
rm -f "$HDR" "$BODY"
H_SID="Mcp-Session-Id: $SID"

# notifications/initialized (required before subsequent calls)
curl -s -H "$H_CT" -H "$H_AC" -H "$H_SID" -X POST "$URL" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' > /dev/null

# --- helper: call a method, print bytes + ms + inner-content size ------
call() {
  local label="$1"; local body="$2"
  local out; out=$(mktemp)
  local t1; t1=$(date +%s%3N)
  local bytes; bytes=$(curl -s -H "$H_CT" -H "$H_AC" -H "$H_SID" -X POST "$URL" -d "$body" -w '%{size_download}' -o "$out")
  local t2; t2=$(date +%s%3N)
  local ms=$((t2 - t1))
  # SSE: strip "data: " prefix, find the JSON line, extract result.content[0].text length
  local inner
  inner=$(grep -E '^data:' "$out" | sed 's/^data: //' | python -c "import sys,json
for line in sys.stdin:
  line=line.strip()
  if not line: continue
  try: o=json.loads(line)
  except: continue
  r=o.get('result') or {}
  c=r.get('content') or []
  if c and isinstance(c[0],dict):
    print(len(c[0].get('text','')))
    break
  if 'tools' in r:
    print(sum(len(json.dumps(t)) for t in r['tools']))
    break
")
  printf '%-44s bytes=%-6s ms=%-5s inner=%s\n' "$label" "$bytes" "$ms" "${inner:-n/a}"
  rm -f "$out"
}

echo
echo "== T1  tools/list (the constant) =================================="
call "tools/list" '{"jsonrpc":"2.0","id":10,"method":"tools/list"}'

echo
echo "== T2  list_capabilities (one call, whole inventory) =============="
call "list_capabilities()" '{"jsonrpc":"2.0","id":20,"method":"tools/call","params":{"name":"list_capabilities","arguments":{}}}'

echo
echo "== T3  find_skill_by_capability across 6 tags ====================="
for tag in meeting.summarise invoice.extract content.draft ads.extract lead.research pdf.extract; do
  call "find_skill_by_capability($tag)" "$(printf '{"jsonrpc":"2.0","id":30,"method":"tools/call","params":{"name":"find_skill_by_capability","arguments":{"tag":"%s"}}}' "$tag")"
done

echo
echo "== T4  describe_skill across 4 skills ============================="
for sid in comms/meeting-insights finance/invoice-extract research/lead-research content/research-writer; do
  call "describe_skill($sid)" "$(printf '{"jsonrpc":"2.0","id":40,"method":"tools/call","params":{"name":"describe_skill","arguments":{"skill_id":"%s"}}}' "$sid")"
done

echo
echo "== T6  negative \u2014 unknown tag (no bottleneck) ===================="
call "find_skill_by_capability(does.not.exist)" '{"jsonrpc":"2.0","id":60,"method":"tools/call","params":{"name":"find_skill_by_capability","arguments":{"tag":"does.not.exist"}}}'
