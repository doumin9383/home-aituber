# CLAUDE.md

This file provides guidance to Claude Code / AI assistants when working on HomeAITuber.

## Project Identity

HomeAITuber is a fork of **Open-LLM-VTuber** with a private household layer added.

- **Repository**: `doumin9383/home-aituber`
- **Upstream**: `Open-LLM-VTuber/Open-LLM-VTuber`
- **Display name**: HomeAITuber
- **Subtitle**: 逸汎の誤家庭向け常駐AITuber
- **Tagline**: A local-first personal AITuber for ordinary households
- **Specification**: See [SPEC.md](./SPEC.md) for full design document

## Core Architecture Principle

> Open-LLM-VTuber = **body**
> soul/ = **continuity**
> Frontend Web UI = **control/log window**
> Hermes = **hands**
> AIRI = **future vessel**

## Directory Structure

```
home-aituber/
  ├─ src/open_llm_vtuber/       # Open-LLM-VTuber upstream backend (keep as-is)
  ├─ homeaituber/                # HomeAITuber-specific layer
  │   ├─ radio_prompt_builder.py  # Soul → LLM prompt construction
  │   ├─ radio_tick.py            # Periodic segment generation + TTS playback
  │   ├─ server_integration.py    # FastAPI hooks: /radio-ws, /api/feedback, TTS wiring
  │   ├─ memory_worker.py         # Comment → feedback → soul learning
  │   └─ feedback_logger.py       # Feedback event I/O
  ├─ soul/                       # Local state directory (identity, memory, weights)
  ├─ deploy/k8s/                 # k3s deployment manifests
  │   └─ homeaituber.yaml         # Deployment + ConfigMap + PVC + RoleBinding
  ├─ frontend/ (submodule → doumin9383/Open-LLM-VTuber-Web, gh-pages-build)
  │   ├─ index.html               # Built React app (includes HA panel)
  │   ├─ assets/                  # JS/CSS bundles
  │   └─ libs/                    # Live2D + VAD wasm/onnx
  ├─ characters/                 # Character configs
  ├─ config_templates/           # Default configs
  ├─ chat_history/               # Conversation logs
  └─ SPEC.md                     # Full specification
```

## Frontend Architecture (v2)

The frontend is a forked and built version of `Open-LLM-VTuber-Web` (React/TypeScript/Vite/ChakraUI).
Source: `doumin9383/Open-LLM-VTuber-Web` (main branch)
Built output: `gh-pages-build` branch, served via git submodule.

### Custom additions (in `src/renderer/src/`):
- `components/homeaituber/HomeAITuberPanel.tsx` — HA controls in sidebar
- `hooks/homeaituber/use-radio-ws.ts` — Radio WebSocket hook
- Sidebar integration in `components/sidebar/sidebar.tsx`

### Build workflow:
```bash
cd /opt/data/home-aituber-web-src
npm install
npm run build:web              # → dist/web/
git checkout gh-pages-build
cp -r dist/web/* .
git commit && git push
```
Then update submodule in home-aituber:
```bash
cd /opt/data/home-aituber/frontend
git fetch origin gh-pages-build
git checkout origin/gh-pages-build
cd .. && git add frontend && git commit
```

## Implementation Status

### ✅ Complete

| Phase | What | Key Files |
|:-----:|:-----|:----------|
| **0** | Fork + rename + SPEC + directory layout | `SPEC.md`, `soul/`, `homeaituber/` |
| **1** | Radio mode core — prompt builder, tick engine, EN→JP→EN_REPEAT | `radio_prompt_builder.py`, `radio_tick.py` |
| **2** | Soul directory — 8 files, identity, weights, review queue | `soul/*` |
| **3** | *(skipped)* Mattermost adapter — deprioritized, via Hermes instead | — |
| **4** | Memory worker — feedback pipeline (code ready, needs Phase 3 feedback) | `memory_worker.py` |
| **5** | k3s deployment — Running in `agent-build` namespace, Tailscale-accessible | `deploy/k8s/homeaituber.yaml` |

### Completed Integration Steps

| Step | What | Files |
|:----:|:-----|:------|
| A | Frontend submodule init | `frontend/` (Open-LLM-VTuber-Web) |
| B | Graphics toggle + branding | `frontend/index.html` (injected JS via template) |
| C | Memory worker pipeline | `memory_worker.py`, `feedback_logger.py` |
| D | Radio → WS notify + chat capture | `server_integration.py`, `/radio-ws`, `/api/feedback` |
| E | **TTS wiring** — radio segments → edge_tts → audio WS → frontend playback | `server_integration.py:_tts_callback`, `run_server.py:set_tts_engine()` |
| F | **Mobile control panel v3** — Live2D toggle, radio fire, mood select, history, state machine | `deploy/k8s/frontend-index-template.html` |

### Current Capabilities

- **Live2D**: `mao_pro` model displayed, toggleable via 🖼️ button
- **ASR**: SenseVoice (zh/en/ja/ko/yue multilingual), waiting for mic input
- **TTS**: edge_tts with `en-US-AvaMultilingualNeural`, wired into radio playback
- **Chat**: Bilingual EN/JP conversation via chat input on the frontend
- **Radio (auto)**: Fires every 10 minutes, generates EN→JP→EN_REPEAT segment, plays via TTS
- **Radio (manual)**: 📻 button on control panel, mood selectable, state-aware (debounce + interrupt)
- **Frontend Panel**: Collapsible bottom sheet, mobile-first, sequential audio queue, segment history

### ⬜ Remaining (SPEC v0)

- **Phase 3**: Mattermost adapter — `/aituber` commands, transcript posting, feedback (deprioritized)
- **Acceptance criteria #5, #6**: Transcript to Mattermost, feedback_log.jsonl populated

## Frontend Template Machinery

The frontend (`deploy/k8s/frontend-index-template.html`) is injected on top of the upstream `Open-LLM-VTuber-Web` submodule during init. It:

1. Replaces the vanilla `index.html` with a custom template
2. Sets `localStorage` WS/base URL dynamically via `window.location` (with `JSON.stringify` — critical!)
3. Injects a **control panel** as a fixed bottom sheet:
   - Live2D ON/OFF toggle
   - Radio manual fire with mood selector
   - Segment history (last 5)
   - Connection status indicator
   - Collapsible on mobile (collapsed by default in portrait)
4. Connects to `/radio-ws` for radio segments + audio playback
5. Audio playback is queued sequentially (prevents overlapping)
6. Radio state machine: `idle` → `generating` (debounce) → `playing` (interruptible) → `idle`
7. Intercepts chat WebSocket to forward user messages as radio comments
8. `visibilitychange` — reconnects on tab wake (mobile battery optimization)

## Deployment Notes

- **Namespace**: `agent-build`
- **Pod name**: `homeaituber-*`
- **External access**: `http://100.81.16.52:30787/` (Tailscale NodePort)
- **Internal**: `http://<pod-ip>:12393/`
- **LLM backend**: Atlas Gemma-4-26B at `http://100.89.160.90:30099/v1`
- **Memory limit**: 16Gi (raised from 8Gi to prevent OOM during `uv sync` + CUDA downloads)
- **SA**: `hermes-open-llm-vtuber` (limited: can patch deployments/configmaps, read pods/logs, cannot create Services or delete pods)

### Deployment update workflow

1. Push changes to `doumin9383/home-aituber` main branch
2. `kubectl apply -n agent-build -f deploy/k8s/homeaituber.yaml` (only needed if Deployment spec/manifest changed)
3. `kubectl -n agent-build patch deployment homeaituber -p '{"spec":{"template":{"metadata":{"annotations":{"restartedAt":"<ISO8601>"}}}}}'`
4. Init script does `git reset --hard origin/main`, copies template, patches JS URLs, starts server
5. First boot takes 2-5 minutes (`uv sync` + CUDA downloads); subsequent boots ~30s (PVC + tmpfs venv)

⚠️ `patch deployment restartedAt` only restarts the pod — does NOT update the init script. For spec changes, `kubectl apply` first, then restart.

## Key Development Rules

### Hot path must stay fast
Radio tick / user input → persona + daily_cache → Speaker LLM → TTS → playback
Must NOT require: full memory scan, Hermes, tool execution, filesystem search, RAG.

### Radio output format (Phase 1+)
```json
{
  "segment_id": "radio-YYYYMMDD-HHMMSS",
  "en": "English sentence",
  "jp": "日本語訳",
  "en_repeat": "Same English (slightly slower)",
  "phrase": "One useful expression",
  "note": "Short Japanese explanation",
  "topic": "...",
  "mood": "brisk|chaotic|chill|thoughtful",
  "safety": { "uses_private_data": false, "requires_external_access": false }
}
```

### TTS pipeline
```
RadioTickEngine._tick()
  → generate_segment() → LLM → JSON parse → RadioSegment
  → _playback_segment() → for each speak part:
      tts_callback(text, lang) → TTSInterface.async_generate_audio(text)
      → prepare_audio_payload() → base64 WAV
      → _broadcast_audio() → /radio-ws WS clients
      → frontend playRadioAudio() → Blob → Audio.play() (queued sequential)
  → _notify_callback() → _broadcast_segment() → frontend overlay
```

### Privacy doctrine
- WAN exposure disabled by default
- No filesystem-wide read access
- No browser history / credential scanning
- Allowed dirs by default: `./soul`, `./chat_history`, `./cache`, `./config`

## Essential Commands

- **Install deps**: `uv sync`
- **Run server**: `uv run run_server.py`
- **Run radio tick CLI test**: `uv run python -m homeaituber.radio_tick --mood brisk`
- **Lint**: `ruff check .`
- **Format**: `ruff format .`

## Upstream Information

Open-LLM-VTuber is at v1 (v2 rewrite in planning). The following components are provided by upstream and should be preserved:
- `src/open_llm_vtuber/` — all backend code (ASR, TTS, VAD, WebSocket, config, conversations)
- `characters/` — character YAML definitions
- `avatars/`, `backgrounds/`, `live2d-models/` — visual assets
- `frontend/` — web UI (git submodule)
- `run_server.py` — entry point

HomeAITuber additions go into `homeaituber/`, `soul/`, and `deploy/` directories — **never modify upstream files unless absolutely necessary for integration hooks**.
The two exceptions are:
- `run_server.py` — minimal hook for `RadioServerIntegration` setup + `set_tts_engine()` call
- `deploy/k8s/frontend-index-template.html` — replaces upstream `frontend/index.html` at deploy time
