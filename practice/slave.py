import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject

Gst.init(None)

pipeline = Gst.parse_launch(
    "ipcpipelinesrc control=unix:/tmp/ipc_socket ! decodebin ! autovideosink"
)

pipeline.set_state(Gst.State.PLAYING)

try:
    loop = GObject.MainLoop()
    print("🟢 슬레이브 프로세스 실행 중 (데이터 수신 및 출력)...")
    loop.run()
except KeyboardInterrupt:
    pipeline.set_state(Gst.State.NULL)
    print("슬레이브 종료")
