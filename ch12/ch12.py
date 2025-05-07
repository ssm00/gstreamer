import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

class CustomData:
    def __init__(self):
        self.is_live = False
        self.pipeline = None
        self.loop = None

def cb_message(bus, msg, data):
    msg_type = msg.type
    if msg_type == Gst.MessageType.ERROR:
        err, debug = msg.parse_error()
        print(f"Error: {err.message}")
        data.pipeline.set_state(Gst.State.READY)
        data.loop.quit()

    elif msg_type == Gst.MessageType.EOS:
        data.pipeline.set_state(Gst.State.READY)
        data.loop.quit()

    elif msg_type == Gst.MessageType.BUFFERING:
        if data.is_live:
            return
        percent = msg.parse_buffering()
        print(f"Buffering ({percent}%)", end="\r")
        print(percent)
        if percent < 100:
            data.pipeline.set_state(Gst.State.PAUSED)
        else:
            data.pipeline.set_state(Gst.State.PLAYING)

    elif msg_type == Gst.MessageType.CLOCK_LOST:
        data.pipeline.set_state(Gst.State.PAUSED)
        data.pipeline.set_state(Gst.State.PLAYING)

def main():
    Gst.init(None)
    data = CustomData()

    uri = "https://gstreamer.freedesktop.org/data/media/sintel_trailer-480p.webm"
    pipeline = Gst.parse_launch(f"playbin uri={uri}")
    data.pipeline = pipeline

    ret = pipeline.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        print("Unable to set the pipeline to the playing state.")
        return
    elif ret == Gst.StateChangeReturn.NO_PREROLL:
        print("is live")
        data.is_live = True

    loop = GLib.MainLoop()
    data.loop = loop

    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", cb_message, data)

    try:
        loop.run()
    except:
        pass

    pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":
    main()
