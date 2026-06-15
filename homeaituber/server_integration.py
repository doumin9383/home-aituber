"""Server integration for HomeAITuber radio mode.

Hooks the RadioTickEngine into the Open-LLM-VTuber server lifecycle.
Adds a /radio-ws WebSocket endpoint for broadcasting radio segments
and receiving comment/feedback from connected frontend clients.

Usage:
    from homeaituber.server_integration import RadioServerIntegration

    # After creating the FastAPI server app:
    integration = RadioServerIntegration()
    integration.attach_to_app(server.app)

    # On server start:
    await integration.start()

    # On server shutdown:
    await integration.stop()
"""

import asyncio
import json
import logging as _logging
from pathlib import Path
from typing import Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from homeaituber.radio_tick import RadioTickEngine, RadioSegment
from homeaituber.memory_worker import MemoryWorker

from loguru import logger


class RadioServerIntegration:
    """Integrates radio tick engine + memory worker into the FastAPI server.

    Creates and manages:
    - /radio-ws WebSocket: pushes radio segments, receives comment/feedback,
      handles mode/language switching commands
    - /api/feedback HTTP POST: alternative feedback submission endpoint
    - /api/state HTTP GET: returns current mode, language, and engine status
    - RadioTickEngine background task
    - Periodic memory consolidation worker
    """

    def __init__(
        self,
        soul_dir: str = "soul",
        llm_base_url: str = "http://100.89.160.90:30099/v1",
        llm_model: str = "Gemma-4-26B-A4B-it-NVFP4A16",
        llm_api_key: str = "",
        interval_seconds: int = 600,
        consolidation_interval_minutes: int = 30,
    ):
        self._radio_clients: Set[WebSocket] = set()
        self._engine: Optional[RadioTickEngine] = None
        self._task: Optional[asyncio.Task] = None

        self.soul_dir = soul_dir
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.llm_api_key = llm_api_key
        self.interval_seconds = interval_seconds
        self.consolidation_interval_minutes = consolidation_interval_minutes
        self._memory_worker = MemoryWorker(soul_dir)
        self._tts_engine = None  # Set via set_tts_engine() after server init

        # Mode / Language state
        self.current_mode: str = "radio"      # "chat" | "radio" | "radio-chat"
        self.current_language: str = "en-jp"   # "en" | "jp" | "en-jp" | "en-jp-note" | "mixed"

    def set_tts_engine(self, tts_engine) -> None:
        """Set the TTS engine reference after server initialization."""
        self._tts_engine = tts_engine

    def attach_to_app(self, app: FastAPI) -> None:
        """Register WebSocket and HTTP endpoints."""

        # ── HTTP feedback endpoint ──
        @app.post("/api/feedback")
        async def submit_feedback(data: dict):
            event = {
                "timestamp": data.get("timestamp", ""),
                "source": data.get("source", "web_ui"),
                "event": data.get("event", "comment"),
                "text": data.get("text", ""),
                "segment_id": data.get("segment_id", ""),
                "topic": data.get("topic", ""),
            }
            self._memory_worker.write_feedback(event)
            return {"status": "ok"}

        # ── HTTP state endpoint ──
        @app.get("/api/state")
        async def get_state():
            return {
                "mode": self.current_mode,
                "language": self.current_language,
                "engine_running": self.is_running,
            }

        # ── Radio WebSocket ──
        @app.websocket("/radio-ws")
        async def radio_websocket(websocket: WebSocket):
            await websocket.accept()
            client_host = websocket.client.host if websocket.client else "unknown"
            logger.info(f"Radio WebSocket client connected: {client_host}")
            self._radio_clients.add(websocket)

            # Send current state on connect
            await websocket.send_json({
                "type": "state-sync",
                "mode": self.current_mode,
                "language": self.current_language,
                "engine_running": self.is_running,
            })

            try:
                while True:
                    data = await websocket.receive_text()
                    msg = json.loads(data)
                    msg_type = msg.get("type", "")

                    if msg_type == "ping":
                        await websocket.send_json({"type": "pong"})

                    elif msg_type == "request-radio":
                        # Client requests an immediate radio segment
                        mood = msg.get("mood")
                        if self._engine:
                            segment = await self._engine.generate_segment(
                                mood=mood,
                                language_mode=self.current_language,
                            )
                            if segment:
                                # Run TTS playback before notifying frontend
                                await self._engine._playback_segment(segment)
                                await self._broadcast_segment(segment)

                    elif msg_type == "set-mode":
                        mode = msg.get("mode", "radio")
                        valid_modes = ("chat", "radio", "radio-chat")
                        if mode not in valid_modes:
                            await websocket.send_json({
                                "type": "error",
                                "message": f"Invalid mode: {mode}. Valid: {valid_modes}",
                            })
                            continue
                        self.current_mode = mode
                        logger.info(f"Mode set to: {mode}")
                        await websocket.send_json({
                            "type": "mode-changed",
                            "mode": mode,
                        })
                        # Broadcast mode change to all clients
                        await self._broadcast_state()

                    elif msg_type == "set-language":
                        lang = msg.get("language", "en-jp")
                        from homeaituber.radio_prompt_builder import LANGUAGE_SCHEMAS
                        if lang not in LANGUAGE_SCHEMAS:
                            await websocket.send_json({
                                "type": "error",
                                "message": f"Invalid language: {lang}. Valid: {list(LANGUAGE_SCHEMAS.keys())}",
                            })
                            continue
                        self.current_language = lang
                        logger.info(f"Language set to: {lang}")
                        # Propagate to engine for auto-ticks
                        if self._engine:
                            self._engine.set_language_mode(lang)
                        await websocket.send_json({
                            "type": "language-changed",
                            "language": lang,
                        })
                        # Broadcast language change to all clients
                        await self._broadcast_state()

                    elif msg_type in ("comment", "feedback"):
                        # Save user comment/feedback
                        event = {
                            "source": "radio_ws",
                            "event": msg_type,
                            "text": msg.get("text", ""),
                            "segment_id": msg.get("segment_id", ""),
                            "topic": msg.get("topic", ""),
                        }
                        self._memory_worker.write_feedback(event)
                        await websocket.send_json({"type": "feedback-ack"})

                    elif msg_type == "consolidate":
                        # Manually trigger memory consolidation
                        result = await self._memory_worker.consolidate()
                        await websocket.send_json({
                            "type": "consolidation-result",
                            **result,
                        })

            except WebSocketDisconnect:
                logger.info(f"Radio WebSocket client disconnected: {client_host}")
            except Exception as e:
                logger.error(f"Radio WebSocket error: {e}")
            finally:
                self._radio_clients.discard(websocket)

        logger.info("Radio integration endpoints registered: /radio-ws, /api/feedback")

    async def _broadcast_segment(self, segment: RadioSegment) -> None:
        """Send a radio segment to all connected WebSocket clients."""
        payload = {
            "type": "radio-segment",
            "segment": segment.to_dict(),
        }
        dead_clients: Set[WebSocket] = set()
        for ws in self._radio_clients:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    payload_json = json.dumps(payload, ensure_ascii=False)
                    await ws.send_text(payload_json)
            except Exception as e:
                logger.warning(f"Failed to send to radio client: {e}")
                dead_clients.add(ws)
        self._radio_clients -= dead_clients

    async def _broadcast_state(self) -> None:
        """Broadcast current mode/language state to all connected WebSocket clients."""
        payload = {
            "type": "state-sync",
            "mode": self.current_mode,
            "language": self.current_language,
            "engine_running": self.is_running,
        }
        dead_clients: Set[WebSocket] = set()
        for ws in self._radio_clients:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    payload_json = json.dumps(payload, ensure_ascii=False)
                    await ws.send_text(payload_json)
            except Exception as e:
                logger.warning(f"Failed to broadcast state: {e}")
                dead_clients.add(ws)
        self._radio_clients -= dead_clients

    async def _broadcast_audio(self, audio_payload: dict) -> None:
        """Send an audio payload to all connected radio-ws clients."""
        dead_clients: Set[WebSocket] = set()
        payload_json = json.dumps(audio_payload, ensure_ascii=False)
        for ws in self._radio_clients:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(payload_json)
            except Exception as e:
                logger.warning(f"Failed to send audio to radio client: {e}")
                dead_clients.add(ws)
        self._radio_clients -= dead_clients

    async def _tts_callback(self, text: str, lang: str) -> None:
        """TTS callback for RadioTickEngine — generate audio and broadcast to frontend."""
        if not self._tts_engine:
            return
        try:
            from src.open_llm_vtuber.utils.stream_audio import prepare_audio_payload
            from src.open_llm_vtuber.agent.output_types import DisplayText

            audio_path = await self._tts_engine.async_generate_audio(text)
            if audio_path:
                display = DisplayText(text=f"[{lang}] {text}", name="HomeAITuber")
                payload = prepare_audio_payload(
                    audio_path,
                    display_text=display,
                )
                await self._broadcast_audio(payload)
        except Exception as e:
            logger.error(f"Radio TTS failed: {e}")

    async def _notify_callback(self, segment_dict: dict) -> None:
        """Callback for RadioTickEngine — broadcasts via WebSocket."""
        segment = RadioSegment(segment_dict)
        await self._broadcast_segment(segment)

    async def _consolidation_loop(self) -> None:
        """Periodic memory consolidation loop."""
        interval_seconds = self.consolidation_interval_minutes * 60
        logger.info(
            f"Memory consolidation loop started (every {self.consolidation_interval_minutes} min)"
        )
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                await self._memory_worker.consolidate()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Memory consolidation error: {e}")

    async def start(self) -> None:
        """Create and start the radio tick engine + consolidation loop."""
        if self._engine is not None:
            logger.warning("Radio engine already started")
            return

        self._engine = RadioTickEngine(
            soul_dir=Path(self.soul_dir),
            llm_base_url=self.llm_base_url,
            llm_model=self.llm_model,
            llm_api_key=self.llm_api_key,
            interval_seconds=self.interval_seconds,
            tts_callback=self._tts_callback if self._tts_engine else None,
            notify_callback=self._notify_callback,
        )

        # Start the background tick loop
        self._engine.start()

        # Start periodic memory consolidation
        loop = asyncio.get_event_loop()
        self._consolidation_task = loop.create_task(self._consolidation_loop())

        logger.info(
            f"Radio integration started (interval={self.interval_seconds}s, "
            f"model={self.llm_model}, "
            f"consolidation={self.consolidation_interval_minutes}min)"
        )

    async def stop(self) -> None:
        """Stop the radio tick engine, consolidation loop, and disconnect all clients."""
        if self._engine:
            await self._engine.stop()
            self._engine = None

        if hasattr(self, "_consolidation_task") and self._consolidation_task:
            self._consolidation_task.cancel()
            try:
                await self._consolidation_task
            except asyncio.CancelledError:
                pass

        # Disconnect all radio WebSocket clients
        for ws in list(self._radio_clients):
            try:
                await ws.close()
            except Exception:
                pass
        self._radio_clients.clear()
        logger.info("Radio integration stopped")

    @property
    def is_running(self) -> bool:
        return self._engine is not None and self._engine.is_running()

    async def generate_and_broadcast(self, mood: Optional[str] = None) -> Optional[dict]:
        """Generate a single segment and broadcast it immediately."""
        if not self._engine:
            logger.warning("Radio engine not started")
            return None
        segment = await self._engine.generate_segment(mood=mood)
        if segment:
            await self._broadcast_segment(segment)
            return segment.to_dict()
        return None
