import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject

Gst.init(None)

pipeline = Gst.parse_launch(
    "videotestsrc is-live=true ! videoconvert ! x264enc tune=zerolatency ! "
    "ipcpipelinesink name=sink control=unix:/tmp/ipc_socket"
)

pipeline.set_state(Gst.State.PLAYING)

try:
    loop = GObject.MainLoop()
    print("🔵 마스터 프로세스 실행 중 (데이터 전송 중)...")
    loop.run()
except KeyboardInterrupt:
    pipeline.set_state(Gst.State.NULL)
    print("마스터 종료")
