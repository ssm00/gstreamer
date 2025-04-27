#!/usr/bin/env python3
"""
basic-tutorial-6.py ― Pad Capabilities (Python port)
GTK UI 없이 콘솔에만 정보를 출력합니다.
"""

import sys, gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst

# ---------- Capabilities 출력 유틸 ----------
def print_field(struct, field_name, value, pfx=""):
    """Gst.Structure.foreach() 용 콜백 (파이썬은 foreach 대신 직접 loop)"""
    print(f"{pfx:}{field_name:>15}: {value.serialize()}")

def print_caps(caps: Gst.Caps, pfx=""):
    if not caps or caps.is_empty():
        print(f"{pfx}EMPTY")
        return
    for i in range(caps.get_size()):
        s = caps.get_structure(i)
        # 구조체 전체를 문자열로 직렬화 → 특수 타입도 안전
        print(f"{pfx}{s.get_name()}: {s.to_string()}")

def factory_longname(factory):
    # overrides 유무에 관계없이 동작
    return getattr(factory, "get_longname",
                   lambda: factory.get_metadata("long-name"))()

# ---------- Pad Template 정보 ----------
def print_pad_templates(factory: Gst.ElementFactory):
    print(f"Pad Templates for {factory_longname(factory)}:")
    if factory.get_num_pad_templates() == 0:
        print("  none\n")
        return

    for tmpl in factory.get_static_pad_templates():
        direction = {Gst.PadDirection.SRC: "SRC",
                     Gst.PadDirection.SINK: "SINK"}.get(tmpl.direction, "UNKNOWN")
        presence = {Gst.PadPresence.ALWAYS: "Always",
                    Gst.PadPresence.SOMETIMES: "Sometimes",
                    Gst.PadPresence.REQUEST: "On request"}.get(tmpl.presence, "UNKNOWN")
        print(f"  {direction} template: '{tmpl.name_template}'")
        print(f"    Availability: {presence}")

        if tmpl.static_caps.string:
            print("    Capabilities:")
            caps = tmpl.get_caps()
            print_caps(caps, "      ")
        print()

# ---------- Pad Capabilities ----------
def print_pad_capabilities(element: Gst.Element, pad_name: str):
    pad = element.get_static_pad(pad_name)
    if not pad:
        print(f"ERROR: pad '{pad_name}' not found", file=sys.stderr)
        return
    caps = pad.get_current_caps()
    if not caps:
        caps = pad.query_caps(None)  # negotiate 전이면 허용 Caps
    print(f"Caps for the {pad_name} pad:")
    print_caps(caps, "      ")

# ---------- 메인 ----------
def main():
    Gst.init(None)

    src_factory  = Gst.ElementFactory.find("audiotestsrc")
    sink_factory = Gst.ElementFactory.find("autoaudiosink")
    if not (src_factory and sink_factory):
        sys.exit("필요한 element factory가 없습니다.")

    # Pad Template 정보 출력
    print_pad_templates(src_factory)
    print_pad_templates(sink_factory)

    # 실제 Element 생성
    source = src_factory.create("source")
    sink   = sink_factory.create("sink")
    pipeline = Gst.Pipeline.new("test-pipeline")
    if not (pipeline and source and sink):
        sys.exit("Element를 생성하지 못했습니다.")

    pipeline.add(source)
    pipeline.add(sink)
    if not source.link(sink):
        sys.exit("Element link 실패")

    # NULL 상태에서 협상된 Caps (없을 수도 있음) 출력
    print("\nIn NULL state:")
    print_pad_capabilities(sink, "sink")

    # PLAYING 진입
    ret = pipeline.set_state(Gst.State.PLAYING)
    if ret == Gst.StateChangeReturn.FAILURE:
        sys.exit("PLAYING 상태로 전환 실패")

    # Bus loop
    bus = pipeline.get_bus()
    terminate = False
    while not terminate:
        msg = bus.timed_pop_filtered(
            Gst.CLOCK_TIME_NONE,
            Gst.MessageType.ERROR | Gst.MessageType.EOS | Gst.MessageType.STATE_CHANGED
        )
        if msg:
            t = msg.type
            if t == Gst.MessageType.ERROR:
                err, dbg = msg.parse_error()
                print(f"Error from {msg.src.get_name()}: {err.message}")
                if dbg:
                    print(f"Debug info: {dbg}")
                terminate = True
            elif t == Gst.MessageType.EOS:
                print("End-Of-Stream")
                terminate = True
            elif t == Gst.MessageType.STATE_CHANGED and msg.src == pipeline:
                old, new, pending = msg.parse_state_changed()
                print(f"\nPipeline state changed {old.value_nick} → {new.value_nick}:")
                print_pad_capabilities(sink, "sink")

    # 정리
    pipeline.set_state(Gst.State.NULL)
    bus.unref()

if __name__ == "__main__":
    main()
