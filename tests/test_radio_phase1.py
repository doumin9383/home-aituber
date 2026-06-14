#!/usr/bin/env python3
"""Standalone test script for HomeAITuber Phase 1 Radio Mode.

Tests:
1. RadioPromptBuilder — builds correct prompts from soul context
2. RadioTickEngine.generate_segment — calls LLM and parses JSON response
3. RadioSegment — playback order and serialization

Usage:
  # Test prompt builder only (no LLM needed):
  python tests/test_radio_phase1.py

  # Test full pipeline (requires running LLM):
  python tests/test_radio_phase1.py --llm-base-url http://litellm.llm-gateway.svc.cluster.local --llm-model gemma4

  # Test with local ollama:
  python tests/test_radio_phase1.py --llm-base-url http://localhost:11434/v1 --llm-model qwen2.5:0.5b
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def test_prompt_builder():
    """Test RadioPromptBuilder with mock soul data."""
    from homeaituber.radio_prompt_builder import RadioPromptBuilder

    print("=== Test: RadioPromptBuilder ===")

    with tempfile.TemporaryDirectory() as tmp:
        soul_dir = Path(tmp)

        # Write test soul files
        (soul_dir / "identity.md").write_text(
            "HomeAITuber - cute, chaotic, private.\n"
            "Name: Airi\n"
            "Tone: friendly, lightly chaotic\n"
            "Privacy: no WAN, no filesystem scan\n"
        )
        (soul_dir / "daily_cache.md").write_text(
            "## Daily Cache 2026-06-12\n"
            "User was excited about local LLM project.\n"
            "Spent time debugging k3s manifests.\n"
        )
        (soul_dir / "topic_weights.json").write_text(
            json.dumps({
                "homelab": 0.95,
                "local_ai": 0.95,
                "aituber": 0.9,
                "language_learning": 0.7,
                "generic_news": 0.2,
            })
        )
        (soul_dir / "review_queue.json").write_text(
            json.dumps([
                {"phrase": "basically means 要するに", "en": "Productivity apps are basically digital amulets"},
                {"phrase": "worth noting means 注目に値する", "en": "It's worth noting that..."},
            ])
        )

        builder = RadioPromptBuilder(soul_dir)

        # Test identity loading
        identity = builder.load_identity()
        assert "Airi" in identity, "Should read identity"
        print(f"  ✓ load_identity(): {len(identity)} chars")

        # Test topic weights
        topics = builder.load_topic_weights()
        assert "homelab" in topics, "Should read topic weights"
        print(f"  ✓ load_topic_weights(): {len(topics)} topics")

        # Test review queue
        queue = builder.load_review_queue()
        assert len(queue) == 2, "Should read review queue"
        print(f"  ✓ load_review_queue(): {len(queue)} items")

        # Test radio prompt build
        prompt = builder.build_radio_prompt()
        assert "Generate a radio segment" in prompt, "Should contain task description"
        assert "segment_id" in prompt, "Should contain JSON schema"
        assert "\"homelab\": 0.95" in json.dumps(topics), "homelab should be in weights"
        print(f"  ✓ build_radio_prompt(): {len(prompt)} chars")

        # Test with user command
        prompt_cmd = builder.build_radio_prompt(user_command="Talk about AI in Japan")
        assert "Talk about AI in Japan" in prompt_cmd, "Should include command"
        print(f"  ✓ build_radio_prompt(with command): {len(prompt_cmd)} chars")

        # Test chat prompt
        chat = builder.build_chat_prompt("Hello!")
        assert "The user says: Hello!" in chat, "Should include user message"
        print(f"  ✓ build_chat_prompt(): {len(chat)} chars")

    print("  ✅ All prompt builder tests passed!\n")
    return True


def test_radio_segment():
    """Test RadioSegment data model."""
    from homeaituber.radio_tick import RadioSegment

    print("=== Test: RadioSegment ===")

    data = {
        "segment_id": "radio-20260612-120000",
        "en": "The quick brown fox jumps over the lazy dog.",
        "jp": "素早い茶色の狐はのろまな犬を飛び越える。",
        "en_repeat": "The quick brown fox jumps over the lazy dog.",
        "phrase": "jumps over = 飛び越える",
        "note": "動物を使った英語の例文。フォニックス練習にも使われる有名なパングラム。",
        "topic": "language_learning",
        "safety": {"uses_private_data": False, "requires_external_access": False},
    }

    seg = RadioSegment(data)
    assert seg.segment_id == "radio-20260612-120000"
    assert seg.en == data["en"]
    assert seg.jp == data["jp"]

    # Test playback order
    order = seg.to_playback_order()
    assert len(order) >= 5, "Should have EN, pause, JP, pause, EN_REPEAT at minimum"
    assert order[0]["type"] == "speak"
    assert order[0]["text"] == data["en"]
    assert order[2]["text"] == data["jp"]
    assert order[4]["type"] == "speak"
    assert order[4]["text"] == data["en_repeat"]

    # Test serialization
    d = seg.to_dict()
    assert d["en"] == data["en"]
    assert d["topic"] == "language_learning"
    assert "timestamp" in d

    print(f"  ✓ RadioSegment creation from dict")
    print(f"  ✓ to_playback_order(): {len(order)} parts")
    print(f"  ✓ to_dict(): {len(d)} keys")
    print("  ✅ All RadioSegment tests passed!\n")
    return True


def test_live_llm(base_url: str, model: str, api_key: str):
    """Test RadioTickEngine with a live LLM endpoint."""
    from homeaituber.radio_tick import RadioTickEngine

    print(f"=== Test: Live LLM ({model} @ {base_url}) ===")

    soul_dir = Path(__file__).resolve().parent.parent / "soul"
    if not soul_dir.exists():
        print(f"  ⚠ soul dir not found at {soul_dir}, using mock")
        import tempfile
        soul_dir = Path(tempfile.mkdtemp())
        (soul_dir / "identity.md").write_text("HomeAITuber - a cute private AITuber.")
        (soul_dir / "daily_cache.md").write_text("## Test context")
        (soul_dir / "topic_weights.json").write_text('{"test": 1.0}')
        (soul_dir / "review_queue.json").write_text("[]")

    import asyncio

    async def run():
        engine = RadioTickEngine(
            soul_dir=soul_dir,
            llm_base_url=base_url,
            llm_model=model,
            llm_api_key=api_key,
        )
        segment = await engine.generate_segment(
            user_command="Say something about AI assistants."
        )
        if segment is None:
            print("  ❌ LLM returned no segment")
            return False

        print(f"  ✓ Segment ID: {segment.segment_id}")
        print(f"  ✓ Topic: {segment.topic}")
        print(f"  ✓ EN: {segment.en[:80]}")
        print(f"  ✓ JP: {segment.jp[:80]}")
        print(f"  ✓ EN_REPEAT: {segment.en_repeat[:80]}")
        if segment.phrase:
            print(f"  ✓ Phrase: {segment.phrase[:80]}")
        if segment.note:
            print(f"  ✓ Note: {segment.note[:80]}")
        print(f"  ✓ Safety: uses_private_data={segment.safety['uses_private_data']}")

        # Validate structure
        assert segment.en, "EN text required"
        assert segment.jp, "JP text required"
        assert segment.en_repeat, "EN_REPEAT required"

        print("  ✅ Live LLM test passed!\n")
        return True

    return asyncio.run(run())


def main():
    parser = argparse.ArgumentParser(description="HomeAITuber Phase 1 Tests")
    parser.add_argument("--llm-base-url", help="OpenAI-compatible base URL for live LLM test")
    parser.add_argument("--llm-model", default="gemma4", help="Model name for LLM test")
    parser.add_argument("--llm-api-key", default="sk-local", help="API key for LLM")
    parser.add_argument("--skip-prompt", action="store_true", help="Skip prompt builder tests")
    parser.add_argument("--skip-segment", action="store_true", help="Skip segment model tests")
    parser.add_argument("--live-only", action="store_true", help="Run only live LLM test")
    args = parser.parse_args()

    passed = 0
    failed = 0

    if not args.live_only:
        if not args.skip_prompt:
            try:
                test_prompt_builder()
                passed += 1
            except Exception as e:
                print(f"❌ Prompt builder test FAILED: {e}\n")
                failed += 1

        if not args.skip_segment:
            try:
                test_radio_segment()
                passed += 1
            except Exception as e:
                print(f"❌ RadioSegment test FAILED: {e}\n")
                failed += 1

    if args.llm_base_url:
        try:
            if test_live_llm(args.llm_base_url, args.llm_model, args.llm_api_key):
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ Live LLM test FAILED: {e}\n")
            failed += 1

    if args.live_only and not args.llm_base_url:
        parser.error("--live-only requires --llm-base-url")

    if not args.llm_base_url and not args.live_only:
        print("Tip: Add --llm-base-url <url> to test against a live LLM.\n")

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
