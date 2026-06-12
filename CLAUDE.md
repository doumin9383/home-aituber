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
> Mattermost = **control/log window**
> Hermes = **hands**
> AIRI = **future vessel**

## Directory Structure

```
home-aituber/
  ├─ src/open_llm_vtuber/       # Open-LLM-VTuber upstream backend (keep as-is)
  ├─ homeaituber/                # HomeAITuber-specific layer
  │   ├─ radio_prompt_builder.py
  │   ├─ mattermost_adapter.py
  │   ├─ feedback_logger.py
  │   ├─ memory_worker.py
  │   └─ audio_only_frontend/
  ├─ soul/                       # Local state directory (identity, memory, weights)
  │   ├─ identity.md
  │   ├─ user_profile.json
  │   ├─ topic_weights.json
  │   ├─ learning_state.json
  │   ├─ review_queue.json
  │   ├─ dream_journal.jsonl
  │   ├─ daily_cache.md
  │   └─ feedback_log.jsonl
  ├─ characters/                 # Character configs (Open-LLM-VTuber)
  ├─ config_templates/           # Default configs
  ├─ chat_history/               # Conversation logs
  └─ SPEC.md                     # Full specification
```

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
  "safety": { "uses_private_data": false, "requires_external_access": false }
}
```

### Privacy doctrine
- WAN exposure disabled by default
- No filesystem-wide read access
- No browser history / credential scanning
- Allowed dirs by default: `./soul`, `./chat_history`, `./cache`, `./config`

## Essential Commands

- **Install deps**: `uv sync`
- **Run server**: `uv run run_server.py`
- **Lint**: `ruff check .`
- **Format**: `ruff format .`

## Upstream Information

Open-LLM-VTuber is at v1 (v2 rewrite in planning). The following components are provided by upstream and should be preserved:
- `src/open_llm_vtuber/` — all backend code (ASR, TTS, VAD, WebSocket, config, conversations)
- `characters/` — character YAML definitions
- `avatars/`, `backgrounds/`, `live2d-models/` — visual assets
- `frontend/` — web UI (git submodule)
- `run_server.py` — entry point

HomeAITuber additions go into `homeaituber/` and `soul/` directories — **never modify upstream files unless absolutely necessary for integration hooks**.
