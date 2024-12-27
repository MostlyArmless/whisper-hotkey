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
        self.proc = None
        self.sock = None
        
        Keybinder.init()
        Keybinder.bind("<Ctrl><Alt>R", self.toggle_recording)
        print("Hotkey bound: Ctrl+Alt+R")
        
        self.window.connect("delete-event", self.cleanup_and_quit)
        self.window.show_all()

    def draw(self, widget, context):
        context.set_source_rgba(0, 0, 0, 0.8)
        context.set_operator(1)
        context.paint()
        return False

    def type_text(self, text):
        # Use xdotool to type text and immediately sync
        try:
            subprocess.run([
                'xdotool', 'type', '--delay', '1', 
                '--clearmodifiers', text
            ], check=True)
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error typing text: {e}")
            return False

    def process_received_text(self, text):
        # Filter timestamps and clean up text
        parts = text.split('  ')
        if len(parts) > 1:
            clean_text = '  '.join(parts[1:]).strip()
            if clean_text:
                GLib.idle_add(self.type_text, clean_text + " ")

    def receive_transcription(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect(('192.168.0.197', 43007))
            self.sock.settimeout(0.5)  # shorter timeout for more responsive stopping

            buffer = ""
            while self.recording:
                try:
                    data = self.sock.recv(1024)
                    if not data:
                        break
                        
                    buffer += data.decode()
                    lines = buffer.split('\n')
                    
                    # Process all complete lines
                    for line in lines[:-1]:
                        if line.strip():
                            self.process_received_text(line)
                    
                    # Keep the incomplete last line
                    buffer = lines[-1]
                    
                except socket.timeout:
                    continue
                except Exception as e:
                    print(f"Error receiving data: {e}")
                    break
                    
            # Process any remaining data
            if buffer.strip():
                self.process_received_text(buffer)
                
        except Exception as e:
            print(f"Connection error: {e}")
            GLib.idle_add(self.label.set_text, "🚫 Connection Error")
        finally:
            self.cleanup_connection()

    def cleanup_connection(self):
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except:
                pass
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        
        if self.proc:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except:
                pass
            self.proc = None

    def cleanup_and_quit(self, *args):
        self.recording = False
        self.cleanup_connection()
        Gtk.main_quit()
        return False

    def toggle_recording(self, key=None):
        if not self.recording:
            # Start new recording
            self.recording = True
            self.label.set_text("🎤 Recording... (Esc/Ctrl+Alt+R to stop)")
            
            cmd = "arecord -f S16_LE -c1 -r 16000 -t raw -D default | nc 192.168.0.197 43007"
            try:
                self.proc = subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid)
            except Exception as e:
                print(f"Error starting recording: {e}")
                self.recording = False
                self.label.set_text("🚫 Recording Error")
                return
            
            self.receive_thread = threading.Thread(target=self.receive_transcription)
            self.receive_thread.daemon = True
            self.receive_thread.start()
        else:
            # Stop recording
            self.recording = False
            self.cleanup_connection()
            self.label.set_text("🎙️ Ready (Ctrl+Alt+R)")
            # Small delay to ensure the socket is properly closed
            time.sleep(0.1)

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