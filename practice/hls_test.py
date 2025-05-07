import gi
import time
import threading

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject

Gst.init(None)

class StreamRecorder:
    def __init__(self, uri):
        self.pipeline = Gst.Pipeline.new("main-pipeline")
        self.uri = uri

        # 기본 요소
        self.src = Gst.ElementFactory.make("uridecodebin", "src")
        self.src.set_property("uri", uri)
        self.tee = Gst.ElementFactory.make("tee", "tee")
        self.queue_display = Gst.ElementFactory.make("queue", "queue_display")
        self.convert_display = Gst.ElementFactory.make("videoconvert", "convert_display")
        self.sink_display = Gst.ElementFactory.make("autovideosink", "sink_display")

        # 요소 추가
        for el in [self.src, self.tee, self.queue_display, self.convert_display, self.sink_display]:
            self.pipeline.add(el)

        # uridecodebin pad 연결 (비디오만 처리)
        self.src.connect("pad-added", self.on_pad_added)

        # 디스플레이 분기 연결
        self.tee.link(self.queue_display)
        self.queue_display.link(self.convert_display)
        self.convert_display.link(self.sink_display)

        # 녹화 관련 변수
        self.recording_elements = []

    def on_pad_added(self, src, pad):
        # src → tee 연결
        sink_pad = self.tee.get_compatible_pad(pad, None)
        if sink_pad and not sink_pad.is_linked():
            pad.link(sink_pad)

    def start(self):
        self.pipeline.set_state(Gst.State.PLAYING)
        print("🔊 스트리밍 재생 중...")

    def stop(self):
        self.pipeline.set_state(Gst.State.NULL)
        print("🛑 파이프라인 종료")

    def start_recording(self, filename="output.mp4"):
        print("⏺ 녹화 시작")
        queue_rec = Gst.ElementFactory.make("queue", "queue_rec")
        convert_rec = Gst.ElementFactory.make("videoconvert", "convert_rec")
        encoder = Gst.ElementFactory.make("x264enc", "encoder")
        muxer = Gst.ElementFactory.make("mp4mux", "muxer")
        sink = Gst.ElementFactory.make("filesink", "sink_rec")
        sink.set_property("location", filename)

        for el in [queue_rec, convert_rec, encoder, muxer, sink]:
            self.pipeline.add(el)

        queue_rec.link(convert_rec)
        convert_rec.link(encoder)
        encoder.link(muxer)
        muxer.link(sink)

        tee_record_src= Gst.Element.request_pad_simple(self.tee, "src_%u")
        sink_pad = queue_rec.get_static_pad("sink")
        tee_record_src.link(sink_pad)

        for el in [queue_rec, convert_rec, encoder, muxer, sink]:
            el.sync_state_with_parent()

        self.recording_elements = [queue_rec, convert_rec, encoder, muxer, sink, tee_record_src]
        print(f"🎥 '{filename}' 저장 중...")

    def stop_recording(self):
        print("⏹ 녹화 중지")
        for el in self.recording_elements[:-1]:  # 마지막은 tee_pad
            el.set_state(Gst.State.NULL)
            self.pipeline.remove(el)
        self.tee.release_request_pad(self.recording_elements[-1])
        self.recording_elements = []

# 사용 예시
if __name__ == "__main__":
    uri = "http://cctvsec.ktict.co.kr/2770/1LCTS8uO1VK7vzG13UDrgeoLz7uEvfQhjQdCwNmlehZnHsSbB7esyTc1Ud6xcdwcYlOhk6ziSWJA9fPRZ2vc1H5yB1F1YO5BJJuYSJxNVbE="  # 🔁 여기에 HLS URL 입력
    recorder = StreamRecorder(uri)
    recorder.start()

    # 5초 후 녹화 시작
    threading.Timer(3, recorder.start_recording).start()

    # 15초 후 녹화 종료 + 전체 종료
    def stop_all():
        recorder.stop_recording()
    threading.Timer(8, stop_all).start()

    # GLib 메인 루프 실행
    loop = GObject.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        recorder.stop()
        loop.quit()
