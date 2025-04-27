#!/usr/bin/env python3
import sys
import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject

class CustomData:
    def __init__(self):
        self.pipeline = None
        self.source = None
        self.convert = None
        self.resample = None
        self.sink = None

def pad_added_handler(src, new_pad, data):
    """uridecodebin이 새 pad를 만들었을 때 호출되는 콜백"""
    sink_pad = data.convert.get_static_pad('sink')
    if sink_pad.is_linked():
        print("Already linked. Ignoring.")
        return

    # 새 pad의 caps 정보 얻기
    new_pad_caps = new_pad.query_caps(None)
    new_pad_struct = new_pad_caps.get_structure(0)
    new_pad_type = new_pad_struct.get_name()

    # raw 오디오가 아니면 무시
    if not new_pad_type.startswith('audio/x-raw'):
        print(f"It has type '{new_pad_type}' which is not raw audio. Ignoring.")
        return

    # pad 간 연결 시도
    ret = new_pad.link(sink_pad)
    if ret != Gst.PadLinkReturn.OK:
        print(f"Type is '{new_pad_type}' but link failed.")
    else:
        print(f"Link succeeded (type '{new_pad_type}').")

def main():
    Gst.init(None)

    data = CustomData()

    # 요소 생성
    data.source   = Gst.ElementFactory.make('uridecodebin',   'source')
    data.convert  = Gst.ElementFactory.make('audioconvert',   'convert')
    data.resample = Gst.ElementFactory.make('audioresample',  'resample')
    data.sink     = Gst.ElementFactory.make('autoaudiosink',  'sink')
    data.pipeline = Gst.Pipeline.new('test-pipeline')

    # 생성 실패 체크
    if not data.pipeline or not data.source or not data.convert \
       or not data.resample or not data.sink:
        sys.stderr.write("Not all elements could be created.\n")
        sys.exit(1)

    # 파이프라인에 요소 추가
    data.pipeline.add(data.source)
    data.pipeline.add(data.convert)
    data.pipeline.add(data.resample)
    data.pipeline.add(data.sink)

    # 고정 연결
    if not data.convert.link(data.resample) or not data.resample.link(data.sink):
        sys.stderr.write("Elements could not be linked.\n")
        data.pipeline.set_state(Gst.State.NULL)
        sys.exit(1)

    # 재생할 URI 설정
    data.source.set_property('uri', 'https://gstreamer.freedesktop.org/data/media/sintel_trailer-480p.webm')

    # pad-added 시그널 연결
    data.source.connect('pad-added', pad_added_handler, data)

    # 재생 시작
    ret = data.pipeline.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        sys.stderr.write("Unable to set the pipeline to the playing state.\n")
        data.pipeline.set_state(Gst.State.NULL)
        sys.exit(1)
 
    # 버스 메시지 폴링 루프
    bus = data.pipeline.get_bus()
    terminate = False
    while not terminate:
        msg = bus.timed_pop_filtered(
            Gst.CLOCK_TIME_NONE,
            Gst.MessageType.STATE_CHANGED | Gst.MessageType.ERROR | Gst.MessageType.EOS
        )
        if msg:
            t = msg.type
            if t == Gst.MessageType.ERROR:
                err, debug = msg.parse_error()
                sys.stderr.write(f"Error received from element {msg.src.get_name()}: {err.message}\n")
                sys.stderr.write(f"Debugging information: {debug}\n")
                terminate = True
            elif t == Gst.MessageType.EOS:
                print("End-Of-Stream reached.")
                terminate = True
            elif t == Gst.MessageType.STATE_CHANGED:
                if(msg.src == data.pipeline):
                    old, new, _ = msg.parse_state_changed()
                    print(f"Pipeline state changed from {Gst.Element.state_get_name(old)} to {Gst.Element.state_get_name(new)}.")
            else:
                print("Unexpected message received.")

    # 정리
    data.pipeline.set_state(Gst.State.NULL)
    sys.exit(0)

if __name__ == '__main__':
    main()
