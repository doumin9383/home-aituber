<p align="center">
  <img src="./assets/banner.jpg" alt="HomeAITuber" />
</p>

<h1 align="center">HomeAITuber</h1>
<h3 align="center">
  逸汎の誤家庭向け常駐AITuber
  <br/>
  <em>A local-first personal AITuber for ordinary households with unusually capable home AI appliances.</em>
</h3>

<p align="center">
  <a href="./README.JP.md">日本語</a>
  ·
  <a href="./SPEC.md">📖 Specification</a>
  ·
  <a href="#-quick-start">🚀 Quick Start</a>
  ·
  <a href="#-what-it-does">✨ What It Does</a>
</p>

---

**HomeAITuber** is a local-first, audio-first personal AITuber that lives inside your home network, speaks in a cute voice, remembers preferences, and turns interesting topics into English-Japanese radio segments.

> 英語嫌いでも続く、自分専用の英日AIラジオ相棒
> *Your private EN/JP AI radio buddy — even if you hate English.*

---

## 🔄 Project Status

**v0 — Running on k3s, actively used daily.**

| Component | Status |
|-----------|:------:|
| Live2D (mao_pro) | ✅ |
| ASR (SenseVoice multilingual) | ✅ |
| TTS (edge_tts, wired to radio) | ✅ |
| Chat (EN/JP bilingual) | ✅ |
| Radio auto-tick (10min interval) | ✅ |
| Radio manual fire (mood selectable) | ✅ |
| Mobile control panel | ✅ |
| Soul directory (identity, weights, cache) | ✅ |
| Memory worker (code ready) | ⚠️ |
| Mattermost adapter | ⬜ |

See [CLAUDE.md](./CLAUDE.md) for detailed implementation status.

## 🧬 Fork Base

HomeAITuber is a fork of **[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)** (v1.2.1), which provides the body layer:

- WebSocket backend, ASR, TTS, VAD
- Live2D / visual frontend
- Character configuration & persona prompts
- Chat history persistence
- Proactive speaking & agent interface

HomeAITuber adds the **private household layer**:

| Layer | What |
|-------|------|
| 🎙️ **Radio mode** | Periodic EN→JP→EN_REPEAT segments, LLM-generated, TTS-spoken |
| 💾 **Soul directory** | Local state: identity, user profile, topic weights, review queue, daily cache |
| 🖥️ **Control panel** | Mobile-first bottom sheet: Live2D toggle, radio fire, mood select, segment history |
| 🧠 **Memory worker** | Feedback → topic reinforcement → dream journal → daily cache regen |
| 🔒 **Privacy doctrine** | LAN-only, no WAN, no filesystem scan, no surveillance |

## ✨ What It Does

**Radio Mode** — the primary interface.

1. Every 10 minutes (or on manual trigger), the engine builds a prompt from your soul preferences
2. The LLM generates a structured EN→JP→EN_REPEAT segment with a useful phrase
3. TTS speaks each part sequentially through edge_tts (multilingual voice)
4. The segment appears as an overlay on the frontend
5. Audio plays through your device speakers

**Control Panel** — `http://<your-host>:30787/`

- 🖼️ **Live2D ON/OFF** — toggle graphics for battery saving
- 📻 **Radio fire** — manual trigger with mood selector (auto / chaotic / chill / brisk / thoughtful)
- 📜 **Segment history** — last 5 radio segments with EN/JP preview
- ● **Connection status** — live WebSocket indicator
- Collapsible bottom sheet, mobile-optimized

## 🎯 Core Principles

| Principle | Description |
|-----------|-------------|
| **Local-first** | Everything runs inside your LAN. No cloud dependency. |
| **Audio-first** | Radio mode is the primary interface. Visual is optional. |
| **Privacy by default** | No WAN exposure, no filesystem scanning, no surveillance. |
| **Light hot path** | Full memory scan and tool execution never block real-time conversation. |
| **Personality > Productivity** | Cute, chaotic, funny — not a corporate assistant. |

## 🚀 Quick Start

```bash
# Clone
git clone --recurse-submodules https://github.com/doumin9383/home-aituber.git
cd home-aituber

# Install deps
uv sync

# Configure
cp config_templates/conf.default.yaml conf.yaml
# Edit conf.yaml — set LLM endpoint, TTS voice, Live2D model

# Run
uv run run_server.py
# → http://localhost:12393
```

### k3s Deployment

```bash
kubectl apply -n agent-build -f deploy/k8s/homeaituber.yaml
```

See [CLAUDE.md](./CLAUDE.md) §Deployment Notes for the full workflow.

## 🏗️ Architecture

```
HomeAITuber
  ├─ Open-LLM-VTuber backend (body)
  │   ├─ ASR, TTS, VAD
  │   ├─ WebSocket (/client-ws)
  │   ├─ character config
  │   └─ proactive speak
  │
  ├─ homeaituber layer
  │   ├─ radio_prompt_builder.py   → soul → LLM prompt
  │   ├─ radio_tick.py             → tick loop + TTS playback
  │   ├─ server_integration.py     → /radio-ws, /api/feedback, TTS wiring
  │   ├─ memory_worker.py          → feedback → soul consolidation
  │   └─ feedback_logger.py
  │
  ├─ deploy/k8s/
  │   ├─ homeaituber.yaml          → Deployment + ConfigMap + PVC
  │   └─ frontend-index-template.html  → custom frontend injection
  │
  └─ future integrations
      ├─ Hermes bridge
      └─ AIRI migration adapter
```

## 📋 Implementation Phases

| Phase | What | Status |
|-------|------|:------:|
| **0** | Fork + rename + SPEC | ✅ |
| **1** | Radio mode (prompt builder, structured output, TTS) | ✅ |
| **2** | Soul directory (identity, profile, weights) | ✅ |
| **3** | Mattermost adapter | ⬜ |
| **4** | Memory worker (feedback → soul learning) | ⚠️ code ready |
| **5** | k3s deployment | ✅ |

## 🔒 Privacy

HomeAITuber is designed to be **private by default**:

- ❌ No WAN exposure
- ❌ No filesystem-wide read access
- ❌ No browser history reading
- ❌ No autonomous tool execution in v0
- ✅ LAN-only operation
- ✅ Access to `soul/`, `chat_history/`, `cache/`, `config/` only
- ✅ User controls what the system sees and does

## 📜 License

This project is a fork of [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) and is distributed under the same license terms. See [LICENSE](./LICENSE) for details.

Live2D sample models are provided under [Live2D Free Material License](https://www.live2d.jp/en/terms/live2d-free-material-license-agreement/).

---

<p align="center">
  <sub>HomeAITuber belongs to your home network. It must not invite itself outside.</sub>
</p>
