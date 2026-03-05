#!/usr/bin/env python3
"""
Minimal STT client for RealtimeSTT server.
Captures audio from microphone and streams to server for transcription.

Usage:
    python stt_client.py --server 192.168.0.120
    python stt_client.py --server gpu-server  # if in /etc/hosts
"""

import argparse
import asyncio
import json
import struct
import sys
import threading
from queue import Queue

import pyaudio
import websockets

# Audio settings matching server expectations
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SIZE = 1024
FORMAT = pyaudio.paInt16


class STTClient:
    def __init__(self, server_host: str, control_port: int = 8011, data_port: int = 8012):
        self.control_url = f"ws://{server_host}:{control_port}"
        self.data_url = f"ws://{server_host}:{data_port}"
        self.audio_queue: Queue = Queue()
        self.running = False
        self.current_text = ""

    def audio_callback(self, in_data, frame_count, time_info, status):
        """PyAudio callback - puts audio data in queue"""
        if self.running:
            self.audio_queue.put(in_data)
        return (None, pyaudio.paContinue)

    def pack_audio_message(self, audio_data: bytes) -> bytes:
        """Pack audio data with metadata header as expected by server"""
        metadata = {
            "sampleRate": SAMPLE_RATE
        }
        metadata_json = json.dumps(metadata).encode('utf-8')
        metadata_length = len(metadata_json)

        # Pack: 4-byte length (little endian) + metadata JSON + audio data
        return struct.pack('<I', metadata_length) + metadata_json + audio_data

    async def send_audio(self, ws):
        """Send audio chunks to server"""
        while self.running:
            try:
                # Non-blocking get with timeout
                await asyncio.sleep(0.01)
                while not self.audio_queue.empty():
                    data = self.audio_queue.get_nowait()
                    # Pack with metadata header
                    message = self.pack_audio_message(data)
                    await ws.send(message)
            except Exception as e:
                if self.running:
                    print(f"\nError sending audio: {e}", file=sys.stderr)
                break

    async def receive_transcription(self, ws):
        """Receive transcription updates from server"""
        while self.running:
            try:
                message = await ws.recv()
                data = json.loads(message)

                msg_type = data.get("type", "")

                if msg_type == "realtime":
                    # Real-time partial transcription
                    text = data.get("text", "")
                    if text:
                        # Clear line and print partial
                        print(f"\r\033[K{text}", end="", flush=True)
                        self.current_text = text

                elif msg_type == "fullSentence":
                    # Final transcription for a sentence
                    text = data.get("text", "")
                    if text:
                        print(f"\r\033[K{text}")  # Print final and newline
                        self.current_text = ""

                elif msg_type == "recording_start":
                    print("\n[Recording...]", end="", flush=True)

                elif msg_type == "recording_stop":
                    pass  # Will get fullSentence next

                elif msg_type == "vad_detect_start":
                    # Voice activity started
                    pass

                elif msg_type == "vad_detect_stop":
                    # Voice activity stopped
                    pass

            except websockets.ConnectionClosed:
                print("\nConnection closed", file=sys.stderr)
                break
            except Exception as e:
                if self.running:
                    print(f"\nError receiving: {e}", file=sys.stderr)
                break

    async def run(self):
        """Main client loop"""
        print(f"Connecting to {self.data_url}...")

        # Initialize PyAudio
        p = pyaudio.PyAudio()

        # List available input devices
        print("\nAvailable input devices:")
        default_device = p.get_default_input_device_info()
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                marker = " [DEFAULT]" if i == default_device["index"] else ""
                print(f"  {i}: {info['name']}{marker}")
        print()

        # Open audio stream
        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE,
            stream_callback=self.audio_callback,
        )

        try:
            async with websockets.connect(self.data_url) as ws:
                print(f"Connected! Speak into your microphone...")
                print("Press Ctrl+C to stop.\n")

                self.running = True
                stream.start_stream()

                # Run send and receive concurrently
                await asyncio.gather(
                    self.send_audio(ws),
                    self.receive_transcription(ws),
                )

        except KeyboardInterrupt:
            print("\n\nStopping...")
        except Exception as e:
            print(f"\nConnection error: {e}", file=sys.stderr)
        finally:
            self.running = False
            stream.stop_stream()
            stream.close()
            p.terminate()


def main():
    parser = argparse.ArgumentParser(description="STT Client for RealtimeSTT server")
    parser.add_argument(
        "--server", "-s",
        default="192.168.0.120",
        help="Server hostname or IP (default: 192.168.0.120)"
    )
    parser.add_argument(
        "--control-port", "-c",
        type=int,
        default=8011,
        help="Control WebSocket port (default: 8011)"
    )
    parser.add_argument(
        "--data-port", "-d",
        type=int,
        default=8012,
        help="Data WebSocket port (default: 8012)"
    )
    args = parser.parse_args()

    client = STTClient(args.server, args.control_port, args.data_port)
    asyncio.run(client.run())


if __name__ == "__main__":
    main()
