#!/usr/bin/env python3
"""
AI-Link Bridge Server Test Client

Simulates the Unity client behavior to validate the full bridge protocol
without needing the actual Unity client or Quest headset.

Usage:
    1. Start the bridge server: python3 bridge_server.py
    2. Run this test: python3 tests/test_bridge_client.py
    3. Or with custom host/port: python3 tests/test_bridge_client.py --host 192.168.1.10 --port 8765
"""

import asyncio
import json
import time
import sys
import os
import argparse
import struct
import random

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import aiohttp
except ImportError:
    print("ERROR: aiohttp is required. Install with: pip install aiohttp")
    sys.exit(1)

from helpers.protocol import PROTOCOL_VERSION, capabilities_payload

# Parse args
parser = argparse.ArgumentParser(description="AI-Link Bridge Test Client")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--num-frames", type=int, default=60, help="Number of fake video frames to send")
args = parser.parse_args()

BASE_URL = f"http://{args.host}:8765"
WS_URL = f"ws://{args.host}:8765/ws"
SESSION_ID = f"test-session-{int(time.time())}"


async def recv_until_message_type(ws: aiohttp.ClientWebSocketResponse, expected_type: str, timeout: float = 5.0):
    """Read messages until a specific bridge messageType is seen.

    Returns a tuple: (ok, data_or_detail, seen_messages)
    where seen_messages is a list of intermediate message types.
    """
    deadline = time.time() + timeout
    seen = []
    while time.time() < deadline:
        remaining = max(0.1, deadline - time.time())
        msg = await asyncio.wait_for(ws.receive(), timeout=remaining)
        if msg.type == aiohttp.WSMsgType.TEXT:
            data = json.loads(msg.data)
            msg_type = data.get("messageType", "")
            seen.append(msg_type)
            if msg_type == expected_type:
                return True, data, seen
            continue
        return False, str(msg), seen
    return False, f"timeout waiting for {expected_type}", seen


def make_envelope(message_type: str, payload: dict, seq: int = 0) -> str:
    """Create a bridge protocol envelope JSON string."""
    return json.dumps({
        "protocolVersion": PROTOCOL_VERSION,
        "messageType": message_type,
        "sessionId": SESSION_ID,
        "timestampMs": int(time.time() * 1000),
        "sequence": seq,
        "payloadFormat": "json",
        "payload": payload,
    })


def make_fake_video_frame(frame_num: int) -> bytes:
    """Create a fake video frame (type 1) binary message."""
    timestamp = struct.pack("<q", int(time.time() * 1000))
    # Generate a small fake JPEG-like payload with frame number
    fake_data = b"\xff\xd8\xff\xe0" + f"FAKE_FRAME_{frame_num:06d}".encode() + b"\xff\xd9"
    return bytes([1]) + timestamp + fake_data


def make_fake_audio_frame(frame_num: int) -> bytes:
    """Create a fake audio frame (type 0) binary message."""
    timestamp = struct.pack("<q", int(time.time() * 1000))
    # Generate small fake Opus-like payload
    fake_data = bytes([0x00, 0x01]) + struct.pack("<I", frame_num) + bytes(random.randint(20, 80))
    return bytes([0]) + timestamp + fake_data


async def test_http_endpoints():
    """Test all HTTP endpoints."""
    print("\n" + "=" * 50)
    print("PHASE 1: HTTP Endpoint Tests")
    print("=" * 50)

    results = []
    async with aiohttp.ClientSession() as session:
        # Health check
        async with session.get(f"{BASE_URL}/health") as resp:
            data = await resp.json()
            ok = resp.status == 200 and data.get("status") == "ok"
            results.append(("GET /health", ok, data))
            print(f"  [{'PASS' if ok else 'FAIL'}] GET /health -> {data}")

        # Capabilities
        async with session.get(f"{BASE_URL}/capabilities") as resp:
            data = await resp.json()
            ok = resp.status == 200 and data.get("protocol") == PROTOCOL_VERSION
            results.append(("GET /capabilities", ok, data.get("capabilities", {})))
            print(f"  [{'PASS' if ok else 'FAIL'}] GET /capabilities -> protocol={data.get('protocol')}")
            caps = data.get("capabilities", {})
            print(f"           videoFormats: {caps.get('videoFormats')}")
            print(f"           audioFormats: {caps.get('audioFormats')}")
            print(f"           captureSources: {caps.get('captureSources')}")

        # Sessions (should be empty initially)
        async with session.get(f"{BASE_URL}/sessions") as resp:
            data = await resp.json()
            ok = resp.status == 200
            results.append(("GET /sessions", ok, data))
            print(f"  [{'PASS' if ok else 'FAIL'}] GET /sessions -> {len(data.get('sessions', []))} sessions")

        # Metrics
        async with session.get(f"{BASE_URL}/metrics") as resp:
            data = await resp.json()
            ok = resp.status == 200
            results.append(("GET /metrics", ok, data))
            print(f"  [{'PASS' if ok else 'FAIL'}] GET /metrics -> {data}")

        # Task trigger (Manifold Pipe test)
        task_payload = {
            "session_id": SESSION_ID,
            "prompt": "Test task from automated test client",
            "route": "test"
        }
        async with session.post(f"{BASE_URL}/task", json=task_payload) as resp:
            data = await resp.json()
            ok = resp.status == 202 and data.get("status") == "scaffolded"
            results.append(("POST /task", ok, data))
            print(f"  [{'PASS' if ok else 'FAIL'}] POST /task -> status={data.get('status')}, task_id={data.get('task_id')}")

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n  HTTP Results: {passed}/{len(results)} passed")
    return results


async def test_websocket_protocol():
    """Test the full WebSocket protocol lifecycle."""
    print("\n" + "=" * 50)
    print("PHASE 2: WebSocket Protocol Tests")
    print("=" * 50)

    results = []
    seq = 0
    video_frames_sent = 0
    audio_frames_sent = 0

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(WS_URL) as ws:
            print(f"  [PASS] WebSocket connected to {WS_URL}")
            results.append(("ws_connect", True, None))

            # --- Hello handshake ---
            hello_msg = make_envelope("hello", {
                "clientName": "AutomatedTestClient",
                "captureMode": "Desktop",
                "protocolVersion": PROTOCOL_VERSION,
                "sessionId": SESSION_ID,
            }, seq)
            seq += 1
            await ws.send_str(hello_msg)
            print(f"  [----] Sent hello")

            # Wait for hello.ack
            ok, data, seen = await recv_until_message_type(ws, "hello.ack", timeout=5)
            results.append(("hello.ack", ok, data))
            if ok:
                print(f"  [PASS] Received hello.ack -> protocol={data.get('payload', {}).get('protocol')}")
            else:
                print(f"  [FAIL] hello.ack not received. Seen={seen} detail={data}")

            # --- Stream start ---
            stream_start = make_envelope("stream.start", {
                "captureMode": "Desktop",
                "codec": "JPEG",
                "width": 1280,
                "height": 720,
                "fps": 30,
            }, seq)
            seq += 1
            await ws.send_str(stream_start)
            print(f"  [----] Sent stream.start")

            ok, data, seen = await recv_until_message_type(ws, "stream.start.ack", timeout=5)
            results.append(("stream.start.ack", ok, data))
            if ok:
                print(f"  [PASS] Received stream.start.ack")
            else:
                print(f"  [FAIL] stream.start.ack not received. Seen={seen} detail={data}")

            # --- Send fake media frames ---
            print(f"\n  Sending {args.num_frames} fake video + audio frames...")
            for i in range(args.num_frames):
                # Send video frame
                video_msg = make_fake_video_frame(i)
                await ws.send_bytes(video_msg)
                video_frames_sent += 1

                # Send audio frame every other video frame
                if i % 2 == 0:
                    audio_msg = make_fake_audio_frame(i)
                    await ws.send_bytes(audio_msg)
                    audio_frames_sent += 1

                # Small delay to simulate real streaming
                await asyncio.sleep(0.005)

            print(f"  [----] Sent {video_frames_sent} video frames, {audio_frames_sent} audio frames")

            # --- Send stats ---
            stats_msg = make_envelope("stats", {
                "reconnectCount": 0,
                "droppedFrames": 0,
                "videoFramesSent": video_frames_sent,
                "audioFramesSent": audio_frames_sent,
                "networkLatencyMs": 12.5,
                "audioLatencyMs": 8.3,
                "videoLatencyMs": 15.7,
            }, seq)
            seq += 1
            await ws.send_str(stats_msg)
            print(f"  [----] Sent stats message")

            # --- Ping/pong ---
            ping_msg = make_envelope("ping", {
                "clientTimeMs": int(time.time() * 1000),
            }, seq)
            seq += 1
            ping_start = time.time()
            await ws.send_str(ping_msg)

            ok, data, seen = await recv_until_message_type(ws, "pong", timeout=5)
            pong_time = time.time() - ping_start
            latency_ms = pong_time * 1000
            results.append(("pong", ok, f"{latency_ms:.1f}ms" if ok else {"seen": seen, "detail": data}))
            if ok:
                print(f"  [PASS] Ping/pong round-trip: {latency_ms:.1f}ms")
            else:
                print(f"  [FAIL] pong not received. Seen={seen} detail={data}")

            # --- Stream stop ---
            stream_stop = make_envelope("stream.stop", {}, seq)
            seq += 1
            await ws.send_str(stream_stop)
            print(f"  [----] Sent stream.stop")

            ok, data, seen = await recv_until_message_type(ws, "stream.stop.ack", timeout=5)
            results.append(("stream.stop.ack", ok, data))
            if ok:
                print(f"  [PASS] Received stream.stop.ack")
            else:
                print(f"  [FAIL] stream.stop.ack not received. Seen={seen} detail={data}")

    return results, video_frames_sent, audio_frames_sent


async def test_post_stream_metrics(video_frames: int, audio_frames: int):
    """Verify the server tracked the frames we sent."""
    print("\n" + "=" * 50)
    print("PHASE 3: Post-Stream Verification")
    print("=" * 50)

    results = []
    async with aiohttp.ClientSession() as session:
        # Check sessions
        async with session.get(f"{BASE_URL}/sessions") as resp:
            data = await resp.json()
            sessions = data.get("sessions", [])
            if sessions:
                s = sessions[0]
                server_video = s.get("metrics", {}).get("videoFrames", 0)
                server_audio = s.get("metrics", {}).get("audioFrames", 0)
                # Server counts every 30th frame echo, so it should have >= video_frames / 30
                ok = server_video > 0 or server_audio > 0
                results.append(("session_metrics", ok, s.get("metrics", {})))
                print(f"  [{'PASS' if ok else 'FAIL'}] Session metrics: video={server_video}, audio={server_audio}")
            else:
                results.append(("session_metrics", False, "No sessions"))
                print(f"  [FAIL] No sessions found")

        # Check aggregate metrics
        async with session.get(f"{BASE_URL}/metrics") as resp:
            data = await resp.json()
            total_video = data.get("total_video_frames", 0)
            total_audio = data.get("total_audio_frames", 0)
            ok = total_video > 0 or total_audio > 0
            results.append(("aggregate_metrics", ok, data))
            print(f"  [{'PASS' if ok else 'FAIL'}] Aggregate: video={total_video}, audio={total_audio}, sessions={data.get('total_sessions')}")

    return results


async def main():
    print("=" * 60)
    print("  AI-Link Bridge Server â€” Automated Test Client")
    print(f"  Protocol: {PROTOCOL_VERSION}")
    print(f"  Target: {args.host}:8765")
    print(f"  Session: {SESSION_ID}")
    print("=" * 60)

    all_results = []

    # Phase 1: HTTP tests
    try:
        http_results = await test_http_endpoints()
        all_results.extend(http_results)
    except Exception as e:
        print(f"\n  [ERROR] HTTP tests failed: {e}")
        print("  Is the bridge server running? Start it with: python3 bridge_server.py")

    # Phase 2: WebSocket protocol tests
    try:
        ws_results, video_frames, audio_frames = await test_websocket_protocol()
        all_results.extend(ws_results)
    except Exception as e:
        print(f"\n  [ERROR] WebSocket tests failed: {e}")
        video_frames, audio_frames = 0, 0

    # Phase 3: Post-stream verification
    if video_frames > 0:
        try:
            post_results = await test_post_stream_metrics(video_frames, audio_frames)
            all_results.extend(post_results)
        except Exception as e:
            print(f"\n  [ERROR] Post-stream verification failed: {e}")

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, ok, _ in all_results if ok)
    total = len(all_results)
    print(f"  Total: {passed}/{total} passed")
    if passed < total:
        print("  Failed tests:")
        for name, ok, detail in all_results:
            if not ok:
                print(f"    - {name}: {detail}")
    print(f"\n  {'ALL TESTS PASSED' if passed == total else 'SOME TESTS FAILED'}")
    print("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    exit(asyncio.run(main()))
