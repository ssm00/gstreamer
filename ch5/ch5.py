#!/usr/bin/env python3
"""
GTK + GStreamer ‘playbin’ 데모
— 재생/일시정지/정지 버튼, 시크 슬라이더, 스트림 메타데이터 표시
"""

import gi, sys
gi.require_version("Gst", "1.0")
gi.require_version("Gtk", "3.0")                 # GTK 3 예제 (4도 유사)
from gi.repository import Gst, Gtk, GLib

GST_SEC = Gst.SECOND  # 읽기 편하게 상수 alias


class Player:

    def __init__(self) -> None:

        Gst.init(None)
        Gtk.init(None)
        self.playbin: Gst.Element = Gst.ElementFactory.make("playbin", "playbin")

        self.playbin.set_state(Gst.State.NULL)
        self.playbin.set_state(Gst.State.READY)
        self.playbin.set_state(Gst.State.PAUSED)
        self.playbin.set_state(Gst.State.PLAYING)
        if not self.playbin:
            print("playbin 생성 실패", file=sys.stderr)
            sys.exit(1)

        # --------- 비디오 싱크: gtkglsink → gtksink fallback ----------
        videosink = Gst.ElementFactory.make("glsinkbin", "glsinkbin")
        gtkglsink = Gst.ElementFactory.make("gtkglsink", "gtkglsink")
        if videosink and gtkglsink:
            videosink.set_property("sink", gtkglsink)
            self.sink_widget = gtkglsink.get_property("widget")
        else:
            # OpenGL 사용 불가 시
            videosink = Gst.ElementFactory.make("gtksink", "gtksink")
            self.sink_widget = videosink.get_property("widget")

        self.playbin.set_property(
            "uri",
            "https://gstreamer.freedesktop.org/data/media/sintel_trailer-480p.webm",
        )
        self.playbin.set_property("video-sink", videosink)

        # -------------- GUI --------------
        self._build_ui()

        # -------------- Bus 연결 --------------
        # 버스에 시그널 감시 설
        bus = self.playbin.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        bus.connect("message::eos", self._on_eos)
        bus.connect("message::state-changed", self._on_state_changed)
        bus.connect("message::application", self._on_app_msg)

        # playbin 태그 변경 시 application 메시지 발생
        for sig in ("video-tags-changed", "audio-tags-changed", "text-tags-changed"):
            self.playbin.connect(sig, self._on_tags_changed)

        # 1 초마다 UI 새로고침
        GLib.timeout_add_seconds(1, self._refresh_ui)

        # 재생
        if self.playbin.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            print("PLAYING 전환 실패", file=sys.stderr)
            sys.exit(1)

    # ---------- UI 만들기 ----------
    def _build_ui(self) -> None:
        self.window = Gtk.Window(title="GStreamer GTK Player")
        self.window.connect("delete-event", self._on_delete)

        # 컨트롤 버튼
        play_btn = Gtk.Button.new_from_icon_name("media-playback-start", Gtk.IconSize.SMALL_TOOLBAR)
        pause_btn = Gtk.Button.new_from_icon_name("media-playback-pause", Gtk.IconSize.SMALL_TOOLBAR)
        stop_btn = Gtk.Button.new_from_icon_name("media-playback-stop", Gtk.IconSize.SMALL_TOOLBAR)
        play_btn.connect("clicked", lambda *_: self.playbin.set_state(Gst.State.PLAYING))
        pause_btn.connect("clicked", lambda *_: self.playbin.set_state(Gst.State.PAUSED))
        stop_btn.connect("clicked", lambda *_: self.playbin.set_state(Gst.State.READY))

        # 슬라이더
        self.slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.slider.set_draw_value(False)
        self.slider_update_id = self.slider.connect("value-changed", self._on_slider_change)

        # 스트림 정보 뷰어
        self.streams_view = Gtk.TextView(editable=False)
        self.streams_buf = self.streams_view.get_buffer()

        # 레이아웃
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        for b in (play_btn, pause_btn, stop_btn):  # type: ignore[arg-type]
            controls.pack_start(b, False, False, 0)
        controls.pack_start(self.slider, True, True, 0)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        hbox.pack_start(self.sink_widget, True, True, 0)
        hbox.pack_start(self.streams_view, False, False, 0)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.pack_start(hbox, True, True, 0)
        vbox.pack_start(controls, False, False, 0)

        self.window.add(vbox)
        self.window.set_default_size(640, 480)
        self.window.show_all()

        # 재생 위치·길이 캐시
        self.duration = Gst.CLOCK_TIME_NONE
        self.state: Gst.State = Gst.State.NULL

    # ---------- 콜백 ----------
    def _on_delete(self, *_):
        self.playbin.set_state(Gst.State.NULL)
        Gtk.main_quit()

    def _on_slider_change(self, range_: Gtk.Range):
        val = range_.get_value()
        self.playbin.seek_simple(
            Gst.Format.TIME,
            Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT,
            int(val * GST_SEC),
        )

    def _refresh_ui(self):
        if self.state < Gst.State.PAUSED:  # READY 또는 NULL
            return True

        # 길이 쿼리
        ok, self.duration = self.playbin.query_duration(Gst.Format.TIME)
        if ok and self.duration != Gst.CLOCK_TIME_NONE:
            self.duration = self.duration
            self.slider.set_range(0, self.duration / GST_SEC)

        # 현재 위치
        ok, current = self.playbin.query_position(Gst.Format.TIME)
        if ok and self.duration != Gst.CLOCK_TIME_NONE:
            self.slider.handler_block(self.slider_update_id)
            self.slider.set_value(current / GST_SEC)
            self.slider.handler_unblock(self.slider_update_id)
        return True  # 계속 호출

    # ----- Bus 메시지 -----
    def _on_error(self, _bus, msg):
        err, dbg = msg.parse_error()
        print(f"[ERROR] {err.message}\n{dbg or ''}", file=sys.stderr)
        self.playbin.set_state(Gst.State.READY)

    def _on_eos(self, *_):
        print("End-of-Stream")
        self.playbin.set_state(Gst.State.READY)

    def _on_state_changed(self, _bus, msg):
        if msg.src is self.playbin:
            old, new, _ = msg.parse_state_changed()
            self.state = new
            print(f"State → {Gst.Element.state_get_name(new)}")
            if old == Gst.State.READY and new == Gst.State.PAUSED:
                self._refresh_ui()  # 첫 PAUSED 시 즉시 업데이트

    # 태그 콜백 → application 메시지
    def _on_tags_changed(self, _playbin, _stream):
        self.playbin.post_message(
            Gst.Message.new_application(
                self.playbin, Gst.Structure.new_empty("tags-changed")
            )
        )

    def _on_app_msg(self, _bus, msg):
        if msg.get_structure().get_name() == "tags-changed":
            self._analyze_streams()

    # 스트림 메타데이터 분석
    def _analyze_streams(self):
        buf = self.streams_buf
        buf.set_text("")  # clear

        def append(txt: str):
            buf.insert(buf.get_end_iter(), txt)

        n_vid = self.playbin.get_property("n-video")
        n_aud = self.playbin.get_property("n-audio")
        n_txt = self.playbin.get_property("n-text")

        for i in range(n_vid):
            tags = self.playbin.emit("get-video-tags", i)
            if tags:
                codec = tags.get_string(Gst.TAG_VIDEO_CODEC)[1] or "unknown"
                append(f"video stream {i}:\n  codec: {codec}\n")

        for i in range(n_aud):
            tags = self.playbin.emit("get-audio-tags", i)
            if tags:
                append(f"\naudio stream {i}:\n")
                codec = tags.get_string(Gst.TAG_AUDIO_CODEC)[1]
                lang = tags.get_string(Gst.TAG_LANGUAGE_CODE)[1]
                rate = tags.get_uint(Gst.TAG_BITRATE)[1]
                if codec:
                    append(f"  codec: {codec}\n")
                if lang:
                    append(f"  language: {lang}\n")
                if rate:
                    append(f"  bitrate: {rate}\n")

        for i in range(n_txt):
            tags = self.playbin.emit("get-text-tags", i)
            if tags:
                append(f"\nsubtitle stream {i}:\n")
                lang = tags.get_string(Gst.TAG_LANGUAGE_CODE)[1]
                if lang:
                    append(f"  language: {lang}\n")

    # ---------- 실행 ----------
    def run(self):
        Gtk.main()


if __name__ == "__main__":

    Player().run()
