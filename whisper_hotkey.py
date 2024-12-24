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
        # Create a minimal window that will show recording status
        self.window = Gtk.Window(title="Recording")
        self.window.set_keep_above(True)
        self.window.set_decorated(False)
        self.window.set_default_size(100, 30)
        
        # Add a label
        self.label = Gtk.Label(label="🎤 Recording...")
        self.window.add(self.label)
        
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
        
        # Handle window close
        self.window.connect("delete-event", Gtk.main_quit)
        
        # Set up clipboard
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)

    def draw(self, widget, context):
        # Make window background semi-transparent
        context.set_source_rgba(0, 0, 0, 0.8)
        context.set_operator(1)
        context.paint()
        return False

    def insert_text(self, text):
        # Simulate typing the text
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
        finally:
            sock.close()

    def toggle_recording(self, key):
        if not self.recording:
            # Start recording
            self.recording = True
            self.window.show_all()
            
            # Start arecord and netcat
            cmd = "arecord -f S16_LE -c1 -r 16000 -t raw -D default | nc 192.168.0.197 43007"
            self.proc = subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid)
            
            # Start receiving transcriptions
            self.receive_thread = threading.Thread(target=self.receive_transcription)
            self.receive_thread.daemon = True
            self.receive_thread.start()
        else:
            # Stop recording
            self.recording = False
            if self.proc:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                self.proc = None
            self.window.hide()

    def run(self):
        # Add keyboard shortcut to stop recording
        self.window.connect('key-press-event', self.on_key_press)
        Gtk.main()

    def on_key_press(self, widget, event):
        # Handle Escape key
        if event.keyval == Gdk.KEY_Escape and self.recording:
            self.toggle_recording(None)
        return True

def main():
    app = WhisperHotkeyApp()
    app.run()

if __name__ == "__main__":
    main()