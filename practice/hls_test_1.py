import gi
gi.require_version('Gst', '1.0')
gi.require_version('GObject', '2.0')
from gi.repository import Gst, GObject
import requests

Gst.init(None)  # Initialize GStreamer

class HLSRecorder:
    def __init__(self, hls_url, output_pattern="recording_%05d.mp4"):
        # Create GStreamer pipeline
        self.pipeline = Gst.Pipeline.new("hls_recorder_pipeline")
        if not self.pipeline:
            raise RuntimeError("Failed to create GStreamer pipeline")

        # Elements for HLS source and decoding
        self.src = Gst.ElementFactory.make("souphttpsrc", "src")
        self.hlsdemux = Gst.ElementFactory.make("hlsdemux", "hlsdemux")
        self.decodebin = Gst.ElementFactory.make("decodebin", "decodebin")
        if not self.src or not self.hlsdemux or not self.decodebin:
            raise RuntimeError("Failed to create source/demux/decodebin elements")

        self.src.set_property("location", hls_url)
        # For HLS, enable continuous buffering if needed (optional):
        # self.src.set_property("keep-alive", True)

        # Elements for video processing
        self.videoconvert = Gst.ElementFactory.make("videoconvert", "videoconvert")
        self.tee = Gst.ElementFactory.make("tee", "tee")
        if not self.videoconvert or not self.tee:
            raise RuntimeError("Failed to create videoconvert or tee")

        # Elements for playback branch
        self.queue_display = Gst.ElementFactory.make("queue", "queue_display")
        self.videosink = Gst.ElementFactory.make("autovideosink", "videosink")
        if not self.queue_display or not self.videosink:
            raise RuntimeError("Failed to create display queue or video sink")
        # Optionally, set queue properties for display (e.g., leaky or max sizes) if needed:
        # self.queue_display.set_property("max-size-buffers", 0)
        # self.queue_display.set_property("max-size-bytes", 0)
        # self.queue_display.set_property("max-size-time", 0)

        # Elements for recording branch
        self.queue_record = Gst.ElementFactory.make("queue", "queue_record")
        self.valve = Gst.ElementFactory.make("valve", "record_valve")
        self.x264enc = Gst.ElementFactory.make("x264enc", "x264enc")
        self.h264parse = Gst.ElementFactory.make("h264parse", "h264parse")
        self.splitmuxsink = Gst.ElementFactory.make("splitmuxsink", "splitmuxsink")
        if not self.queue_record or not self.valve or not self.x264enc or not self.h264parse or not self.splitmuxsink:
            raise RuntimeError("Failed to create one or more recording elements")
        # Configure recording elements
        self.valve.set_property("drop", True)  # start with valve closed (not recording)
        # Forward caps (sticky events) even when drop=TRUE, to ensure encoder can negotiate format
        if self.valve.find_property("drop-mode") is not None:
            self.valve.set_property("drop-mode", "forward-sticky-events")
        # Configure x264 encoder for low latency and fast keyframe insertion
        self.x264enc.set_property("tune", "zerolatency")  # reduce latency (no B-frames):contentReference[oaicite:6]{index=6}
        self.x264enc.set_property("key-int-max", 30)      # force keyframe at least every 30 frames (around 1s, for frequent GOPs)
        # Optionally, we could set bitrate or speed-preset on x264enc if needed:
        # self.x264enc.set_property("bitrate", 2000)  # in kbps, for example
        # self.x264enc.set_property("speed-preset", "ultrafast")
        # Configure H264 parser to put SPS/PPS in each keyframe (ensures each MP4 segment has headers)
        self.h264parse.set_property("config-interval", 1)
        # Configure splitmuxsink for MP4 output
        self.splitmuxsink.set_property("location", output_pattern)
        self.splitmuxsink.set_property("muxer", Gst.ElementFactory.make("mp4mux", None))  # use MP4 muxer (usually default)
        # Ensure splitmuxsink finalizes files without blocking the pipeline
        self.splitmuxsink.set_property("async-handling", True)  # finalize in background:contentReference[oaicite:7]{index=7}
        # We only record video stream (no audio); splitmuxsink will automatically mux only the video track.
        # No explicit max-size-time or max-size-bytes is set; files will split only when we trigger via signals.

        # Add all elements to the pipeline
        elements = [
            self.src, self.hlsdemux, self.decodebin,
            self.videoconvert, self.tee,
            self.queue_display, self.videosink,
            self.queue_record, self.valve, self.x264enc, self.h264parse, self.splitmuxsink
        ]
        for elem in elements:
            self.pipeline.add(elem)

        # Link static elements where possible
        # Source -> HLS demux
        if not self.src.link(self.hlsdemux):
            raise RuntimeError("Failed to link src -> hlsdemux")
        # HLS demux will output the stream dynamically, so we connect to its pad-added signal
        self.hlsdemux.connect("pad-added", self._on_hls_pad_added)
        # Once HLS demux outputs data, we link to decodebin (which will also link dynamically)
        # decodebin will in turn output raw video on pad-added signal

        # Link post-decode elements (will complete linking in decodebin pad-added callback)
        # videoconvert -> tee
        if not self.videoconvert.link(self.tee):
            raise RuntimeError("Failed to link videoconvert -> tee")
        # Tee branches: tee -> queue_display -> videosink
        if not self.tee.link(self.queue_display):
            raise RuntimeError("Failed to link tee -> queue_display")
        if not self.queue_display.link(self.videosink):
            raise RuntimeError("Failed to link queue_display -> videosink")
        # tee -> queue_record -> valve -> x264enc -> h264parse -> splitmuxsink
        if not self.tee.link(self.queue_record):
            raise RuntimeError("Failed to link tee -> queue_record (record branch)")
        if not self.queue_record.link(self.valve):
            raise RuntimeError("Failed to link queue_record -> valve")
        if not self.valve.link(self.x264enc):
            raise RuntimeError("Failed to link valve -> x264enc")
        if not self.x264enc.link(self.h264parse):
            raise RuntimeError("Failed to link x264enc -> h264parse")
        if not self.h264parse.link(self.splitmuxsink):
            raise RuntimeError("Failed to link h264parse -> splitmuxsink")

        # Connect decodebin pad-added to handle dynamic output pads
        self.decodebin.connect("pad-added", self._on_decode_pad_added)

        # Set up bus message handler for errors/EOS
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)

    def _on_hls_pad_added(self, demux, pad):
        """Callback when hlsdemux provides a new pad (e.g., the TS stream pad)."""
        # We expect the HLS demux to output the combined stream (likely MPEG-TS) on this pad.
        # Link that pad to the sink of decodebin to let decodebin handle demuxing/decode.
        if pad.get_current_caps():
            caps_struct = pad.get_current_caps().get_structure(0)
            pad_type = caps_struct.get_name()
        else:
            pad_type = pad.query_caps(None).get_structure(0).get_name()
        # Only link if this is video or main content (could be "video/MP2T" for MPEG-TS)
        # Typically, hlsdemux will output "application/x-hls" or "video/mp2t".
        if pad_type.startswith("application/x-hls") or pad_type.startswith("video/mp2t") or pad_type == "video/mpegts":
            decode_sink = self.decodebin.get_static_pad("sink")
            if decode_sink is not None:
                pad.link(decode_sink)

    def _on_decode_pad_added(self, decodebin, pad):
        """Callback when decodebin outputs a new decoded pad (raw video or audio)."""
        caps = pad.get_current_caps()
        struct = caps.get_structure(0)
        pad_type = struct.get_name()
        if pad_type.startswith("video/"):  # It's raw video
            # Link decodebin's video output to videoconvert -> (then to tee and onward)
            if not pad.link(self.videoconvert.get_static_pad("sink")) == Gst.PadLinkReturn.OK:
                print("Warning: Failed to link decoded video pad to videoconvert")
        elif pad_type.startswith("audio/"):  # It's audio (we don't need audio)
            # Link audio pad to fakesink to consume it (avoid stalling decodebin)
            fakesink = Gst.ElementFactory.make("fakesink", None)
            if fakesink:
                self.pipeline.add(fakesink)
                fakesink.sync_state_with_parent()  # ensure state matches pipeline
                pad.link(fakesink.get_static_pad("sink"))
            else:
                print("Warning: Failed to create fakesink for audio stream; audio will be ignored without linking")

    def _on_bus_message(self, bus, msg):
        """Handle messages on the pipeline's bus (errors, EOS, etc.)."""
        t = msg.type
        if t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            print(f"[ERROR] {err}: {dbg}")
            # On error, stop the pipeline and quit the main loop
            self.stop_pipeline()
        elif t == Gst.MessageType.EOS:
            print("[INFO] End-of-stream received (pipeline stopped or HLS stream ended).")
            # End-of-stream handling: we can quit the loop if it’s not intentional
            self.stop_pipeline()
        # We also listen for fragment close events from splitmuxsink (optional)
        elif t == Gst.MessageType.ELEMENT:
            # splitmuxsink posts 'splitmuxsink-fragment-closed' messages when a segment file is finalized
            struct = msg.get_structure()
            if struct and struct.get_name() == "splitmuxsink-fragment-closed":
                location = struct.get_string("location")
                if location:
                    print(f"[INFO] Finished writing recording file: {location}")

    def start_pipeline(self):
        """Start the pipeline (begin playback of the stream)."""
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Failed to start the GStreamer pipeline")
        print("[INFO] Pipeline started, playing HLS stream...")

    def stop_pipeline(self):
        """Stop the pipeline and clean up (to be called on program exit or error)."""
        # Send EOS to pipeline to flush and end cleanly
        self.pipeline.send_event(Gst.Event.new_eos())
        # Set state to NULL (free resources)
        self.pipeline.set_state(Gst.State.NULL)
        print("[INFO] Pipeline stopped.")

    def start_recording(self):
        """Start recording: open the valve to allow data into the recording branch."""
        self.valve.set_property("flush", True)
        if not self.valve.get_property("drop"):
            print("[INFO] Recording is already active.")
            return
        # Open the valve to start sending buffers to the encoder and muxer
        self.valve.set_property("drop", False)
        print("[INFO] Recording started.")

    def stop_recording(self):
        if self.valve.get_property("drop"):
            print("[INFO] Recording is not active.")
            return

        print("[INFO] Stopping recording…")

        # ① 즉시 조각 닫기
        self.splitmuxsink.emit("split-now")


        # ② 조각 파일이 실제로 닫힐 때까지 대기
        bus = self.pipeline.get_bus()
        while True:
            msg = bus.timed_pop_filtered(
                Gst.SECOND * 10,
                Gst.MessageType.ELEMENT | Gst.MessageType.ERROR
            )
            if not msg:
                print("…waiting fragment close")
                continue

            if msg.type == Gst.MessageType.ERROR:
                err, dbg = msg.parse_error()
                print(f"[ERROR] {err}: {dbg}")
                break

            s = msg.get_structure()
            if s and s.get_name() == "splitmuxsink-fragment-closed":
                location = s.get_string("location")
                print(f"[INFO] Recording file finalized: {location}")
                break

        # ③ 이제 밸브를 닫아 스트림 차단
        self.valve.set_property("drop", True)
        print("[INFO] Recording stopped (valve closed).")


# Example usage:
if __name__ == "__main__":
    # Replace with a valid HLS URL
    response_json = requests.get(
        "https://openapi.its.go.kr:9443/cctvInfo?apiKey=110ad7b8effb40388baaed01a4cd9dd1&type=ex&cctvType=1&minX=126.800000&maxX=127.890000&minY=34.90000&maxY=35.100000&getType=json").json()
    response_data = response_json.get("response").get('data')
    print(response_data)
    uri_ex = response_data[0].get("cctvurl")
    recorder = HLSRecorder(uri_ex)
    try:
        recorder.start_pipeline()
    except RuntimeError as e:
        print(f"Pipeline error: {e}")
        exit(1)

    # Run main loop to handle the pipeline events
    loop = GObject.MainLoop()
    # You could integrate external triggers here, e.g., timers or user input to start/stop recording:
    # For demonstration, let's start recording after 5 seconds and stop after 15 seconds.
    def on_start_recording():
        recorder.start_recording()
        return False  # one-shot timer
    def on_stop_recording():
        recorder.stop_recording()
        # Optionally, exit after stopping recording
        # loop.quit()
        return False
    GObject.timeout_add_seconds(2, on_start_recording)
    GObject.timeout_add_seconds(5, on_stop_recording)
    GObject.timeout_add_seconds(10, on_start_recording)
    GObject.timeout_add_seconds(13, on_stop_recording)

    try:
        loop.run()
    except KeyboardInterrupt:
        print("Interrupted by user, stopping...")
        recorder.stop_pipeline()
