#!/usr/bin/env python3
"""
basic-tutorial-7.py — Tee branches (audio + visual) in Python
"""

import sys, gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst


def link_many(*elements) -> bool:
    """C의 gst_element_link_many()와 같은 역할 (PadLinkReturn 검사)."""
    for src, sink in zip(elements, elements[1:]):
        if src.link(sink) != Gst.PadLinkReturn.OK:
            print(f"link failed: {src.get_name()} → {sink.get_name()}")
            return False
    return True
# ---------- 메인 ----------
def main():
    Gst.init(None)

    # 1. 요소 생성
    audio_source   = Gst.ElementFactory.make("audiotestsrc", "audio_source")
    tee            = Gst.ElementFactory.make("tee", "tee")
    audio_queue    = Gst.ElementFactory.make("queue", "audio_queue")
    audio_convert  = Gst.ElementFactory.make("audioconvert", "audio_convert")
    audio_resample = Gst.ElementFactory.make("audioresample", "audio_resample")
    audio_sink     = Gst.ElementFactory.make("autoaudiosink", "audio_sink")
    video_queue    = Gst.ElementFactory.make("queue", "video_queue")
    visual         = Gst.ElementFactory.make("wavescope", "visual")
    video_convert  = Gst.ElementFactory.make("videoconvert", "csp")
    video_sink     = Gst.ElementFactory.make("autovideosink", "video_sink")
    pipeline       = Gst.Pipeline.new("test-pipeline")

    if not all([pipeline, audio_source, tee, audio_queue, audio_convert, audio_resample,
                audio_sink, video_queue, visual, video_convert, video_sink]):
        sys.exit("필요한 요소를 만들지 못했습니다.")

    # 2. 속성 설정
    audio_source.set_property("freq", 215.0)                     # 사인파 주파수 :contentReference[oaicite:1]{index=1}
    visual.set_property("shader", 0)
    visual.set_property("style", 1)                              # wavescope 옵션 :contentReference[oaicite:2]{index=2}

    # 3. 파이프라인 구성 & 자동 링크
    for element in (
            audio_source, tee,
            audio_queue, audio_convert, audio_resample, audio_sink,
            video_queue, visual, video_convert, video_sink
    ):
        pipeline.add(element)
    audio_source.link(tee)
    audio_queue.link(audio_convert)
    audio_convert.link(audio_resample)
    audio_resample.link(audio_sink)

    video_queue.link(visual)
    visual.link(video_convert)
    video_convert.link(video_sink)

    # 4. Tee ↔ Queue 수동 링크 (request pads)
    tee_audio_pad = Gst.Element.request_pad_simple(tee, "src_%u")
    print(f"Request pad {tee_audio_pad.get_name()} for audio")
    tee_video_pad = Gst.Element.request_pad_simple(tee, "src_%u")
    print(f"Request pad {tee_video_pad.get_name()} for video")

    queue_audio_pad = audio_queue.get_static_pad("sink")
    queue_video_pad = video_queue.get_static_pad("sink")

    if (tee_audio_pad.link(queue_audio_pad) != Gst.PadLinkReturn.OK or
        tee_video_pad.link(queue_video_pad) != Gst.PadLinkReturn.OK):
        sys.exit("Tee-Queue 패드 링크 실패")                       # :contentReference[oaicite:4]{index=4}

    # 5. 재생 시작
    pipeline.set_state(Gst.State.PLAYING)

    # 6. 버스 대기 (EOS/ERROR)
    bus = pipeline.get_bus()
    while True:
        msg = bus.timed_pop_filtered(
            Gst.CLOCK_TIME_NONE,
            Gst.MessageType.ERROR | Gst.MessageType.EOS
        )
        if not msg:
            continue
        t = msg.type
        if t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print(f"Error: {err.message}")
            if dbg: print(dbg)
        else:
            print("EOS reached")
        msg = None
        break

    # 7. 정리
    tee.release_request_pad(tee_audio_pad)
    tee.release_request_pad(tee_video_pad)
    pipeline.set_state(Gst.State.NULL)

if __name__ == "__main__":
    main()
