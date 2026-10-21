"""BH-K13 — wpctl parsing must survive the REAL `wpctl status` shape.

The old parser keyed sections by name only and never reset on unknown
headers. Real output has TWO groups (Audio, Video) each with their own
Sinks/Sources, plus Devices, Streams and a Settings block whose
"Default Configured Devices" entries also look like `N. name`. Result:
the laptop camera merged into the audio Sources (offered as a meeting
system/mic node), Firefox's playback stream became a "Source endpoint",
and default-configured entries polluted whatever section came last.
The pre-existing fixture had an Audio group only — the green-tests /
dead-hardware shape this hunt keeps finding.
"""

from __future__ import annotations

from assistant.capture import parse_wpctl_status

REAL_WPCTL = """\
PipeWire 'pipewire-0' [1.2.7, user@fedora, cookie:987654321]
 └─ Clients:
        32. WirePlumber [1.2.7, user@fedora, pid:1234]
        46. pipewire [1.2.7, user@fedora, pid:1235]

Audio
 ├─ Devices:
 │      40. ALC257 Analog [alsa]
 │      41. HDMI Audio [alsa]
 ├─ Sinks:
 │  *   55. ALC257 Analog Stereo [vol: 0.40]
 │      56. HDMI / DisplayPort Stereo [vol: 0.75]
 ├─ Sources:
 │  *   57. ALC257 Analog Stereo [vol: 1.00]
 │      58. USB Headset Microphone [vol: 0.90]
 ├─ Sink endpoints:
 ├─ Source endpoints:
 └─ Streams:
        77. Firefox
 │      78. pw-record

Video
 ├─ Devices:
 │      42. Integrated Camera [v4l2]
 ├─ Sinks:
 ├─ Sources:
 │  *   43. Integrated Camera (V4L2)
 ├─ Sink endpoints:
 ├─ Source endpoints:
 └─ Streams:

Settings
 └─ Default Configured Devices:
         0. Audio/Sink    alsa_output.pci-0000_00_1f.3.analog-stereo
         1. Audio/Source  alsa_input.pci-0000_00_1f.3.analog-stereo
"""


def test_video_sources_do_not_merge_into_audio_sources():
    sections = parse_wpctl_status(REAL_WPCTL)
    source_names = [n["display_name"] for n in sections.get("Sources", [])]
    assert source_names == ["ALC257 Analog Stereo", "USB Headset Microphone"], (
        f"the camera must not be offered as a microphone; got {source_names}")


def test_streams_devices_and_settings_entries_are_not_nodes():
    sections = parse_wpctl_status(REAL_WPCTL)
    everywhere = [n["display_name"] for nodes in sections.values() for n in nodes]
    assert not any("Firefox" in n or "pw-record" in n for n in everywhere), (
        "playback/capture streams are not sinks or sources")
    assert not any("alsa_" in n for n in everywhere), (
        "Default Configured Devices entries are not nodes")
    assert not any("ALC257 Analog [alsa]" == n for n in everywhere), (
        "Devices: entries are cards, not nodes")


def test_audio_sections_and_defaults_survive():
    sections = parse_wpctl_status(REAL_WPCTL)
    sinks = sections.get("Sinks", [])
    assert [n["id"] for n in sinks] == [55, 56]
    assert sinks[0]["is_default"] is True and sinks[1]["is_default"] is False
    assert sections.get("Sink endpoints") == []
    assert sections.get("Source endpoints") == []
