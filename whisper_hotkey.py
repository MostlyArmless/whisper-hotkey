#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Keybinder', '3.0')
from gi.repository import Gtk, Gdk, GLib, Keybinder
import subprocess
import threading
import socket
import signal
import os
import time
import queue

class WhisperHotkeyApp:
    def __init__(self):
        self.window = Gtk.Window(title="Whisper Hotkey")
        self.window.set_keep_above(True)
        self.window.set_decorated(False)
        self.window.set_default_size(150, 40)
        
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.window.add(self.box)
        
        self.label = Gtk.Label(label="🎙️ Ready (Ctrl+Alt+R)")
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
        
        Keybinder.init()
        Keybinder.bind("<Ctrl><Alt>R", self.toggle_recording)
        print("Hotkey bound: Ctrl+Alt+R")
        
        self.window.connect("delete-event", self.cleanup_and_quit)
        self.window.show_all()

        # Start the text processing timer
        GLib.timeout_add(100, self.process_text_queue)

    def draw(self, widget, context):
        context.set_source_rgba(0, 0, 0, 0.8)
        context.set_operator(1)
        context.paint()
        return False

    def type_text(self, text):
        print(f"Typing text: {text}")
        try:
            subprocess.run([
                'xdotool', 'type', '--clearmodifiers', '--delay', '1', text
            ], check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error typing text: {e}")
            return False

    def process_text_queue(self):
        """Process any pending text in the queue"""
        try:
            while True:  # Process all available items
                text = self.text_queue.get_nowait()
                self.type_text(text)
                self.text_queue.task_done()
        except queue.Empty:
            pass
        
        # Keep the timer running if we're recording
        return self.recording

    def read_output(self):
        while self.recording and self.nc_proc:
            try:
                line = self.nc_proc.stdout.readline().decode().strip()
                if line:
                    print(f"Received line: {line}")
                    parts = line.split('  ', 1)  # Split only on first occurrence
                    if len(parts) == 2:
                        timestamp, text = parts
                        if timestamp not in self.seen_segments:
                            self.seen_segments.add(timestamp)
                            # Add to queue instead of direct typing
                            self.text_queue.put(text + " ")
            except Exception as e:
                print(f"Error reading output: {e}")
                break

    def start_recording(self):
        try:
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
            self.seen_segments.clear()  # Clear segments for new recording
            if self.start_recording():
                self.label.set_text("🎤 Recording... (Esc/Ctrl+Alt+R to stop)")
                # Start the text processing timer
                GLib.timeout_add(100, self.process_text_queue)
            else:
                self.recording = False
                self.label.set_text("🚫 Recording Error")
        else:
            self.recording = False
            self.cleanup_recording()
            self.label.set_text("🎙️ Ready (Ctrl+Alt+R)")

    def run(self):
        self.window.connect('key-press-event', self.on_key_press)
        Gtk.main()

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape and self.recording:
            self.toggle_recording()
        return True

def main():
    app = WhisperHotkeyApp()
    app.run()

if __name__ == "__main__":
    main()