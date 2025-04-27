#!/usr/bin/env python3
"""
Equivalent of the C ‘playbin’ example in Python (GStreamer 1.x, PyGObject)
"""
import sys
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

class CustomData:
    """Mimics the C struct _CustomData"""
    def __init__(self) -> None:
        self.playbin: Gst.Element | None = None
        self.playing = False
        self.terminate = False
        self.seek_enabled = False
        self.seek_done = False
        self.duration = Gst.CLOCK_TIME_NONE


def handle_message(data: CustomData, msg: Gst.Message) -> None:
    mtype = msg.type

    if mtype == Gst.MessageType.ERROR:
        err, debug_info = msg.parse_error()
        print(
            f"Error received from element {msg.src.get_name()}: {err.message}",
            file=sys.stderr,
        )
        print(f"Debugging information: {debug_info or 'none'}", file=sys.stderr)
        data.terminate = True

    elif mtype == Gst.MessageType.EOS:
        print("\nEnd-Of-Stream reached.")
        data.terminate = True

    elif mtype == Gst.MessageType.DURATION_CHANGED:
        # Invalidate stored duration
        data.duration = Gst.CLOCK_TIME_NONE

    elif mtype == Gst.MessageType.STATE_CHANGED and msg.src is data.playbin:
        old, new, pending = msg.parse_state_changed()
        print(
            f"Pipeline state changed from {Gst.Element.state_get_name(old)} "
            f"to {Gst.Element.state_get_name(new)}"
        )

        data.playing = new == Gst.State.PLAYING

        if data.playing:
            # Check if the stream is seekable
            query = Gst.Query.new_seeking(Gst.Format.TIME)
            if data.playbin.query(query):
                _, seek_enabled, start, end = query.parse_seeking()
                data.seek_enabled = seek_enabled
                if seek_enabled:
                    print(
                        f"Seeking is ENABLED from {start / Gst.SECOND:.2f}s "
                        f"to {end / Gst.SECOND:.2f}s"
                    )
                else:
                    print("Seeking is DISABLED for this stream.")
            else:
                print("Seeking query failed.", file=sys.stderr)


def main() -> int:
    Gst.init(None)

    data = CustomData()
    data.playbin = Gst.ElementFactory.make("playbin", "playbin")

    if not data.playbin:
        print("Could not create playbin element.", file=sys.stderr)
        return -1

    data.playbin.set_property(
        "uri",
        "https://gstreamer.freedesktop.org/data/media/sintel_trailer-480p.webm",
    )

    # Start playback
    ret = data.playbin.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        print("Unable to set the pipeline to the playing state.", file=sys.stderr)
        data.playbin.unref()
        return -1

    bus = data.playbin.get_bus()

    while not data.terminate:
        # Wait up to 100 ms for interesting messages on the bus
        msg = bus.timed_pop_filtered(
            100 * Gst.MSECOND,
            Gst.MessageType.STATE_CHANGED
            | Gst.MessageType.ERROR
            | Gst.MessageType.EOS
            | Gst.MessageType.DURATION_CHANGED,
        )

        if msg:
            handle_message(data, msg)
        else:
            # Timeout expired — do UI/update work
            if data.playing:
                ok, current = data.playbin.query_position(Gst.Format.TIME)
                if not ok:
                    print("Could not query current position.", file=sys.stderr)
                    current = Gst.CLOCK_TIME_NONE

                if data.duration == Gst.CLOCK_TIME_NONE:
                    ok, data.duration = data.playbin.query_duration(Gst.Format.TIME)
                    if not ok:
                        print("Could not query current duration.", file=sys.stderr)
                        data.duration = Gst.CLOCK_TIME_NONE

                if (
                    current != Gst.CLOCK_TIME_NONE
                    and data.duration != Gst.CLOCK_TIME_NONE
                ):
                    print(
                        f"Position {current / Gst.SECOND:.2f}s / "
                        f"{data.duration / Gst.SECOND:.2f}s",
                        end="\r",
                        flush=True,
                    )

                # Seek to 30 s once we pass 10 s
                if (
                    data.seek_enabled
                    and not data.seek_done
                    and current > 10 * Gst.SECOND
                ):
                    print("\nReached 10 s, performing seek…")
                    data.playbin.seek_simple(
                        Gst.Format.TIME,
                        Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
                        30 * Gst.SECOND,
                    )
                    data.seek_done = True

    # Clean up
    bus.unref()
    data.playbin.set_state(Gst.State.NULL)
    data.playbin.unref()
    return 0


if __name__ == "__main__":
    sys.exit(main())
