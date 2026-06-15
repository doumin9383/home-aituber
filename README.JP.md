<p align="center">
  <img src="./assets/banner.jpg" alt="HomeAITuber" />
</p>

<h1 align="center">HomeAITuber</h1>
<h3 align="center">
  逸汎の誤家庭向け常駐AITuber
  <br/>
  <em>ちょっと変わった家庭用AIサーバーに住み着く、ローカル最優先の個人AITuber</em>
</h3>

<p align="center">
  <a href="./README.md">English</a>
  ·
  <a href="./SPEC.md">📖 仕様書</a>
  ·
  <a href="#-クイックスタート">🚀 クイックスタート</a>
  ·
  <a href="#-できること">✨ できること</a>
</p>

---

**HomeAITuber** は、LANの中で動く個人専用AITuberです。かわいい声で話し、好みを覚え、面白い話題を英日ラジオに変えてくれます。

> 英語嫌いでも続く、自分専用の英日AIラジオ相棒

クラウドアシスタントでも、監視エージェントでも、配信者でもありません。あなたの `$HOME` やホームラボに住む、プライベートな相棒です。

---

## 🔄 開発状況

**v0 — k3s上で稼働中、毎日使用中。**

| 機能 | 状態 |
|------|:----:|
| Live2D（mao_pro） | ✅ |
| 音声認識（SenseVoice 日中英韓粤） | ✅ |
| 音声合成（edge_tts、ラジオに配線済み） | ✅ |
| チャット（英日バイリンガル） | ✅ |
| ラジオ自動配信（10分間隔） | ✅ |
| ラジオ手動発火（ムード選択可） | ✅ |
| モバイル操作パネル | ✅ |
| Soulディレクトリ（人格・嗜好・キャッシュ） | ✅ |
| Memory worker（コード実装済み） | ⚠️ |
| Mattermost連携 | ⬜ |

詳細な実装状況は [CLAUDE.md](./CLAUDE.md) を参照。

## 🧬 フォーク元

HomeAITuber は **[Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber)** (v1.2.1) のフォークです。

**Open-LLM-VTuber が提供するもの（身体）：**
- WebSocket バックエンド
- 音声認識（ASR）・音声合成（TTS）・発話検出（VAD）
- Live2D フロントエンド
- キャラクター設定・ペルソナプロンプト
- チャット履歴の永続化
- 能動発話・エージェントインターフェース

**HomeAITuber が追加するもの（家庭レイヤー）：**

| レイヤー | 内容 |
|----------|------|
| 🎙️ **ラジオモード** | 定期/手動で EN→JP→EN_REPEAT の英日ラジオを生成・音声再生 |
| 💾 **Soulディレクトリ** | 人格・ユーザープロフィール・話題嗜好・復習キュー・日次キャッシュ |
| 🖥️ **操作パネル** | モバイル対応ボトムシート：Live2D切替・ラジオ発火・ムード選択・履歴 |
| 🧠 **Memory worker** | フィードバック → 話題強化 → 夢日記 → 日次キャッシュ再生成 |
| 🔒 **プライバシー原則** | LAN限定、WAN露出なし、ファイルシステムスキャンなし |

## ✨ できること

### 📻 ラジオモード

メイン機能。LLMが面白い話題を英日バイリンガルでラジオ配信します。

1. 10分ごと（または手動トリガー）に発火
2. Soulの嗜好データからプロンプトを構築
3. LLMが EN→JP→EN_REPEAT の構造化セグメントを生成
4. edge_tts が各パートを順番に音声合成
5. フロントエンドにオーバーレイ表示 + デバイスで音声再生

**出力例：**
```
EN: "Productivity apps are basically digital amulets for people who fear their own inbox."
JP:  「生産性アプリって、結局『受信箱が怖い人向けのデジタルお守り』なんだよな。」
EN_REPEAT: "Productivity apps are basically digital amulets..."
💡 "basically" — 「要するに」「ほぼ」みたいな軽い断定で便利。
```

### 🎛️ 操作パネル

`http://<your-host>:30787/` にアクセス。

- 🖼️ **Live2D ON/OFF** — バッテリー節約・帯域節約
- 📻 **ラジオ発火** — 手動トリガー + ムード選択（auto / chaotic / chill / brisk / thoughtful）
- 📜 **ラジオ履歴** — 直近5件のEN/JPプレビュー
- ● **接続状態** — WebSocket死活表示
- ボトムシート式、モバイル最適化、畳める

### 🎤 チャットモード

マイク入力またはテキスト入力で会話。Live2D表情付きで応答。ラジオとは独立して動作。

## 🎯 設計思想

| 原則 | 説明 |
|------|------|
| **ローカル最優先** | すべてLAN内で完結。クラウド依存なし。 |
| **音声最優先** | ラジオが主インターフェース。画面は任意。 |
| **プライバシー重視** | WAN露出なし、ファイルシステムスキャンなし、監視しない。 |
| **ホットパス軽量** | リアルタイム会話をメモリスキャンやツール実行でブロックしない。 |
| **実用より人格** | かわいく、ちょっとカオスで、面白い。教材アシスタントではない。 |

## 🚀 クイックスタート

```bash
# クローン
git clone --recurse-submodules https://github.com/doumin9383/home-aituber.git
cd home-aituber

# 依存インストール
uv sync

# 設定
cp config_templates/conf.default.yaml conf.yaml
# conf.yaml を編集 — LLMエンドポイント、TTS音声、Live2Dモデルを設定

# 起動
uv run run_server.py
# → http://localhost:12393
```

### k3s デプロイ

```bash
kubectl apply -n agent-build -f deploy/k8s/homeaituber.yaml
```

デプロイ手順の詳細は [CLAUDE.md](./CLAUDE.md) §Deployment Notes を参照。

## 🏗️ アーキテクチャ

```
HomeAITuber
  ├─ Open-LLM-VTuber バックエンド（身体）
  │   ├─ ASR, TTS, VAD
  │   ├─ WebSocket (/client-ws)
  │   ├─ キャラクター設定
  │   └─ 能動発話
  │
  ├─ homeaituber レイヤー
  │   ├─ radio_prompt_builder.py   → Soul → LLMプロンプト
  │   ├─ radio_tick.py             → 定期ループ + TTS再生
  │   ├─ server_integration.py     → /radio-ws, /api/feedback, TTS配線
  │   ├─ memory_worker.py          → フィードバック → Soul更新
  │   └─ feedback_logger.py
  │
  ├─ deploy/k8s/
  │   ├─ homeaituber.yaml          → Deployment + ConfigMap + PVC
  │   └─ frontend-index-template.html  → フロントエンド注入
  │
  └─ 将来構想
      ├─ Hermes 連携
      └─ AIRI 移行アダプター
```

## 📋 実装フェーズ

| Phase | 内容 | 状態 |
|-------|------|:----:|
| **0** | Fork + リネーム + SPEC | ✅ |
| **1** | ラジオモード（プロンプト構築、構造化出力、TTS） | ✅ |
| **2** | Soulディレクトリ（人格、プロフィール、嗜好） | ✅ |
| **3** | Mattermost連携 | ⬜ |
| **4** | Memory worker（フィードバック → Soul学習） | ⚠️ コード済 |
| **5** | k3s デプロイ | ✅ |

## 🔒 プライバシー

HomeAITuber は **デフォルトでプライバシー保護** されています：

- ❌ WANへの露出なし
- ❌ ファイルシステム全体の読み取りなし
- ❌ ブラウザ履歴の読み取りなし
- ❌ v0での自律ツール実行なし
- ✅ LAN限定動作
- ✅ `soul/`、`chat_history/`、`cache/`、`config/` のみアクセス許可
- ✅ ユーザーが何を見せて何を見せないかを制御

## 📜 ライセンス

本プロジェクトは [Open-LLM-VTuber](https://github.com/Open-LLM-VTuber/Open-LLM-VTuber) のフォークであり、同一のライセンス条項に従います。詳細は [LICENSE](./LICENSE) を参照。

Live2D サンプルモデルは [Live2D Free Material License](https://www.live2d.jp/en/terms/live2d-free-material-license-agreement/) に基づきます。

---

<p align="center">
  <sub>HomeAITuberはあなたのホームネットワークに属します。自分から外に出てはいけません。</sub>
</p>
