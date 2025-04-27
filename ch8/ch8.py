#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
C tutorial ‘appsrc + tee’ 예제를 gst-python으로 옮긴 버전.
― 16-bit mono @ 44.1 kHz 사인파를 실시간 생성
― 오디오 재생 / 파형 비주얼라이저 / appsink 수집 3-way 분기
"""
import gi, math, sys, ctypes
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GObject, GLib

CHUNK_SIZE   = 1024      # bytes per push (== 512 samples)
SAMPLE_RATE  = 44100     # Hz

class AppSrcTeeDemo:
    def __init__(self):
        Gst.init(None)
        self.loop         = GLib.MainLoop()
        self.num_samples  = 0
        self.a, self.b    = 0.0, 1.0  # waveform state
        self.c, self.d    = 0.0, 1.0

        # ---------- 요소 생성 ----------
        self.appsrc   = Gst.ElementFactory.make("appsrc",        "audio_source")
        self.tee      = Gst.ElementFactory.make("tee",           "tee")
        self.q_audio  = Gst.ElementFactory.make("queue",         "audio_q")
        self.conv1    = Gst.ElementFactory.make("audioconvert",  "conv1")
        self.resample = Gst.ElementFactory.make("audioresample", "resample")
        self.sink_aud = Gst.ElementFactory.make("autoaudiosink", "audio_sink")

        self.q_vis    = Gst.ElementFactory.make("queue",         "video_q")
        self.conv2    = Gst.ElementFactory.make("audioconvert",  "conv2")
        self.scope    = Gst.ElementFactory.make("wavescope",     "scope")
        self.videoconv= Gst.ElementFactory.make("videoconvert",  "vconv")
        self.sink_vid = Gst.ElementFactory.make("autovideosink", "video_sink")

        self.q_app    = Gst.ElementFactory.make("queue",         "app_q")
        self.appsink  = Gst.ElementFactory.make("appsink",       "app_sink")

        self.pipeline = Gst.Pipeline.new("pipeline")

        if not all([self.pipeline, self.appsrc, self.tee, self.q_audio, self.conv1,
                    self.resample, self.sink_aud, self.q_vis, self.conv2, self.scope,
                    self.videoconv, self.sink_vid, self.q_app, self.appsink]):
            raise RuntimeError("요소 생성 실패")

        # ---------- wavescope 설정 ----------
        self.scope.set_property("shader", 0)
        self.scope.set_property("style",  0)

        # ---------- appsrc caps 및 시그널 ----------
        caps = Gst.Caps.from_string(f"audio/x-raw,format=S16LE,rate={SAMPLE_RATE},channels=1")
        self.appsrc.set_property("caps", caps)
        self.appsrc.set_property("format", Gst.Format.TIME)
        self.appsrc.connect("need-data",   self.on_need_data)
        self.appsrc.connect("enough-data", self.on_enough_data)

        # ---------- appsink 설정 ----------
        self.appsink.set_property("emit-signals", True)
        self.appsink.set_property("caps", caps)
        self.appsink.connect("new-sample", self.on_new_sample)

        # ---------- 파이프라인 조립  ----------
        self.pipeline.add(self.appsrc)
        self.pipeline.add(self.tee)
        self.pipeline.add(self.q_audio)
        self.pipeline.add(self.conv1)
        self.pipeline.add(self.resample)
        self.pipeline.add(self.sink_aud)
        self.pipeline.add(self.q_vis)
        self.pipeline.add(self.conv2)
        self.pipeline.add(self.scope)
        self.pipeline.add(self.videoconv)
        self.pipeline.add(self.sink_vid)
        self.pipeline.add(self.q_app)
        self.pipeline.add(self.appsink)

        #--(Always pads)는 연결
        self.appsrc.link(self.tee)

        self.q_audio.link(self.conv1)
        self.conv1.link(self.resample)
        self.resample.link(self.sink_aud)

        self.q_vis.link(self.conv2)
        self.conv2.link(self.scope)
        self.scope.link(self.videoconv)
        self.videoconv.link(self.sink_vid)

        self.q_app.link(self.appsink)
        # ---------- tee 요청 pad 수동 연결 ----------
        tmpl = self.tee.get_pad_template("src_%u")
        def link_branch(tee_pad, queue):
            q_sink = queue.get_static_pad("sink")
            if tee_pad.link(q_sink) != Gst.PadLinkReturn.OK:
                raise RuntimeError("Tee→Queue pad 링크 실패")

        link_branch(self.tee.request_pad(tmpl, None, None), self.q_audio)
        link_branch(self.tee.request_pad(tmpl, None, None), self.q_vis)
        link_branch(self.tee.request_pad(tmpl, None, None), self.q_app)

        # ---------- Bus 오류 처리 ----------
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self.on_error)

    # -------------------- Signal 콜백 --------------------
    def on_need_data(self, src, length):
        # main-loop idle 에 등록해 지속 push
        if not hasattr(self, "_source_id"):
            self._source_id = GLib.idle_add(self.push_data)

    def on_enough_data(self, src):
        if hasattr(self, "_source_id"):
            GLib.source_remove(self._source_id)
            del self._source_id

    def on_new_sample(self, sink):
        sample = sink.emit("pull-sample")
        if sample:
            sys.stdout.write("*"); sys.stdout.flush()
            sample.unref()
            return Gst.FlowReturn.OK
        return Gst.FlowReturn.ERROR

    def on_error(self, bus, msg):
        err, dbg = msg.parse_error()
        print(f"\n[ERROR] {err.message}\n{dbg or ''}", file=sys.stderr)
        self.loop.quit()

    # -------------------- 오디오 버퍼 push --------------------
    def push_data(self):
        buf = Gst.Buffer.new_allocate(None, CHUNK_SIZE, None)
        n_samples = CHUNK_SIZE // 2        # 16-bit
        # 타임스탬프/Duration 설정
        buf.pts = buf.dts = self.num_samples * Gst.SECOND // SAMPLE_RATE
        buf.duration     = n_samples  * Gst.SECOND // SAMPLE_RATE

        # waveform 생성 (C 버전과 동일 공식)
        success, mapinfo = buf.map(Gst.MapFlags.WRITE)
        if not success:
            return False
        raw = (ctypes.c_int16 * n_samples).from_address(mapinfo.data)
        self.c += self.d
        self.d -= self.c / 1000
        freq = 1100 + 1000 * self.d
        for i in range(n_samples):
            self.a += self.b
            self.b -= self.a / freq
            raw[i] = int(500 * self.a)
        buf.unmap(mapinfo)

        self.num_samples += n_samples
        # appsrc 로 푸시
        ret = self.appsrc.emit("push-buffer", buf)
        return ret == Gst.FlowReturn.OK

    # -------------------- 실행 --------------------
    def run(self):
        self.pipeline.set_state(Gst.State.PLAYING)
        try:
            self.loop.run()
        finally:
            self.pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":
    GObject.threads_init()
    AppSrcTeeDemo().run()
