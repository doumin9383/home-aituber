# HomeAITuber v0 Specification

## 1. Project Identity

- **Repository name**: `homeaituber`
- **Display name**: HomeAITuber
- **Japanese subtitle**: 逸汎の誤家庭向け常駐AITuber
- **English tagline**: A local-first personal AITuber for ordinary households with unusually capable home AI appliances.
- **One-line concept**: HomeAITuber is a local-first, audio-first personal AITuber that lives inside the user's home network, speaks in a cute voice, remembers preferences, and turns interesting topics into English-Japanese radio.

---

## 2. Core Concept

HomeAITuber is **not** a public VTuber, not a cloud assistant, and not a surveillance agent.

It is a private AITuber companion for a user's `$HOME`, homelab, or LAN.

**The first goal is not productivity.**
**The first goal is:**

> 英語嫌いでも続く、自分専用の英日AIラジオ相棒

HomeAITuber should feel like:

- 夢見る隣のAITuberちゃん。ただし隣どころか `$HOME` に常駐している。
- 深夜に記憶を整理して、翌日ちょっとだけ賢くなる。
- 英語嫌いのユーザーに、面白い話だけ英日ラジオで流す。
- ユーザーの生活には寄り添うが、見てはいけないものは見ない。

---

## 3. Target Environment

### Runtime
```yaml
runtime:
  default: single-node home AI appliance
  optional: k3s
  network_scope: LAN only
```

### Hardware Target
```yaml
hardware_target:
  class: home AI appliance
  examples:
    - NVIDIA DGX Spark class machine
    - AMD Strix Halo / Ryzen AI Max class machine
    - Apple Silicon Mac with large unified memory
    - existing homelab GPU node
    - small private k3s cluster
```

### Deployment Assumption

HomeAITuber assumes the user may have:
- LAN-only services
- k3s at home
- Mattermost already running
- local LLM runtime
- local or self-hosted TTS
- no public port exposure
- no family-facing UI by default

---

## 4. Fork Base

HomeAITuber v0 is a fork of: **Open-LLM-VTuber**

### Open-LLM-VTuber provides (body):
- WebSocket backend
- ASR
- TTS
- VAD
- Live2D / visual frontend support
- character configuration
- persona prompt
- chat history
- proactive speaking
- agent interface

### HomeAITuber adds (private household layer):
- audio-first radio mode
- EN → JP → EN_REPEAT output style
- local soul state (soul/)
- Mattermost adapter
- feedback logging
- background memory worker
- LAN-only deployment assumptions
- privacy doctrine

---

## 5. Product Scope

### v0 Goal

Build a working local personal AITuber that can:
1. Run inside the user's LAN
2. Speak through local audio
3. Generate short bilingual radio segments
4. Use user taste and lightweight memory
5. Post transcripts to Mattermost
6. Accept feedback such as like / skip / boring / save phrase
7. Avoid external exposure by default

### v0 Non-goals

HomeAITuber v0 does **not** attempt to:
- become a general AI secretary
- browse the whole filesystem
- operate the user's PC freely
- expose itself to WAN
- stream publicly to YouTube or Twitch
- manage family-facing accounts
- become a full AIRI replacement
- implement complex autonomous agents in the hot path
- read private/media/financial directories by default

---

## 6. Personality Direction

**HomeAITuber should be:**
- cute
- lightly chaotic
- private
- loyal to the user
- funny rather than educational
- English-learning aware but not textbook-like
- proactive but not needy
- local-first and privacy-aware

**HomeAITuber should NOT sound like:**
- a school teacher
- a productivity coach
- a corporate assistant
- a public livestreamer
- a surveillance system
- a generic chatbot

### Radio Host Style
- **Bad**: "Today, let's learn the phrase..."
- **Good**: "EN: Productivity apps are basically digital amulets for people who fear their own inbox. JP: 生産性アプリって、結局「受信箱が怖い人向けのデジタルお守り」なんだよな。EN_REPEAT: Productivity apps are basically digital amulets for people who fear their own inbox. NOTE: 'basically' は「要するに」「ほぼ」みたいな軽い断定で便利。"

---

## 7. Modes

### 7.1 Radio Mode (Primary)

Periodically or manually generates a short bilingual segment.

**Segment Format:**
```yaml
en: "Short natural English sentence"
jp: "Natural Japanese translation"
en_repeat: "Same or slightly slower English sentence"
phrase: "One useful expression"
note: "Short Japanese explanation"
```

**Playback Order:**
1. English
2. *(short pause)*
3. Japanese translation
4. *(short pause)*
5. English repeat
6. Phrase/note if useful

**Constraints:**
- short enough for passive listening
- one useful phrase per segment maximum
- no textbook tone
- no forced quizzes in v0
- no long lectures
- prefer topics the user already likes

### 7.2 Chat Mode

User can talk or type to HomeAITuber.

**Inputs:**
- microphone
- local web frontend
- Mattermost message

**Outputs:**
- local TTS audio
- local subtitles/log
- optional Mattermost transcript

### 7.3 Visual Mode

Supported but **not required** for v0 completion.

May use:
- existing Open-LLM-VTuber frontend
- Live2D model
- minimal avatar page
- subtitle-only local web UI

v0 may be audio-first, but should remain visual-compatible.

### 7.4 Dream Mode

Background memory consolidation process. Runs outside the hot path.

**Schedule:** daily, late night

**Responsibilities:**
- read feedback_log.jsonl
- read recent transcripts
- update user_profile.json
- update topic_weights.json
- update learning_state.json
- update daily_cache.md
- append dream_journal.jsonl

**Framing:** 深夜のメモリ整理 — not autonomous spying.

---

## 8. Architecture

### 8.1 High-level

```
HomeAITuber
  ├─ Open-LLM-VTuber backend
  │   ├─ ASR, TTS, VAD
  │   ├─ WebSocket
  │   ├─ character config
  │   └─ proactive speak
  │
  ├─ homeaituber layer
  │   ├─ radio_prompt_builder.py
  │   ├─ soul/
  │   ├─ mattermost_adapter.py
  │   ├─ feedback_logger.py
  │   ├─ memory_worker.py
  │   └─ audio_only_frontend/
  │
  └─ optional future integrations
      ├─ Hermes
      ├─ MCP
      ├─ AIRI migration adapter
      └─ stream publisher
```

### 8.2 Hot Path (must stay fast)
```
radio tick / user input
  → persona + daily_cache + recent context
  → Speaker LLM
  → TTS
  → local playback
```

**Must NOT require:** full memory scan, Hermes, tool execution, filesystem search, long RAG query, heavy personalization model.

### 8.3 Background Path
```
chat history / transcript / feedback
  → memory_worker
  → soul updates
  → daily_cache.md
  → next day's hot path
```

---

## 9. Soul Layer

Small local state directory at `soul/`:

### Files
| File | Purpose |
|---|---|
| `identity.md` | Who HomeAITuber is (name, tone, style, privacy rules) |
| `user_profile.json` | Stable user preferences (name, likes, dislikes) |
| `topic_weights.json` | Topic interest scores for radio curation |
| `learning_state.json` | English-learning state (level, known/weak phrases) |
| `review_queue.json` | Tiny list of phrases to reuse (max 3 in hot path) |
| `dream_journal.jsonl` | Append-only log of memory consolidation |
| `daily_cache.md` | Small compressed state injected into every radio prompt |
| `feedback_log.jsonl` | Raw feedback event log |

### 9.1 identity.md
- name
- tone
- relationship to user
- speaking style
- privacy rules
- English radio style
- forbidden behaviors

### 9.2 user_profile.json
```json
{
  "user_name": "Shuto",
  "likes": ["homelab", "AI", "weird internet culture", "local-first tools"],
  "dislikes": ["textbook English", "corporate productivity tone"],
  "privacy_preferences": {
    "wan_exposure": false,
    "filesystem_default_access": "deny",
    "family_visible": false
  }
}
```

### 9.3 topic_weights.json
```json
{
  "homelab": 0.95,
  "local_ai": 0.95,
  "aituber": 0.9,
  "language_learning": 0.7,
  "generic_news": 0.2
}
```

### 9.4 learning_state.json
```json
{
  "mode": "passive_radio",
  "level": "unknown_initial",
  "known_phrases": [],
  "weak_phrases": [],
  "annoying_patterns": ["forced quizzes", "too much grammar"],
  "preferred_explanation_language": "ja"
}
```

---

## 10. Mattermost Integration

Mattermost = **operation and log window.** Not the soul.

### Responsibilities
- post radio transcript
- receive feedback
- receive simple commands
- optionally trigger radio tick
- optionally forward explicit task requests to Hermes

### v0 Commands
```
/aituber radio
/aituber like
/aituber skip
/aituber too_easy
/aituber too_boring
/aituber save_phrase
/aituber status
```

### Feedback Event Format
```json
{
  "timestamp": "ISO-8601",
  "source": "mattermost",
  "event": "like",
  "segment_id": "radio-2026-06-11-001",
  "note": ""
}
```

---

## 11. Privacy Doctrine

**Hard rules:**
- WAN exposure is disabled by default
- LAN only by default
- no public streaming by default
- no family-facing UI by default
- no filesystem-wide read access
- no automatic reading of private/media/financial/credential directories
- no browser history reading
- no secret scanning unless explicitly requested
- no autonomous Hermes/tool execution in v0

**Filesystem access default:**
```yaml
filesystem_access:
  default: deny
  allowed_dirs:
    - ./soul
    - ./chat_history
    - ./cache
    - ./config
```

**Explicitly denied:** Downloads, Desktop, Documents, Pictures, Videos, browser profiles, password stores, financial records, private media, arbitrary home directory scan.

**Network:**
```yaml
network:
  bind: 0.0.0.0 inside LAN or cluster only
  ingress: LAN only
  public_exposure: false
  tls: recommended for LAN
```

---

## 12. k3s Deployment

- **Namespace:** `homeaituber`
- **Components:** backend, frontend, mattermost-adapter, memory-worker (CronJob), PVC
- **Services:** ClusterIP
- **Ingress:** `homeaituber.local`, LAN only

---

## 13. Model Roles

- **Speaker model:** Fast radio/chat generation, low latency, good JA/EN, personality adherence
- **Personalizer model:** Background memory consolidation, slower OK, never blocks hot path
- **Hermes (tool agent):** Explicit task execution only, NOT in normal radio/chat path (v0 rule)

---

## 14. Radio Prompt Builder

**File:** `homeaituber/radio_prompt_builder.py`

**Inputs:** identity.md, daily_cache.md, topic_weights.json, review_queue.json, current mode, optional user command

**Output:** Compact prompt instructing model to produce EN→JP→EN_REPEAT segment — short, one phrase max, no textbook tone, match user interests, avoid sensitive/private topics.

---

## 15. Required Output Schema

```json
{
  "segment_id": "radio-YYYYMMDD-HHMMSS",
  "en": "...",
  "jp": "...",
  "en_repeat": "...",
  "phrase": "...",
  "note": "...",
  "topic": "...",
  "safety": {
    "uses_private_data": false,
    "requires_external_access": false
  }
}
```

---

## 16. Implementation Plan

### Phase 0: Fork and rename
- fork Open-LLM-VTuber → rename to `homeaituber`
- add README, project concept
- keep upstream structure

### Phase 1: Radio mode
- `radio_prompt_builder.py`
- extend ai-speak-signal with `mode=radio`
- structured EN/JP/EN_REPEAT output → existing TTS path

### Phase 2: Soul directory
- default soul/ files
- daily_cache.md / topic_weights.json / review_queue.json loading
- keep hot path small

### Phase 3: Mattermost adapter
- incoming command endpoint
- transcript posting
- feedback logging
- commands: like / skip / too_easy / too_boring / save_phrase

### Phase 4: Memory worker
- `memory_worker.py`
- summarize feedback → update topic weights, review queue
- write dream_journal.jsonl
- regenerate daily_cache.md

### Phase 5: k3s manifests
- deploy/k3s/ namespace, deployments, PVC, CronJob, ingress

---

## 17. Acceptance Criteria (v0 done when:)

1. Fork boots locally
2. Backend generates a radio segment
3. Segment follows EN→JP→EN_REPEAT format
4. Segment is spoken through TTS
5. Transcript posted to Mattermost
6. Feedback saved to feedback_log.jsonl
7. soul/daily_cache.md loaded into radio generation
8. memory_worker can update at least one soul file from feedback
9. Service runs LAN-only
10. No Hermes/tool execution required for normal radio mode

---

## 18. Design Principle

> Open-LLM-VTuber = **body**
> soul/ = **continuity**
> Mattermost = **control/log window**
> Hermes = **hands**
> AIRI = **future vessel**
>
> The project must remain local-first.
> The user may invite HomeAITuber into the home network.
> HomeAITuber must not invite itself outside.
