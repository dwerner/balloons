"""Sound notification support for Balloons.

Plays audio notifications for events like streaming completion or errors.
"""

import asyncio
import subprocess
from pathlib import Path
from typing import Optional


# Default sound directory
SOUNDS_DIR = Path.home() / ".balloons" / "sounds"

# Sound file names
SOUND_ERROR = "error.mp3"
SOUND_DONE = "done.mp3"
SOUND_NOTIFICATION = "notification.mp3"


def _find_player() -> Optional[str]:
    """Find an available audio player command."""
    players = ["mpv", "ffplay", "paplay", "aplay"]
    for player in players:
        try:
            result = subprocess.run(
                ["which", player],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                return player
        except Exception:
            continue
    return None


def _get_player_args(player: str, sound_path: Path) -> list[str]:
    """Get command line args for the audio player."""
    if player == "mpv":
        return ["mpv", "--no-video", "--really-quiet", str(sound_path)]
    elif player == "ffplay":
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(sound_path)]
    elif player == "paplay":
        # paplay only supports wav/ogg, need to convert mp3
        return ["paplay", str(sound_path)]
    elif player == "aplay":
        return ["aplay", "-q", str(sound_path)]
    else:
        return [player, str(sound_path)]


async def play_sound_async(sound_name: str) -> None:
    """Play a sound file asynchronously (non-blocking).

    Args:
        sound_name: Name of sound file in ~/.balloons/sounds/
    """
    sound_path = SOUNDS_DIR / sound_name
    if not sound_path.exists():
        return

    player = _find_player()
    if not player:
        return

    args = _get_player_args(player, sound_path)

    try:
        # Run in background, don't wait
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        # Don't await - let it play in background
    except Exception:
        pass  # Silently ignore audio playback failures


def play_sound(sound_name: str) -> None:
    """Play a sound file (fire-and-forget).

    Schedules async playback if event loop is running,
    otherwise runs synchronously.

    Args:
        sound_name: Name of sound file in ~/.balloons/sounds/
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(play_sound_async(sound_name))
    except RuntimeError:
        # No event loop - run synchronously in background
        sound_path = SOUNDS_DIR / sound_name
        if not sound_path.exists():
            return

        player = _find_player()
        if not player:
            return

        args = _get_player_args(player, sound_path)

        try:
            subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass


def play_error_sound() -> None:
    """Play the error notification sound."""
    play_sound(SOUND_ERROR)


def play_done_sound() -> None:
    """Play the completion notification sound."""
    play_sound(SOUND_DONE)


def play_notification_sound() -> None:
    """Play a generic notification sound."""
    play_sound(SOUND_NOTIFICATION)
