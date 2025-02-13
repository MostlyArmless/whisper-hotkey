import os
import queue
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Set

import configparser
import gi

# These version requirements must be set before importing the gi modules
# They ensure we're using compatible versions of GTK and related libraries
# for creating the GUI, handling global hotkeys, and system tray functionality
gi.require_version("Gtk", "3.0")
gi.require_version("Keybinder", "3.0")
gi.require_version("AppIndicator3", "0.1")
from gi.repository import Gtk, GLib, Keybinder, AppIndicator3, Gdk  # noqa: E402 # type: ignore[import]


class Config:
    """Handles configuration loading and management."""

    @staticmethod
    def load() -> configparser.ConfigParser:
        config = configparser.ConfigParser()

        # These default values will be used if no config file exists
        config["server"] = {"host": "localhost", "port": "43007"}
        config["hotkey"] = {"combination": "<Ctrl><Alt>R"}
        config["recording"] = {"max_duration": "60"}

        # Store config in standard ~/.config directory
        config_path = Path.home() / ".config" / "whisper-client" / "config.ini"
        config_path.parent.mkdir(parents=True, exist_ok=True)

        if config_path.exists():
            config.read(config_path)
        else:
            # Create default config file if it doesn't exist
            with open(config_path, "w") as f:
                config.write(f)

        return config


def setup_display() -> None:
    """Set up the DISPLAY environment variable for X11 GUI operations.
    This is particularly important when running as a service."""
    try:
        # Try to get the current display from the 'w' command output
        display = subprocess.check_output(["w", "-hs"]).decode().split()[2]
        os.environ["DISPLAY"] = display
    except (subprocess.SubprocessError, IndexError):
        # Fall back to :0 if we can't determine the display
        os.environ["DISPLAY"] = ":0"


class SettingsDialog(Gtk.Dialog):
    """Dialog for editing application settings."""

    def __init__(self, parent, config):
        super().__init__(
            title="Whisper Settings", parent=parent, flags=Gtk.DialogFlags.MODAL
        )

        # Force dialog to stay on top
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_keep_above(True)

        self.config = config
        self.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE,
            Gtk.ResponseType.OK,
        )

        # Create the form layout
        box = self.get_content_area()
        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        box.add(grid)

        # Server settings
        row = 0
        grid.attach(Gtk.Label(label="Whisper server IP address:"), 0, row, 1, 1)
        self.host_entry = Gtk.Entry()
        self.host_entry.set_text(config["server"]["host"])
        grid.attach(self.host_entry, 1, row, 1, 1)

        row += 1
        grid.attach(Gtk.Label(label="Whisper Server Port Number:"), 0, row, 1, 1)
        self.port_entry = Gtk.Entry()
        self.port_entry.set_text(config["server"]["port"])
        grid.attach(self.port_entry, 1, row, 1, 1)

        row += 1
        grid.attach(Gtk.Label(label="Hotkey:"), 0, row, 1, 1)
        self.hotkey_entry = Gtk.Entry()
        self.hotkey_entry.set_text(config["hotkey"]["combination"])
        grid.attach(self.hotkey_entry, 1, row, 1, 1)

        row += 1
        grid.attach(Gtk.Label(label="Max Recording Duration (seconds):"), 0, row, 1, 1)
        self.duration_entry = Gtk.Entry()
        self.duration_entry.set_text(config["recording"]["max_duration"])
        grid.attach(self.duration_entry, 1, row, 1, 1)

        # Add Restore Defaults button
        row += 1
        restore_defaults_button = Gtk.Button(label="Restore Defaults")
        restore_defaults_button.connect("clicked", self.restore_defaults)
        restore_defaults_button.set_margin_top(10)
        grid.attach(restore_defaults_button, 0, row, 2, 1)

        self.show_all()

    def validate(self):
        """Validate the input values."""
        try:
            # Validate port
            port = int(self.port_entry.get_text())
            if not (1 <= port <= 65535):
                raise ValueError("Port must be between 1 and 65535")

            # Validate max duration
            duration = int(self.duration_entry.get_text())
            if duration <= 0:
                raise ValueError("Max duration must be positive")

            # Validate host (basic check)
            host = self.host_entry.get_text().strip()
            if not host:
                raise ValueError("Host cannot be empty")

            # Validate hotkey (basic check)
            hotkey = self.hotkey_entry.get_text().strip()
            if not hotkey:
                raise ValueError("Hotkey cannot be empty")

            return True

        except ValueError as e:
            dialog = Gtk.MessageDialog(
                parent=self,
                flags=Gtk.DialogFlags.MODAL,
                type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                message_format=str(e),
            )
            dialog.run()
            dialog.destroy()
            return False

    def save_settings(self):
        """Save the settings to the config.ini file."""
        self.config["server"]["host"] = self.host_entry.get_text()
        self.config["server"]["port"] = self.port_entry.get_text()
        self.config["hotkey"]["combination"] = self.hotkey_entry.get_text()
        self.config["recording"]["max_duration"] = self.duration_entry.get_text()

        config_path = Path.home() / ".config" / "whisper-client" / "config.ini"
        with open(config_path, "w") as f:
            self.config.write(f)

    def restore_defaults(self, button):
        """Restore default settings values for port, hotkey and duration."""
        self.port_entry.set_text("43007")
        self.hotkey_entry.set_text("<Ctrl><Alt>R")
        self.duration_entry.set_text("60")


class WhisperIndicatorApp:
    """Main application class for the Whisper indicator.

    This class handles:
    - System tray icon and menu
    - Recording state management
    - Communication with whisper server
    - Text output and transcript management
    """

    def __init__(self):
        Gtk.init(None)
        self.config = Config.load()
        self.hotkey = self.config["hotkey"]["combination"]
        self.settings_dialog = None  # Add this line to track the dialog instance

        self.init_state()
        self.init_ui()
        self.init_keybinding()
        self.setup_timers()

    def init_state(self) -> None:
        """Initialize application state variables.

        These variables track:
        - Recording state and processes
        - Text queue for processed speech
        - Timers and durations
        - File paths and settings
        """
        self.is_recording = False
        self.audio_proc: Optional[subprocess.Popen] = None
        self.nc_proc: Optional[subprocess.Popen] = None
        self.text_queue: queue.Queue = queue.Queue()
        self.seen_segments: Set[str] = set()
        self.recording_start_time: Optional[float] = None
        self.recording_duration = 0
        self.last_successful_connection = time.time()
        self.timer_id: Optional[int] = None
        self.transcript_path = Path.home() / "whisper-transcript.txt"
        self.max_recording_duration = int(self.config["recording"]["max_duration"])

    def init_ui(self) -> None:
        """Initialize UI components."""
        self.setup_status_labels()
        self.setup_indicator()
        self.setup_menu()

    def setup_status_labels(self) -> None:
        """Set up status message templates."""
        self.labels = {
            "recording_error": "🚫 Recording Error",
            "recording": f"🔴 Recording (Press {self.hotkey} to stop)",
            "ready": f"🎙️ Ready (Press {self.hotkey} to start)",
            "server_error": "❌ Server Unavailable",
        }

    def setup_indicator(self) -> None:
        """Set up the system tray indicator."""
        self.indicator = AppIndicator3.Indicator.new(
            "whisper-indicator",
            "audio-input-microphone-symbolic",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.indicator.set_label("", "")

    def setup_menu(self) -> None:
        """Set up the indicator menu."""
        self.menu = Gtk.Menu()

        # Status item
        self.status_item = Gtk.MenuItem(label=self.labels["ready"])
        self.status_item.set_sensitive(False)
        self.menu.append(self.status_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        # Toggle recording item
        toggle_item = Gtk.MenuItem(label="Toggle Recording")
        toggle_item.connect("activate", self.toggle_recording)
        self.menu.append(toggle_item)

        # Add Settings item
        settings_item = Gtk.MenuItem(label="Settings")
        settings_item.connect("activate", self.show_settings)
        self.menu.append(settings_item)

        self.menu.append(Gtk.SeparatorMenuItem())

        # Service control items
        restart_item = Gtk.MenuItem(label="Restart Service")
        restart_item.connect("activate", self.restart_service)
        self.menu.append(restart_item)

        quit_item = Gtk.MenuItem(label="Quit Service")
        quit_item.connect("activate", self.quit_service)
        self.menu.append(quit_item)

        self.menu.show_all()
        self.indicator.set_menu(self.menu)

    def init_keybinding(self) -> None:
        """Initialize global hotkey binding."""
        Keybinder.init()
        Keybinder.bind(self.hotkey, self.toggle_recording)

    def setup_timers(self) -> None:
        """Set up periodic tasks."""
        GLib.timeout_add(100, self.process_text_queue)
        self.server_check_timer = GLib.timeout_add(5000, self.check_server_status)

    def check_server_status(self) -> bool:
        """Check if the whisper server is available.

        This runs periodically to:
        1. Test connection to server
        2. Update status display
        3. Track last successful connection time
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(
                (self.config["server"]["host"], int(self.config["server"]["port"]))
            )
            sock.close()

            if result == 0:
                self.last_successful_connection = time.time()
                if not self.is_recording:
                    self.update_status(self.labels["ready"])
            elif not self.is_recording:
                self.update_status(self.labels["server_error"])

        except Exception as e:
            print(f"Server check error: {e}")
            if not self.is_recording:
                self.update_status(self.labels["server_error"])

        self.update_connection_time()
        return True

    def update_status(self, text: str) -> None:
        """Update the status display."""
        self.status_item.set_label(text)

        if "Recording" in text:
            self.set_recording_icon()
        elif "Error" in text or "Unavailable" in text:
            self.indicator.set_icon("network-error-symbolic")
        else:
            self.indicator.set_icon("audio-input-microphone-symbolic")

    def set_recording_icon(self) -> None:
        """Set up the recording indicator icon."""
        self.indicator.set_icon("media-record")
        self.indicator.set_icon_full("media-record", "Recording")
        css = b".app-indicator-icon { color: #ff0000; }"
        style_provider = Gtk.CssProvider()
        style_provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            style_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def update_connection_time(self) -> None:
        """Update the status text with time since last connection."""
        elapsed = time.time() - self.last_successful_connection
        if elapsed < 60:
            time_text = f"{int(elapsed)}s ago"
        elif elapsed < 3600:
            time_text = f"{int(elapsed / 60)}m ago"
        else:
            time_text = f"{int(elapsed / 3600)}h ago"

        current_text = self.status_item.get_label()
        base_text = current_text.split(" (Last seen:")[0]
        self.status_item.set_label(f"{base_text} (Last seen: {time_text})")

    def toggle_recording(self, *args) -> None:
        """Toggle recording state."""
        if not self.is_recording:
            self.start_recording_session()
        else:
            self.stop_recording_session()

    def start_recording_session(self) -> None:
        """Start a new recording session."""
        self.is_recording = True
        self.seen_segments.clear()

        if self.start_recording_processes():
            self.recording_duration = 0
            self.recording_start_time = time.time()
            self.indicator.set_label("0s", "")
            self.timer_id = GLib.timeout_add(1000, self.update_timer)
            self.update_status(self.labels["recording"])
            GLib.timeout_add(100, self.process_text_queue)
        else:
            self.is_recording = False
            self.indicator.set_label("", "")
            self.update_status(self.labels["recording_error"])

    def stop_recording_session(self) -> None:
        """Stop the current recording session."""
        self.is_recording = False
        self.cleanup_recording()
        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = None
        self.indicator.set_label("", "")
        self.update_status(self.labels["ready"])

    def start_recording_processes(self) -> bool:
        """Start the recording and network processes.

        This method:
        1. Starts arecord to capture audio
        2. Pipes audio to netcat (nc) which sends it to the whisper server
        3. Creates a thread to read the server's responses
        """
        try:
            self.audio_proc = subprocess.Popen(
                [
                    "arecord",
                    "-f",  # Format:
                    "S16_LE",  # 16-bit signed integers, little-endian
                    "-c1",  # Single channel (mono) recording
                    "-r",  # Sample rate:
                    "16000",  # 16kHz
                    "-t",  # Audio type:
                    "raw",  # Raw audio format (no header) for direct streaming
                    "-D",  # Device:
                    "default",  # Use system default ALSA audio input device
                ],
                stdout=subprocess.PIPE,
                preexec_fn=os.setsid,
            )

            self.nc_proc = subprocess.Popen(
                ["nc", self.config["server"]["host"], self.config["server"]["port"]],
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

    def read_output(self) -> None:
        """Read and process output from the whisper server.

        The server sends lines in format:
        "start_ms end_ms  transcribed_text"

        This method parses these lines and queues the text for typing.
        """
        while self.is_recording and self.nc_proc and self.nc_proc.stdout:
            try:
                line = self.nc_proc.stdout.readline().decode().strip()
                if not line:
                    continue

                parts = line.split("  ", 1)
                if len(parts) != 2:
                    continue

                timestamp, text = parts
                start_ms, end_ms = map(int, timestamp.split())
                chunk_duration = (end_ms - start_ms) / 1000
                chunk_start_time = start_ms / 1000

                if timestamp not in self.seen_segments:
                    self.seen_segments.add(timestamp)
                    received_time = time.time() - (self.recording_start_time or 0)
                    self.text_queue.put(
                        (text, received_time, chunk_duration, chunk_start_time)
                    )

            except Exception as e:
                print(f"Error reading output: {e}")
                break

    def process_text_queue(self) -> bool:
        """Process queued text from the whisper server.

        This runs periodically to:
        1. Check for new transcribed text
        2. Type the text using xdotool
        3. Save to transcript file
        """
        try:
            while True:
                text, received_time, chunk_duration, chunk_start_time = (
                    self.text_queue.get_nowait()
                )
                self.type_text(text + " ")
                self.text_queue.task_done()
        except queue.Empty:
            pass
        return self.is_recording

    def type_text(self, text: str) -> bool:
        """Type the text and save to transcript."""
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

    def append_to_transcript(self, text: str) -> None:
        """Append text to the transcript file."""
        try:
            timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            with open(self.transcript_path, "a", encoding="utf-8") as f:
                f.write(f"{timestamp} - {text}\n")
        except Exception as e:
            print(f"Error writing to transcript: {e}")

    def update_timer(self) -> bool:
        """Update the recording timer display."""
        if not self.is_recording:
            return False

        if self.recording_start_time is not None:
            self.recording_duration = int(time.time() - self.recording_start_time)
        else:
            self.recording_duration = 0

        self.indicator.set_label(f"{self.recording_duration}s", "")

        if self.recording_duration >= self.max_recording_duration:
            # Stop the timer, toggle recording, and play a beep sound to indicate the end of the recording
            GLib.idle_add(self.toggle_recording)
            subprocess.run(
                ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"]
            )
            return False

        return True

    def cleanup_recording(self) -> None:
        """Clean up recording processes."""
        for proc_name, proc in [("audio", self.audio_proc), ("network", self.nc_proc)]:
            if proc:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except Exception as e:
                    print(f"Error killing {proc_name} process: {e}")

        self.audio_proc = None
        self.nc_proc = None

    def cleanup_and_quit(self, *args) -> bool:
        """Clean up and quit the application."""
        self.is_recording = False
        self.cleanup_recording()
        if hasattr(self, "server_check_timer"):
            GLib.source_remove(self.server_check_timer)
        Gtk.main_quit()
        return False

    def restart_service(self, *args) -> None:
        """Restart the whisper client service."""
        subprocess.run(["systemctl", "--user", "restart", "whisper-client"])

    def quit_service(self, *args) -> None:
        """Stop the whisper client service."""
        subprocess.run(["systemctl", "--user", "stop", "whisper-client"])
        self.cleanup_and_quit()

    def show_settings(self, widget) -> None:
        """Show the settings dialog."""
        # If dialog exists, just present it
        if self.settings_dialog is not None:
            self.settings_dialog.present()
            return

        # Create new dialog
        self.settings_dialog = SettingsDialog(None, self.config)
        response = self.settings_dialog.run()

        if response == Gtk.ResponseType.OK:
            if self.settings_dialog.validate():
                self.settings_dialog.save_settings()
                # Rebind hotkey with new combination
                Keybinder.unbind(self.hotkey)
                self.hotkey = self.config["hotkey"]["combination"]
                Keybinder.bind(self.hotkey, self.toggle_recording)
                # Update max recording duration
                self.max_recording_duration = int(
                    self.config["recording"]["max_duration"]
                )
                # Update status labels with new hotkey
                self.setup_status_labels()
                self.update_status(self.labels["ready"])

        self.settings_dialog.destroy()
        self.settings_dialog = None

    def run(self) -> None:
        """Start the application main loop."""
        Gtk.main()


if __name__ == "__main__":
    setup_display()
    app = WhisperIndicatorApp()
    app.run()
