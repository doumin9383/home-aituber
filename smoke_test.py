#!/usr/bin/env python3
"""
HomeAITuber 総合スモークテスト
使用法: python3 smoke_test.py <pod_ip>
"""
import asyncio, json, sys, time
import urllib.request

POD_IP = sys.argv[1] if len(sys.argv) > 1 else "10.42.0.99"

passed = 0
failed = 0

def check(name, ok, detail=""):
    global passed, failed
    if ok:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name} — {detail}")
        failed += 1

# ── 1. Static assets ──
print("\n=== 1. STATIC ASSETS ===")
for path, label in [
    ("/", "index.html"),
    ("/assets/main-nu7uwxNJ.js", "main JS"),
    ("/assets/main-QEkl09-0.css", "main CSS"),
    ("/libs/live2dcubismcore.js", "Live2D Cubism Core"),
    ("/live2d-models/mao_pro/runtime/mao_pro.model3.json", "model3.json"),
]:
    try:
        req = urllib.request.Request(f"http://{POD_IP}:12393{path}")
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read()
            check(label, r.status == 200, f"HTTP {r.status}")
            if path == "/":
                html = body.decode()
                check("  inject script", 'JSON.stringify' in html, "missing JSON.stringify")
                check("  wsUrl set", 'wsUrl' in html)
                check("  baseUrl set", 'baseUrl' in html)
                check("  removeItem modelInfo", 'removeItem("modelInfo")' in html)
    except Exception as e:
        check(label, False, str(e))

# ── 2. HTML injection ──
print("\n=== 2. HTML INJECTION ===")
try:
    req = urllib.request.Request(f"http://{POD_IP}:12393/")
    with urllib.request.urlopen(req, timeout=5) as r:
        html = r.read().decode()
        check("JSON.stringify in injection", 'JSON.stringify(' in html)
        check("removeItem modelInfo", 'removeItem("modelInfo")' in html)
        # Count <script> tags — should have 2 injected + 1 module
        script_count = html.count("<script")
        check(f"<script> count ({script_count})", script_count >= 3)
except Exception as e:
    check("fetch index.html", False, str(e))

# ── 3. JS defaults patched ──
print("\n=== 3. JS DEFAULT MODEL GLOBALS ===")
try:
    req = urllib.request.Request(f"http://{POD_IP}:12393/assets/main-nu7uwxNJ.js")
    with urllib.request.urlopen(req, timeout=5) as r:
        js = r.read().decode()
        check('ResourcesPath="/live2d-models/mao_pro/"', 
              '/live2d-models/mao_pro/' in js and 'ResourcesPath=""' not in js)
        check('ModelDir=["runtime"]', 
              'ModelDir=["runtime"]' in js and 'ModelDir=[]' not in js)
        check('ModelFileNames=["mao_pro"]',
              'ModelFileNames=["mao_pro"]' in js and 'ModelFileNames=[]' not in js)
except Exception as e:
    check("fetch main JS", False, str(e))

# ── 4. Conversation timeout patched ──
print("\n=== 4. CONVERSATION TIMEOUT PATCH ===")
try:
    req = urllib.request.Request(f"http://{POD_IP}:12393/")
    with urllib.request.urlopen(req, timeout=5) as r:
        pass
    check("server reachable", True)
    # We can't directly check the Python file via HTTP, but we can verify
    # by running the WebSocket test that sends a message and checks for chain-end
except Exception as e:
    check("server reachable", False, str(e))

# ── 5. Model file accessible via correct path ──
print("\n=== 5. MODEL ASSETS ===")
for path, label in [
    ("/live2d-models/mao_pro/runtime/mao_pro.model3.json", "model3.json"),
    ("/live2d-models/mao_pro/runtime/mao_pro.moc3", "moc3"),
    ("/live2d-models/mao_pro/runtime/mao_pro.4096/texture_00.png", "texture"),
    ("/live2d-models/mao_pro/runtime/mao_pro.physics3.json", "physics"),
    ("/live2d-models/mao_pro/runtime/mao_pro.pose3.json", "pose"),
]:
    try:
        req = urllib.request.Request(f"http://{POD_IP}:12393{path}")
        with urllib.request.urlopen(req, timeout=5) as r:
            check(label, r.status == 200, f"HTTP {r.status}")
    except Exception as e:
        check(label, False, str(e))

# ── 6. WebSocket test ──
print("\n=== 6. WEBSOCKET & CONVERSATION ===")
async def ws_test():
    import websockets
    try:
        async with websockets.connect(f'ws://{POD_IP}:12393/client-ws', ping_timeout=60) as ws:
            chain_ended = False
            have_audio = False
            have_thinking = False
            ndefault_url = False  # 0.0.0.0 not in URLs
            
            for i in range(30):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=20)
                except asyncio.TimeoutError:
                    break
                data = json.loads(msg)
                t = data.get('type', '')
                
                if t == 'set-model-and-conf':
                    uid = data.get('client_uid')
                    await ws.send(json.dumps({
                        'type': 'text-input',
                        'text': 'Say just: はいテスト',
                        'client_uid': uid
                    }))
                elif t == 'full-text':
                    text = data.get('text', '')
                    if 'Thinking' in text:
                        have_thinking = True
                elif t == 'audio':
                    have_audio = True
                elif t == 'control':
                    if data.get('text') == 'conversation-chain-end':
                        chain_ended = True
                        break
            
            return {
                'chain_ended': chain_ended,
                'have_audio': have_audio,
                'have_thinking': have_thinking,
            }
    except Exception as e:
        return {'error': str(e)}

ws_result = asyncio.run(ws_test())
if 'error' in ws_result:
    check("WebSocket connect", False, ws_result['error'])
else:
    check("WebSocket connected", True)
    check("Thinking... received", ws_result.get('have_thinking', False))
    check("Audio response received", ws_result.get('have_audio', False))
    check("conversation-chain-end received", ws_result.get('chain_ended', False))

# ── SUMMARY ──
print(f"\n{'='*50}")
print(f"SMOKE TEST RESULTS: {passed} ✅ / {failed} ❌ / {passed+failed} total")
print(f"{'='*50}")
if failed > 0:
    sys.exit(1)
