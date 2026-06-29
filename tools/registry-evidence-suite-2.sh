#!/usr/bin/env bash
# Extends the evidence suite with the combined / repeated call patterns
# that correspond to the Cowork /cost test matrix.
set -u
URL="https://ca-cowork-mcp.lemonsea-9c8971ad.uksouth.azurecontainerapps.io/api/mcp"
H_CT="Content-Type: application/json"
H_AC="Accept: application/json, text/event-stream"

INIT_BODY='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"evidence-suite-2","version":"1.0"}}}'
HDR=$(mktemp); BODY=$(mktemp)
curl -s -D "$HDR" -o "$BODY" -H "$H_CT" -H "$H_AC" -X POST "$URL" -d "$INIT_BODY" > /dev/null
SID=$(grep -i '^mcp-session-id:' "$HDR" | awk '{print $2}' | tr -d '\r\n')
rm -f "$HDR" "$BODY"
H_SID="Mcp-Session-Id: $SID"
curl -s -H "$H_CT" -H "$H_AC" -H "$H_SID" -X POST "$URL" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' > /dev/null

call() {
  local label="$1"; local body="$2"
  local out; out=$(mktemp)
  local t1; t1=$(date +%s%3N)
  local bytes; bytes=$(curl -s -H "$H_CT" -H "$H_AC" -H "$H_SID" -X POST "$URL" -d "$body" -w '%{size_download}' -o "$out")
  local t2; t2=$(date +%s%3N)
  local ms=$((t2 - t1))
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
")
  printf '%-46s bytes=%-6s ms=%-5s inner=%s\n' "$label" "$bytes" "$ms" "${inner:-n/a}"
  rm -f "$out"
}

echo "== B  tools/list only (host enumerates tools) ====================="
curl -s -H "$H_CT" -H "$H_AC" -H "$H_SID" -X POST "$URL" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' -w '%{size_download}\n' -o /dev/null \
  | awk '{printf "tools/list                                     bytes=%s\n",$1}'

echo
echo "== C  one tool call: list_capabilities ============================"
call "list_capabilities()" '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"list_capabilities","arguments":{}}}'

echo
echo "== D  one tool call: find_skill_by_capability ====================="
call "find(meeting.summarise)" '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"find_skill_by_capability","arguments":{"tag":"meeting.summarise"}}}'

echo
echo "== E  two tool calls: find + describe ============================="
call "find(invoice.extract)" '{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"find_skill_by_capability","arguments":{"tag":"invoice.extract"}}}'
call "describe(finance/invoice-extract)" '{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"describe_skill","arguments":{"skill_id":"finance/invoice-extract"}}}'

echo
echo "== F  full loop: list_caps + find + describe + invoice_extract ===="
call "list_capabilities()" '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"list_capabilities","arguments":{}}}'
call "find(invoice.extract)" '{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"find_skill_by_capability","arguments":{"tag":"invoice.extract"}}}'
call "describe(finance/invoice-extract)" '{"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"describe_skill","arguments":{"skill_id":"finance/invoice-extract"}}}'

# invoice_extract lives on the finance-tools mount, need a separate session
URL2="https://ca-cowork-mcp.lemonsea-9c8971ad.uksouth.azurecontainerapps.io/api/skills/finance-tools/mcp"
HDR=$(mktemp); BODY=$(mktemp)
curl -s -D "$HDR" -o "$BODY" -H "$H_CT" -H "$H_AC" -X POST "$URL2" -d "$INIT_BODY" > /dev/null
SID2=$(grep -i '^mcp-session-id:' "$HDR" | awk '{print $2}' | tr -d '\r\n')
rm -f "$HDR" "$BODY"
H_SID2="Mcp-Session-Id: $SID2"
curl -s -H "$H_CT" -H "$H_AC" -H "$H_SID2" -X POST "$URL2" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' > /dev/null
out=$(mktemp); t1=$(date +%s%3N)
bytes=$(curl -s -H "$H_CT" -H "$H_AC" -H "$H_SID2" -X POST "$URL2" \
  -d '{"jsonrpc":"2.0","id":10,"method":"tools/call","params":{"name":"invoice_extract","arguments":{"document_url":"https://example.com/invoices/inv-001.pdf"}}}' \
  -w '%{size_download}' -o "$out")
t2=$(date +%s%3N); ms=$((t2 - t1))
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
")
printf '%-46s bytes=%-6s ms=%-5s inner=%s\n' "invoice_extract(...)" "$bytes" "$ms" "${inner:-n/a}"
rm -f "$out"

echo
echo "== G  3 finds in one turn (cost-per-extra-find) ==================="
for tag in meeting.summarise lead.research content.draft; do
  call "find($tag)" "$(printf '{"jsonrpc":"2.0","id":11,"method":"tools/call","params":{"name":"find_skill_by_capability","arguments":{"tag":"%s"}}}' "$tag")"
done

echo
echo "== H  largest describe (upper bound) =============================="
call "describe(content/research-writer)" '{"jsonrpc":"2.0","id":12,"method":"tools/call","params":{"name":"describe_skill","arguments":{"skill_id":"content/research-writer"}}}'
call "describe(finance/invoice-extract-v2)" '{"jsonrpc":"2.0","id":13,"method":"tools/call","params":{"name":"describe_skill","arguments":{"skill_id":"finance/invoice-extract-v2"}}}'
call "describe(dev/skill-creator)" '{"jsonrpc":"2.0","id":14,"method":"tools/call","params":{"name":"describe_skill","arguments":{"skill_id":"dev/skill-creator"}}}'
