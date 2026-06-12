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
  <a href="./SPEC.md">📖 Specification</a>
  ·
  <a href="#-quick-start">🚀 Quick Start</a>
  ·
  <a href="#-architecture">🏗️ Architecture</a>
  ·
  <a href="#-phases">📋 Phases</a>
</p>

---

**HomeAITuber** is a local-first, audio-first personal AITuber that lives inside the user's home network, speaks in a cute voice, remembers preferences, and turns interesting topics into English-Japanese radio.

> 英語嫌いでも続く、自分専用の英日AIラジオ相棒

HomeAITuber is **not** a public VTuber, not a cloud assistant, and not a surveillance agent. It is a private AITuber companion for your `$HOME`, homelab, or LAN.

---

## 🔄 Project Status

HomeAITuber v0 is currently in **Phase 0** (Fork & Rename).

See [SPEC.md](./SPEC.md) for the full implementation plan.

## 🧬 Fork Base

HomeAITuber is a fork of **[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)**, which provides:

- WebSocket backend
- ASR (speech recognition)
- TTS (text-to-speech)
- VAD (voice activity detection)
- Live2D / visual frontend support
- Character configuration & persona prompts
- Chat history persistence
- Proactive speaking & agent interface

HomeAITuber adds the **private household layer**:
- 🎙️ Audio-first radio mode (EN→JP→EN_REPEAT)
- 💾 Local soul state (`soul/` directory)
- 🤖 Mattermost adapter for control & logging
- 📝 Feedback logging (like / skip / boring / save_phrase)
- 🌙 Background memory worker (Dream Mode)
- 🔒 LAN-only deployment & privacy doctrine

## 🎯 Core Principles

| Principle | Description |
|---|---|
| **Local-first** | Everything runs inside your LAN. No cloud dependency. |
| **Audio-first** | Radio mode is the primary interface. Visual is optional. |
| **Privacy by default** | No WAN exposure, no filesystem scanning, no surveillance. |
| **Light hot path** | Full memory scan and tool execution never block real-time conversation. |
| **Personality > Productivity** | Cute, chaotic, funny — not a corporate assistant. |

## 🚀 Quick Start

```bash
# Clone the repository
git clone https://github.com/doumin9383/home-aituber.git
cd home-aituber

# Install dependencies
uv sync

# Run the server (Open-LLM-VTuber backend)
uv run run_server.py
```

> **Note:** HomeAITuber v0 is under active development. Radio mode, Mattermost integration, and the soul layer are being built incrementally. See [SPEC.md](./SPEC.md) for the current phase.

## 🏗️ Architecture

```
HomeAITuber
  ├─ Open-LLM-VTuber backend (body)
  │   ├─ ASR, TTS, VAD
  │   ├─ WebSocket
  │   ├─ character config
  │   └─ proactive speak
  │
  ├─ homeaituber layer
  │   ├─ radio_prompt_builder.py
  │   ├─ soul/ (identity, memory, state)
  │   ├─ mattermost_adapter.py
  │   ├─ feedback_logger.py
  │   ├─ memory_worker.py
  │   └─ audio_only_frontend/
  │
  └─ future integrations
      ├─ Hermes bridge
      ├─ MCP
      └─ AIRI migration adapter
```

## 📋 Implementation Phases

| Phase | What | Status |
|---|---|---|
| **0** | Fork & rename, README, project concept | 🟡 In progress |
| **1** | Radio mode (prompt builder, structured output) | ⬜ Not started |
| **2** | Soul directory (identity, profile, weights) | ⬜ Not started |
| **3** | Mattermost adapter (commands, transcript, feedback) | ⬜ Not started |
| **4** | Memory worker (Dream Mode, consolidation) | ⬜ Not started |
| **5** | k3s manifests (deploy, PVC, CronJob) | ⬜ Not started |

## 🔒 Privacy

HomeAITuber is designed to be **private by default**:

- ❌ No WAN exposure by default
- ❌ No filesystem-wide read access
- ❌ No browser history reading
- ❌ No autonomous Hermes/tool execution in v0
- ✅ LAN-only operation
- ✅ Access to `soul/`, `chat_history/`, `cache/`, `config/` only
- ✅ User controls what the system sees and does

## 📜 License

This project is a fork of [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) and is distributed under the same license terms. See [LICENSE](./LICENSE) for details.

---

<p align="center">
  <sub>HomeAITuber belongs to your home network. It must not invite itself outside.</sub>
</p>
