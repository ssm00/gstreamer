import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gst, GObject
import requests
# GStreamer 초기화
Gst.init(None)

# 파이프라인 생성
pipeline = Gst.Pipeline.new("test-pipeline")

# uridecodebin 요소 생성 및 URI 설정
source = Gst.ElementFactory.make("uridecodebin", "source")
resp = requests.get(
        "https://openapi.its.go.kr:9443/cctvInfo"
        "?apiKey=110ad7b8effb40388baaed01a4cd9dd1&type=ex&cctvType=1"
        "&minX=126.8&maxX=127.89&minY=34.9&maxY=35.1&getType=json").json()
uri = resp["response"]["data"][0]["cctvurl"]
source.set_property("uri", uri)

# sink 요소 생성 (예: 오디오 및 비디오 출력)
audio_sink = Gst.ElementFactory.make("autoaudiosink", "audio_sink")
video_sink = Gst.ElementFactory.make("autovideosink", "video_sink")

# 요소들을 파이프라인에 추가
pipeline.add(source)
pipeline.add(audio_sink)
pipeline.add(video_sink)

# pad-added 콜백 함수 정의
def on_pad_added(src, pad):
    caps = pad.get_current_caps()
    name = caps.to_string()
    print(f"새로운 패드 생성: {name}")
    if name.startswith("audio/"):
        sink_pad = audio_sink.get_static_pad("sink")
        if not sink_pad.is_linked():
            pad.link(sink_pad)
    elif name.startswith("video/"):
        sink_pad = video_sink.get_static_pad("sink")
        if not sink_pad.is_linked():
            pad.link(sink_pad)

# pad-added 시그널에 콜백 연결
source.connect("pad-added", on_pad_added)

# 파이프라인 실행
pipeline.set_state(Gst.State.PLAYING)

# 메인 루프 실행
loop = GObject.MainLoop()
try:
    loop.run()
except:
    pass

# 파이프라인 정지 및 정리
pipeline.set_state(Gst.State.NULL)
