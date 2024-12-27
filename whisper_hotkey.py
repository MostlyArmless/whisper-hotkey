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

class WhisperHotkeyApp:
    def __init__(self):
        self.window = Gtk.Window(title="Whisper Hotkey")
        self.window.set_keep_above(True)
        self.window.set_decorated(False)
        self.window.set_default_size(150, 40)
        
        # Use a box for layout
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.window.add(self.box)
        
        # Status label
        self.label = Gtk.Label(label="🎙️ Ready (Ctrl+Alt+R)")
        self.box.pack_start(self.label, True, True, 0)
        
        # Make window semi-transparent
        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.window.set_visual(visual)
        self.window.set_app_paintable(True)
        self.window.connect("draw", self.draw)
        
        # Initialize state
        self.recording = False
        self.proc = None
        
        # Bind hotkeys
        Keybinder.init()
        Keybinder.bind("<Ctrl><Alt>R", self.toggle_recording)
        print("Hotkey bound: Ctrl+Alt+R")
        
        # Handle window close
        self.window.connect("delete-event", Gtk.main_quit)
        
        # Show window initially
        self.window.show_all()
        print("Window should be visible now")

    def draw(self, widget, context):
        context.set_source_rgba(0, 0, 0, 0.8)
        context.set_operator(1)
        context.paint()
        return False

    def insert_text(self, text):
        subprocess.run(['xdotool', 'type', text])

    def receive_transcription(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect(('192.168.0.197', 43007))
            while self.recording:
                data = sock.recv(1024)
                if not data:
                    break
                text = data.decode().strip()
                if text:
                    GLib.idle_add(self.insert_text, text + " ")
        except Exception as e:
            print(f"Error receiving transcription: {e}")
            GLib.idle_add(self.label.set_text, "🚫 Connection Error")
        finally:
            sock.close()

    def toggle_recording(self, key=None):
        if not self.recording:
            self.recording = True
            self.label.set_text("🎤 Recording... (Esc/Ctrl+Alt+R to stop)")
            
            cmd = "arecord -f S16_LE -c1 -r 16000 -t raw -D default | nc 192.168.0.197 43007"
            self.proc = subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid)
            
            self.receive_thread = threading.Thread(target=self.receive_transcription)
            self.receive_thread.daemon = True
            self.receive_thread.start()
        else:
            self.recording = False
            if self.proc:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                self.proc = None
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