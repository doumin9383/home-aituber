# HomeAITuber Phase 1 — 実行手順

## 前提環境

- k3s クラスタで動作（開発はローカルで十分）
- LLM: Atlas Gemma-4-26B at `http://100.89.160.90:30099/v1` (model: `Gemma-4-26B-A4B-it-NVFP4A16`)
- 代替: LiteLLM proxy at `http://100.81.16.52:30094/v1` (model alias: `gemma4`, Bearer token要)
- HF cache は `nfs-external` (thinkstationpgx-19fa:/srv/ai)

## LLM エンドポイント状況 (2026-06-12 時点)

| サービス | URL | 状態 | 備考 |
|----------|-----|------|------|
| Atlas (Gemma-4-26B 直) | `http://100.89.160.90:30099/v1` | ✅ 正常 | TTFT ~200ms, 45tok/s |
| LiteLLM (gemma4 proxy) | `http://100.81.16.52:30094/v1` | ⚠️ Bearer token要 | DB接続要確認 |

## 起動手順

### 1. LLM を立ち上げる

agents namespace に ollama をデプロイ (軽量テスト用):

```bash
kubectl apply -n agents -f - <<EOF
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama-test
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ollama-test
  template:
    metadata:
      labels:
        app: ollama-test
    spec:
      containers:
      - name: ollama
        image: ollama/ollama:latest
        ports:
        - containerPort: 11434
        env:
        - name: OLLAMA_HOST
          value: "0.0.0.0"
---
apiVersion: v1
kind: Service
metadata:
  name: ollama-test
spec:
  type: ClusterIP
  selector:
    app: ollama-test
  ports:
  - port: 11434
    targetPort: 11434
EOF
```

or 既存の liteLLM を直す:

```bash
# litellm pod のログ確認
kubectl logs -n llm-gateway -l app=litellm

# atlas pod の状態確認 (llm-inference namespace)
kubectl get pods -n llm-inference
```

### 2. テスト実行

```bash
# Prompt builder & segment model の単体テスト (LLM不要)
cd /opt/data/home-aituber
uv run python tests/test_radio_phase1.py

# LLM 結合テスト
uv run python tests/test_radio_phase1.py \
  --llm-base-url http://litellm.llm-gateway.svc.cluster.local \
  --llm-model gemma4

# または ollama 経由
uv run python tests/test_radio_phase1.py \
  --llm-base-url http://ollama-test.agents.svc.cluster.local:11434/v1 \
  --llm-model llama3.2:1b
```

### 3. Radio エンジン起動 (CLI)

```bash
uv run python -m homeaituber.radio_tick
```

環境変数で LLM を指定:

```bash
LLM_BASE_URL=http://ollama-test.agents.svc.cluster.local:11434/v1 \
LLM_MODEL=llama3.2:1b \
RADIO_INTERVAL=600 \
uv run python -m homeaituber.radio_tick
```

### 4. agents-build へのデプロイ

```bash
# Source を agents-build にコピー
kubectl exec deploy/homeaituber -n agents-build -- mkdir -p /workspace
kubectl cp /opt/data/home-aituber agents-build/homeaituber:/workspace/home-aituber

# または PVC 経由でマウント
kubectl apply -n agents-build -f deploy/k8s/homeaituber.yaml
```

## フロントエンドセットアップ

```bash
# 1. Frontend submodule を初期化
cd /opt/data/home-aituber
git submodule update --init --recursive

# 2. サーバー起動（フロントエンドは自動的に配信される）
uv run run_server.py
# → http://localhost:12393 でアクセス可能

# 3. radio_tick を単体テスト
uv run python -m homeaituber.radio_tick
```

### LLM 環境変数

```bash
# Atlas 直
LLM_BASE_URL=http://100.89.160.90:30099/v1 \
LLM_MODEL=Gemma-4-26B-A4B-it-NVFP4A16 \
uv run python -m homeaituber.radio_tick

# LiteLLM 経由
LLM_BASE_URL=http://100.81.16.52:30094/v1 \
LLM_MODEL=gemma4 \
LLM_API_KEY=<your-bearer-token> \
uv run python -m homeaituber.radio_tick
```

## アーキテクチャ

```
Radio Tick Loop (interval timer)
  └─ radio_prompt_builder.py
       └─ soul/ identity, daily_cache, topic_weights, review_queue
            └─ Speaker LLM (OpenAI-compatible API)
                 └─ JSON structured output (EN/JP/EN_REPEAT)
                      ├─ TTS (edge_tts / 既存のTTSエンジン)
                      │    └─ スピーカー出力
                      └─ Mattermost 投稿 (Phase 3+)
                      └─ WebSocket notify → フロントエンド
```

## Live2D ON/OFF

Live2D は独立した ON/OFF 切り替え可能。
- Radio mode は Live2D と無関係に動作
- `web_tool/radio.html` から切り替えUI提供
- コンフィグ: `homeaituber_config.live2d.enabled`
