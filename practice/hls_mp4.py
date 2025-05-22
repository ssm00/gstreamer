import gi, threading, requests
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject
Gst.init(None)

class StreamRecorder:

    def __init__(self, uri, out_pattern="clip-%03d.mp4"):
        self.uri = uri
        self.pipeline = Gst.Pipeline.new("main")
        self._rec_pad = None          # tee → rec 브랜치 pad

        # ─── Elements ──────────────────────────────────────────
        self.src = Gst.ElementFactory.make("uridecodebin", "src")
        self.src.set_property("uri", uri)
        self.src.connect("pad-added", self._on_pad_added)

        self.tee = Gst.ElementFactory.make("tee")

        # 디스플레이
        qd, cvd, sinkd = (Gst.ElementFactory.make("queue"),
                          Gst.ElementFactory.make("videoconvert"),
                          Gst.ElementFactory.make("autovideosink"))
        # 녹화
        qr = Gst.ElementFactory.make("queue"); qr.set_property("flush-on-eos", False)
        cvr = Gst.ElementFactory.make("videoconvert")
        enc = Gst.ElementFactory.make("x264enc"); enc.set_property("tune", "zerolatency")
        parser = Gst.ElementFactory.make("h264parse")
        self.split = Gst.ElementFactory.make("splitmuxsink")
        self.split.set_property("location", out_pattern)
        self.split.set_property("muxer-factory", "mp4mux")
        self.split.set_property("async-finalize", True)

        # ─── Add & Link static parts ───────────────────────────
        for e in (self.src, self.tee, qd, cvd, sinkd,
                  qr, cvr, enc, parser, self.split):
            self.pipeline.add(e)

        # 모니터 브랜치
        qd.link(cvd); cvd.link(sinkd)

        # 녹화 브랜치 (tee pad는 start_recording 때 연결)
        qr.link(cvr); cvr.link(enc); enc.link(parser); parser.link(self.split)

    # pad-added: src → tee
    def _on_pad_added(self, _, pad):
        if pad.get_current_caps().to_string().startswith("video/"):
            pad.link(self.tee.request_pad_simple("src_%u"))

    # ─── Pipeline control ────────────────────────────────────
    def start_playback(self):
        # tee → 모니터 pad
        disp_pad = self.tee.request_pad_simple("src_%u")
        disp_pad.link(self.pipeline.get_by_name("queue0").get_static_pad("sink"))
        self.pipeline.set_state(Gst.State.PLAYING)
        print("▶ PLAY")

    def stop_playback(self):
        self.pipeline.set_state(Gst.State.NULL)
        print("■ STOP")

    # ─── Record control ──────────────────────────────────────
    def start_recording(self):
        if self._rec_pad:
            print("녹화 중입니다.")
            return
        self._rec_pad = self.tee.request_pad_simple("src_%u")
        self._rec_pad.link(self.pipeline.get_by_name("queue1").get_static_pad("sink"))
        print("⏺ REC ON")

    def stop_recording(self):
        if not self._rec_pad:
            print("녹화가 켜져 있지 않습니다.")
            return
        # 1) 해당 브랜치 BLOCK
        def _block_cb(pad, _info):
            pad.send_event(Gst.Event.new_eos())
            return Gst.PadProbeReturn.REMOVE
        self._rec_pad.add_probe(Gst.PadProbeType.BLOCK_DOWNSTREAM, _block_cb)

        # 2) splitmuxsink 가 파일 닫을 때까지 대기
        bus = self.pipeline.get_bus()
        bus.timed_pop_filtered(Gst.CLOCK_TIME_NONE,
                               Gst.MessageType.EOS | Gst.MessageType.ERROR)

        # 3) 브랜치 해제
        self._rec_pad.unlink(self.pipeline.get_by_name("queue1").get_static_pad("sink"))
        self.tee.release_request_pad(self._rec_pad)
        self._rec_pad = None
        print("⏹ REC OFF (파일 닫힘 완료)")

# ─── Demo run ────────────────────────────────────────────────
if __name__ == "__main__":
    resp = requests.get(
        "https://openapi.its.go.kr:9443/cctvInfo"
        "?apiKey=110ad7b8effb40388baaed01a4cd9dd1&type=ex&cctvType=1"
        "&minX=126.8&maxX=127.89&minY=34.9&maxY=35.1&getType=json").json()
    uri = resp["response"]["data"][0]["cctvurl"]

    rec = StreamRecorder(uri)
    rec.start_playback()

    # 2초 뒤 녹화 ON, 8초 뒤 녹화 OFF
    threading.Timer(2, rec.start_recording).start()
    threading.Timer(4, rec.stop_recording).start()

    loop = GObject.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        rec.stop_playback()
        loop.quit()
