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
        self.hotkey = "<Ctrl><Alt>R"
        self.labels = {
            'recording_error': "🚫 Recording Error",
            'recording': f"🔴 Recording (Press {self.hotkey} to stop)",
            'ready': f"🎙️ Ready (Press {self.hotkey} to start)"
        }
        self.window = Gtk.Window(title="Whisper Hotkey")
        self.window.set_keep_above(True)
        self.window.set_decorated(True)
        self.window.set_default_size(150, 40)
        
        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window.add(outer_box)
        
        header = Gtk.HeaderBar()
        header.set_decoration_layout("close:")
        header.set_show_close_button(True)
        self.window.set_titlebar(header)
        
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer_box.pack_start(self.box, True, True, 0)
        
        self.label = Gtk.Label(label=self.labels['ready'])
        self.box.pack_start(self.label, True, True, 0)
        
        self.button = Gtk.Button(label="Toggle Recording")
        self.button.connect("clicked", self.toggle_recording)
        self.box.pack_start(self.button, True, True, 0)
        
        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.window.set_visual(visual)
        self.window.set_app_paintable(True)
        self.window.connect("draw", self.draw)
        
        self.is_recording = False
        self.audio_proc = None
        self.nc_proc = None
        self.text_queue = queue.Queue()
        self.seen_segments = set()
        self.recording_start_time = None
        self.transcript_path = Path.home() / "whisper-transcript.txt"
        
        Keybinder.init()
        Keybinder.bind(self.hotkey, self.toggle_recording)
        
        self.window.connect("delete-event", self.cleanup_and_quit)
        self.window.show_all()
        GLib.timeout_add(100, self.process_text_queue)

    def draw(self, widget, context):
        context.set_source_rgba(0, 0, 0, 0.8)
        context.set_operator(1)
        context.paint()
        return False

    def append_to_transcript(self, text):
        try:
            timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            with open(self.transcript_path, 'a', encoding='utf-8') as f:
                f.write(f"{timestamp} - {text}\n")
        except Exception as e:
            print(f"Error writing to transcript: {e}")

    def type_text(self, text):
        try:
            subprocess.run([
                'xdotool', 'type', '--clearmodifiers', '--delay', '1', text
            ], check=True)
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
                self.type_text(text + " ")
                self.text_queue.task_done()
        except queue.Empty:
            pass
        return self.is_recording

    def read_output(self):
        while self.is_recording and self.nc_proc:
            try:
                line = self.nc_proc.stdout.readline().decode().strip()
                if line:
                    parts = line.split('  ', 1)
                    if len(parts) == 2:
                        timestamp, text = parts
                        start_ms, end_ms = map(int, timestamp.split())
                        chunk_duration = (end_ms - start_ms) / 1000
                        chunk_start_time = start_ms / 1000
                        
                        if timestamp not in self.seen_segments:
                            self.seen_segments.add(timestamp)
                            received_time = time.time() - self.recording_start_time
                            self.text_queue.put((text, received_time, chunk_duration, chunk_start_time))
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
            except Exception as e:
                print(f'ERROR while trying to kill audio_proc {self.audio_proc.pid}: {e}')
                pass
            self.audio_proc = None
            
        if self.nc_proc:
            try:
                os.killpg(os.getpgid(self.nc_proc.pid), signal.SIGTERM)
            except Exception as e:
                print(f'ERROR while trying to kill nc_proc {self.nc_proc.pid}: {e}')
                pass
            self.nc_proc = None

    def cleanup_and_quit(self, *args):
        self.is_recording = False
        self.cleanup_recording()
        Gtk.main_quit()
        return False

    def toggle_recording(self, key=None):
        if not self.is_recording:
            # Start recording
            self.is_recording = True
            self.seen_segments.clear()
            if self.start_recording():
                self.label.set_text(self.labels['recording'])
                GLib.timeout_add(100, self.process_text_queue)
            else:
                self.is_recording = False
                self.label.set_text(self.labels['recording_error'])
        else:
            self.is_recording = False
            self.cleanup_recording()
            self.label.set_text(self.labels['ready'])

    def run(self):
        Gtk.main()

if __name__ == "__main__":
    app = WhisperHotkeyApp()
    app.run()