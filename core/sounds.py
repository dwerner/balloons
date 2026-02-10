"""Sound notification support for Balloons.

Plays audio notifications for events like streaming completion or errors.
"""

import asyncio
from pathlib import Path
from typing import Optional


# Default sound directory
SOUNDS_DIR = Path.home() / ".balloons" / "sounds"


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
        return ["paplay", str(sound_path)]
    elif player == "aplay":
        return ["aplay", "-q", str(sound_path)]
    else:
        return [player, str(sound_path)]


def _is_enabled() -> bool:
    """Check if sounds are enabled in config."""
    from config import get_config
    return get_config().sounds.enabled


def _get_sound_file(sound_type: str) -> str:
    """Get the configured sound file for a given type."""
    from config import get_config
    sounds = get_config().sounds
    return getattr(sounds, sound_type, f"{sound_type}.ogg")


async def play_sound_async(sound_name: str) -> None:
    """Play a sound file asynchronously (non-blocking).

    Args:
        sound_name: Name of sound file in ~/.balloons/sounds/
    """
    if not _is_enabled():
        return

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

    Schedules async playback. Must be called from async context.

    Args:
        sound_name: Name of sound file in ~/.balloons/sounds/
    """
    if not _is_enabled():
        return

    loop = asyncio.get_running_loop()
    loop.create_task(play_sound_async(sound_name))


def play_error_sound() -> None:
    """Play the error notification sound."""
    play_sound(_get_sound_file("error"))


def play_done_sound() -> None:
    """Play the completion notification sound."""
    play_sound(_get_sound_file("done"))


def play_notification_sound() -> None:
    """Play a generic notification sound."""
    play_sound(_get_sound_file("notification"))
