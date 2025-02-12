import subprocess
import threading
import signal
import os
import time
import queue
from pathlib import Path
from subprocess import check_output
import configparser
import gi
import socket

gi.require_version("Gtk", "3.0")
gi.require_version("Keybinder", "3.0")
gi.require_version("AppIndicator3", "0.1")
from gi.repository import Gtk, GLib, Keybinder, AppIndicator3, Gdk  # type: ignore # noqa: E402


def load_config():
    config = configparser.ConfigParser()

    # Default values
    config["server"] = {"host": "localhost", "port": "43007"}
    config["hotkey"] = {"combination": "<Ctrl><Alt>R"}
    config["recording"] = {"max_duration": "60"}

    # Config file location
    config_dir = Path.home() / ".config" / "whisper-client"
    config_file = config_dir / "config.ini"

    # Create config directory if it doesn't exist
    config_dir.mkdir(parents=True, exist_ok=True)

    # Read existing config or create default
    if config_file.exists():
        config.read(config_file)
    else:
        with open(config_file, "w") as f:
            config.write(f)

    return config


# Load config at startup
config = load_config()


def get_display():
    try:
        display = check_output(["w", "-hs"]).decode().split()[2]
        os.environ["DISPLAY"] = display
    except:
        os.environ["DISPLAY"] = ":0"


get_display()


class WhisperIndicatorApp:
    def __init__(self):
        Gtk.init(None)
        self.hotkey = config["hotkey"]["combination"]
        self.last_successful_connection = time.time()  # Initialize with current time
        self.labels = {
            "recording_error": "🚫 Recording Error",
            "recording": f"🔴 Recording (Press {self.hotkey} to stop)",
            "ready": f"🎙️ Ready (Press {self.hotkey} to start)",
            "server_error": "❌ Server Unavailable",
        }

        # Initialize the indicator
        self.indicator = AppIndicator3.Indicator.new(
            "whisper-indicator",
            "audio-input-microphone-symbolic",  # Using system icon
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_label("", "")  # Initialize empty label

        # Create the menu
        self.menu = Gtk.Menu()

        # Status item (non-clickable)
        self.status_item = Gtk.MenuItem(label=self.labels["ready"])
        self.status_item.set_sensitive(False)
        self.menu.append(self.status_item)

        # Separator
        self.menu.append(Gtk.SeparatorMenuItem())

        # Toggle recording item
        self.toggle_item = Gtk.MenuItem(label="Toggle Recording")
        self.toggle_item.connect("activate", self.toggle_recording)
        self.menu.append(self.toggle_item)

        # Separator
        self.menu.append(Gtk.SeparatorMenuItem())

        # Restart Service item
        restart_item = Gtk.MenuItem(label="Restart Service")
        restart_item.connect("activate", self.restart_service)
        self.menu.append(restart_item)

        # Quit Service item (stops the systemd service)
        quit_service_item = Gtk.MenuItem(label="Quit Service")
        quit_service_item.connect("activate", self.quit_service)
        self.menu.append(quit_service_item)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

        self.is_recording = False
        self.audio_proc = None
        self.nc_proc = None
        self.text_queue = queue.Queue()
        self.seen_segments = set()
        self.recording_start_time = None
        self.recording_duration = 0
        self.MAX_RECORDING_DURATION = int(
            config["recording"]["max_duration"]
        )  # 60 seconds
        self.timer_id = None
        self.transcript_path = Path.home() / "whisper-transcript.txt"

        Keybinder.init()
        Keybinder.bind(self.hotkey, self.toggle_recording)

        GLib.timeout_add(100, self.process_text_queue)

        # Add server check timer
        server_hearbeat_period = 5000  # ms
        self.server_check_timer = GLib.timeout_add(
            server_hearbeat_period, self.check_server_status
        )

    def check_server_status(self):
        """Check if the server is available by attempting a quick connection."""
        try:
            # Attempt to connect with a short timeout
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)  # 1 second timeout
            result = sock.connect_ex(
                (config["server"]["host"], int(config["server"]["port"]))
            )
            sock.close()

            if result == 0:
                self.last_successful_connection = time.time()
                if not self.is_recording:
                    self.update_status(self.labels["ready"])
            else:
                if not self.is_recording:
                    self.update_status(self.labels["server_error"])
        except Exception as e:
            print(f"Server check error: {e}")
            if not self.is_recording:
                self.update_status(self.labels["server_error"])

        self.update_connection_time()
        return True  # Keep the timer running

    def update_connection_time(self):
        """Update the status text with time since last connection"""
        elapsed = time.time() - self.last_successful_connection
        if elapsed < 60:
            time_text = f"{int(elapsed)}s ago"
        elif elapsed < 3600:
            time_text = f"{int(elapsed / 60)}m ago"
        else:
            time_text = f"{int(elapsed / 3600)}h ago"

        current_text = self.status_item.get_label()
        base_text = current_text.split(" (Last seen:")[
            0
        ]  # Remove old timestamp if exists
        self.status_item.set_label(f"{base_text} (Last seen: {time_text})")

    def update_status(self, text):
        self.status_item.set_label(text)
        if "Recording" in text:
            self.indicator.set_icon("media-record")
            self.indicator.set_icon_full("media-record", "Recording")
            css = b"""
            .app-indicator-icon { color: #ff0000; }
            """
            style_provider = Gtk.CssProvider()
            style_provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                style_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        elif "Error" in text or "Unavailable" in text:
            self.indicator.set_icon("network-error-symbolic")
        else:
            self.indicator.set_icon("audio-input-microphone-symbolic")

    def append_to_transcript(self, text):
        try:
            timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            with open(self.transcript_path, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} - {text}\n")
        except Exception as e:
            print(f"Error writing to transcript: {e}")

    def type_text(self, text):
        try:
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--delay", "1", text],
                check=True,
            )
            self.append_to_transcript(text.strip())
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error typing text: {e}")
            return False

    def process_text_queue(self):
        try:
            while True:
                text, received_time, chunk_duration, chunk_start_time = (
                    self.text_queue.get_nowait()
                )
                if self.recording_start_time is not None:
                    typed_time = time.time() - self.recording_start_time
                else:
                    typed_time = 0
                self.type_text(text + " ")
                self.text_queue.task_done()
        except queue.Empty:
            pass
        return self.is_recording

    def read_output(self):
        while self.is_recording and self.nc_proc:
            try:
                if self.nc_proc and self.nc_proc.stdout:
                    line = self.nc_proc.stdout.readline().decode().strip()
                else:
                    break
                if line:
                    parts = line.split("  ", 1)
                    if len(parts) == 2:
                        timestamp, text = parts
                        start_ms, end_ms = map(int, timestamp.split())
                        chunk_duration = (end_ms - start_ms) / 1000
                        chunk_start_time = start_ms / 1000

                        if timestamp not in self.seen_segments:
                            self.seen_segments.add(timestamp)
                            received_time = time.time() - (
                                self.recording_start_time or 0
                            )
                            self.text_queue.put(
                                (text, received_time, chunk_duration, chunk_start_time)
                            )
            except Exception as e:
                print(f"Error reading output: {e}")
                break

    def start_recording(self):
        try:
            self.recording_start_time = time.time()
            self.audio_proc = subprocess.Popen(
                [
                    "arecord",
                    "-f",
                    "S16_LE",
                    "-c1",
                    "-r",
                    "16000",
                    "-t",
                    "raw",
                    "-D",
                    "default",
                ],
                stdout=subprocess.PIPE,
                preexec_fn=os.setsid,
            )

            self.nc_proc = subprocess.Popen(
                ["nc", config["server"]["host"], config["server"]["port"]],
                stdin=self.audio_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid,
            )

            if self.audio_proc.stdout:
                self.audio_proc.stdout.close()

            self.read_thread = threading.Thread(target=self.read_output)
            self.read_thread.daemon = True
            self.read_thread.start()

            self.last_successful_connection = time.time()
            self.update_connection_time()
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
                print(
                    f"ERROR while trying to kill audio_proc {self.audio_proc.pid}: {e}"
                )
            self.audio_proc = None

        if self.nc_proc:
            try:
                os.killpg(os.getpgid(self.nc_proc.pid), signal.SIGTERM)
            except Exception as e:
                print(f"ERROR while trying to kill nc_proc {self.nc_proc.pid}: {e}")
            self.nc_proc = None

    def cleanup_and_quit(self, *args):
        self.is_recording = False
        self.cleanup_recording()
        if hasattr(self, "server_check_timer"):
            GLib.source_remove(self.server_check_timer)
        Gtk.main_quit()
        return False

    def toggle_recording(self, *args):
        if not self.is_recording:
            # Start recording
            self.is_recording = True
            self.seen_segments.clear()
            if self.start_recording():
                self.recording_duration = 0
                self.recording_start_time = time.time()
                self.indicator.set_label("0s", "")  # Initialize timer display
                self.timer_id = GLib.timeout_add(1000, self.update_timer)
                self.update_status(self.labels["recording"])
                GLib.timeout_add(100, self.process_text_queue)
            else:
                self.is_recording = False
                self.indicator.set_label("", "")  # Clear timer
                self.update_status(self.labels["recording_error"])
        else:
            self.is_recording = False
            self.cleanup_recording()
            if self.timer_id:
                GLib.source_remove(self.timer_id)
                self.timer_id = None
            self.indicator.set_label("", "")  # Clear timer
            self.update_status(self.labels["ready"])

    def update_timer(self):
        if self.is_recording:
            if self.recording_start_time is not None:
                self.recording_duration = int(time.time() - self.recording_start_time)
            else:
                self.recording_duration = 0
            # Update the indicator label with just the duration
            self.indicator.set_label(f"{self.recording_duration}s", "")

            # Auto-stop after MAX_RECORDING_DURATION
            if self.recording_duration >= self.MAX_RECORDING_DURATION:
                GLib.idle_add(self.toggle_recording)
                return False
            return True
        return False

    def restart_service(self, *args):
        subprocess.run(["systemctl", "--user", "restart", "whisper-client"])

    def quit_service(self, *args):
        subprocess.run(["systemctl", "--user", "stop", "whisper-client"])
        self.cleanup_and_quit()

    def run(self):
        Gtk.main()


if __name__ == "__main__":
    app = WhisperIndicatorApp()
    app.run()
