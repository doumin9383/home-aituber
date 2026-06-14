"""Audio-only frontend for HomeAITuber.

Headless frontend that connects to the Open-LLM-VTuber WebSocket backend
and plays radio segments via local audio output.

No Live2D, no web UI — just audio + text logging.
Can be toggled ON/OFF independently from the visual frontend.
"""

import asyncio
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Platform-aware audio player.

    Tries: ffplay (ffmpeg) → aplay → python audio libraries.
    Falls back to returning the audio path if no player is available.
    """

    def __init__(self):
        self._player = self._detect_player()

    @staticmethod
    def _detect_player() -> Optional[str]:
        """Find the best available audio player."""
        for cmd in ["ffplay", "aplay", "paplay", "gst-play-1.0"]:
            try:
                subprocess.run(["which", cmd], capture_output=True, check=True)
                return cmd
            except (subprocess.CalledProcessError, FileNotFoundError):
                continue
        return None

    async def play(self, audio_path: str) -> bool:
        """Play an audio file. Returns True if playback started."""
        if not self._player:
            logger.warning("No audio player available. Audio saved at: %s", audio_path)
            return False

        try:
            if self._player == "ffplay":
                proc = await asyncio.create_subprocess_exec(
                    "ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet",
                    audio_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    self._player, audio_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            await proc.wait()
            return True
        except Exception as e:
            logger.error(f"Audio playback failed: {e}")
            return False


class RadioFrontend:
    """Headless radio frontend.

    Connects to the Open-LLM-VTuber server's WebSocket and plays
    radio segments. Can be toggled on/off independently.

    Args:
        server_url: WebSocket URL (e.g. ws://localhost:12393/client-ws?client_id=radio)
        audio_player: AudioPlayer instance or None for no playback
        show_subtitles: Print subtitles to stdout
    """

    def __init__(
        self,
        server_url: str = "ws://localhost:12393/client-ws",
        client_id: str = "radio_frontend",
        audio_player: Optional[AudioPlayer] = None,
        show_subtitles: bool = True,
    ):
        self.server_url = server_url
        self.client_id = client_id
        self.player = audio_player or AudioPlayer()
        self.show_subtitles = show_subtitles
        self._ws: Optional = None
        self._running = False
        self._enabled = True  # Can be toggled ON/OFF

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool) -> None:
        self._enabled = value
        logger.info(f"Radio frontend {'enabled' if value else 'disabled'}")

    async def connect(self) -> None:
        """Connect to the Open-LLM-VTuber WebSocket server."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed. Run: uv pip install websockets")
            return

        try:
            ws_url = f"{self.server_url}?client_id={self.client_id}"
            self._ws = await websockets.connect(ws_url)
            self._running = True
            logger.info(f"Radio frontend connected to {self.server_url}")

            # Send init message
            await self._ws.send(json.dumps({
                "type": "text-input",
                "text": "Hello! I'm the radio frontend.",
            }))

            # Start receiving loop
            await self._receive_loop()

        except Exception as e:
            logger.error(f"Radio frontend connection failed: {e}")
            self._running = False

    async def _receive_loop(self) -> None:
        """Receive and process messages from the server."""
        while self._running and self._ws:
            try:
                message = await asyncio.wait_for(self._ws.recv(), timeout=30.0)
                await self._handle_message(json.loads(message))
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                try:
                    await self._ws.send(json.dumps({"type": "heartbeat"}))
                except Exception:
                    break
            except Exception as e:
                logger.error(f"Receive error: {e}")
                break

    async def _handle_message(self, data: dict) -> None:
        """Process an incoming WebSocket message."""
        msg_type = data.get("type", "")

        if msg_type == "full-text":
            text = data.get("text", "")
            if self.show_subtitles:
                print(f"[Radio] {text}", flush=True)

        elif msg_type == "audio-segment":
            # Audio being streamed for playback
            audio_path = data.get("audio_path", "")
            if self._enabled and audio_path:
                if self.show_subtitles:
                    print(f"[Audio] Playing: {data.get('transcript', '')}", flush=True)
                await self.player.play(audio_path)

        elif msg_type == "radio-segment":
            # Full structured radio segment
            segment = data.get("segment", {})
            if self.show_subtitles:
                en = segment.get("en", "")
                jp = segment.get("jp", "")
                print(f"\n--- Radio Segment ---", flush=True)
                print(f"EN: {en}", flush=True)
                print(f"JP: {jp}", flush=True)
                if segment.get("phrase"):
                    print(f"Phrase: {segment['phrase']} — {segment.get('note', '')}", flush=True)
                print(f"---\n", flush=True)

    async def disconnect(self) -> None:
        """Disconnect from the server."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        logger.info("Radio frontend disconnected")


async def run_radio_frontend(
    server_url: str = "ws://localhost:12393/client-ws",
    client_id: str = "radio_frontend",
    show_subtitles: bool = True,
):
    """Run the radio frontend (CLI entry point)."""
    player = AudioPlayer()
    frontend = RadioFrontend(
        server_url=server_url,
        client_id=client_id,
        audio_player=player,
        show_subtitles=show_subtitles,
    )
    await frontend.connect()


if __name__ == "__main__":
    import sys
    ws_url = sys.argv[1] if len(sys.argv) > 1 else "ws://localhost:12393/client-ws"
    asyncio.run(run_radio_frontend(server_url=ws_url))
