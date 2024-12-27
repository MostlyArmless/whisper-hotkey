#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Keybinder', '3.0')
from gi.repository import Gtk, GLib, Keybinder
import subprocess
import threading
import signal
import os
import time
import queue
from pathlib import Path

class WhisperHotkeyApp:
    def __init__(self):
        self.window = Gtk.Window(title="Whisper Hotkey")
        self.window.set_keep_above(True)
        self.window.set_decorated(True)  # Enable window decorations for close button
        self.window.set_default_size(150, 40)
        
        # Create outer box for window decorations
        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window.add(outer_box)
        
        # Create header bar with close button
        header = Gtk.HeaderBar()
        header.set_decoration_layout("close:")
        header.set_show_close_button(True)
        self.window.set_titlebar(header)
        
        # Main content box
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer_box.pack_start(self.box, True, True, 0)
        
        self.label = Gtk.Label(label="🎙️ Ready (Favorites key)")
        self.box.pack_start(self.label, True, True, 0)
        
        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.window.set_visual(visual)
        self.window.set_app_paintable(True)
        self.window.connect("draw", self.draw)
        
        self.recording = False
        self.audio_proc = None
        self.nc_proc = None
        self.text_queue = queue.Queue()
        self.seen_segments = set()
        self.recording_start_time = None  # Track when recording starts
        
        # Create transcript file path
        self.transcript_path = Path.home() / "whisper-transcript.txt"
        
        Keybinder.init()
        Keybinder.bind("XF86Favorites", self.toggle_recording)
        print("Hotkey bound: Favorites key")
        
        self.window.connect("delete-event", self.cleanup_and_quit)
        self.window.show_all()

        GLib.timeout_add(100, self.process_text_queue)

    def draw(self, widget, context):
        context.set_source_rgba(0, 0, 0, 0.8)
        context.set_operator(1)
        context.paint()
        return False

    def append_to_transcript(self, text):
        """Append text to transcript file with timestamp"""
        try:
            timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            with open(self.transcript_path, 'a', encoding='utf-8') as f:
                f.write(f"{timestamp} - {text}\n")
        except Exception as e:
            print(f"Error writing to transcript: {e}")

    def type_text(self, text):
        print(f"Typing text: {text}")
        try:
            subprocess.run([
                'xdotool', 'type', '--clearmodifiers', '--delay', '1', text
            ], check=True)
            # Also append to transcript file
            self.append_to_transcript(text.strip())
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error typing text: {e}")
            return False

    def process_text_queue(self):
        try:
            while True:
                text, received_time, chunk_duration, chunk_start_time = self.text_queue.get_nowait()
                typed_time = time.time() - self.recording_start_time
                
                # Calculate latencies
                processing_latency = received_time - chunk_start_time  # Time from audio capture to server response
                total_latency = typed_time - chunk_start_time  # Total time from audio to typed output
                
                self.type_text(text + " ")
                
                print(f"\nLatency Analysis:")
                print(f"Chunk duration: {chunk_duration:.2f}s")
                print(f"Processing latency: {processing_latency:.2f}s")
                print(f"Total latency: {total_latency:.2f}s")
                print(f"Realtime factor: {chunk_duration/processing_latency:.2f}x")
                
                self.text_queue.task_done()
        except queue.Empty:
            pass
        return self.recording

    def read_output(self):
        buffer = ""
        while self.recording and self.nc_proc:
            try:
                line = self.nc_proc.stdout.readline().decode().strip()
                if line:
                    print(f"\nRaw received line: {line}")  # Debug raw input
                    parts = line.split('  ', 1)
                    if len(parts) == 2:
                        timestamp, text = parts
                        print(f"Parsed timestamp: {timestamp}, text: {text}")  # Debug parsing
                        # Parse the whisper timestamps (they're in milliseconds)
                        try:
                            start_ms, end_ms = map(int, timestamp.split())
                            chunk_duration = (end_ms - start_ms) / 1000  # Convert to seconds
                            chunk_start_time = start_ms / 1000  # When in the audio this chunk starts
                            
                            if timestamp not in self.seen_segments:
                                self.seen_segments.add(timestamp)
                                received_time = time.time() - self.recording_start_time
                                print(f"Queueing new segment: {text}")  # Debug queueing
                                self.text_queue.put((text, received_time, chunk_duration, chunk_start_time))
                            else:
                                print(f"Skipping already seen segment: {timestamp}")  # Debug duplicates
                        except Exception as e:
                            print(f"Error parsing timestamp {timestamp}: {e}")  # Debug parsing errors
            except Exception as e:
                print(f"Error reading output: {e}")
                break

    def start_recording(self):
        try:
            self.recording_start_time = time.time()
            self.audio_proc = subprocess.Popen(
                ['arecord', '-f', 'S16_LE', '-c1', '-r', '16000', '-t', 'raw', '-D', 'default'],
                stdout=subprocess.PIPE,
                preexec_fn=os.setsid
            )
            
            self.nc_proc = subprocess.Popen(
                ['nc', '192.168.0.197', '43007'],
                stdin=self.audio_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid
            )
            
            self.audio_proc.stdout.close()
            
            self.read_thread = threading.Thread(target=self.read_output)
            self.read_thread.daemon = True
            self.read_thread.start()
            
            return True
            
        except Exception as e:
            print(f"Error starting recording: {e}")
            self.cleanup_recording()
            return False

    def cleanup_recording(self):
        if self.audio_proc:
            try:
                os.killpg(os.getpgid(self.audio_proc.pid), signal.SIGTERM)
            except:
                pass
            self.audio_proc = None
            
        if self.nc_proc:
            try:
                os.killpg(os.getpgid(self.nc_proc.pid), signal.SIGTERM)
            except:
                pass
            self.nc_proc = None

    def cleanup_and_quit(self, *args):
        self.recording = False
        self.cleanup_recording()
        Gtk.main_quit()
        return False

    def toggle_recording(self, key=None):
        if not self.recording:
            self.recording = True
            self.seen_segments.clear()
            if self.start_recording():
                self.label.set_text("🎤 Recording... (Favorites key to stop)")
                GLib.timeout_add(100, self.process_text_queue)
            else:
                self.recording = False
                self.label.set_text("🚫 Recording Error")
        else:
            self.recording = False
            self.cleanup_recording()
            self.label.set_text("🎙️ Ready (Favorites key)")

    def run(self):
        Gtk.main()

def main():
    app = WhisperHotkeyApp()
    app.run()

if __name__ == "__main__":
    main()