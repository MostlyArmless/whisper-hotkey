import os
import queue
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Set
import re

import configparser
import gi
import json

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
        self.hotkey_entry.set_text(config["hotkey"]["mic_only"])
        grid.attach(self.hotkey_entry, 1, row, 1, 1)

        row += 1
        grid.attach(Gtk.Label(label="Mic and Output Hotkey:"), 0, row, 1, 1)
        self.mic_and_output_entry = Gtk.Entry()
        self.mic_and_output_entry.set_text(config["hotkey"]["mic_and_output"])
        grid.attach(self.mic_and_output_entry, 1, row, 1, 1)

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

            # Enhanced host validation
            host = self.host_entry.get_text().strip()
            if not host:
                raise ValueError("Host cannot be empty")

            # Check if it's an IP address
            try:
                # Try parsing as IPv4
                parts = host.split(".")
                if len(parts) == 4 and all(0 <= int(part) <= 255 for part in parts):
                    return True

                # Try parsing as IPv6
                socket.inet_pton(socket.AF_INET6, host)
                return True

            except (ValueError, socket.error):
                # Not an IP address, validate as domain name
                if not self.is_valid_domain(host):
                    raise ValueError(
                        "Invalid host format. Please enter a valid IP address or domain name"
                    )

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

    def is_valid_domain(self, domain):
        """Validate domain name format."""
        if len(domain) > 255:
            return False

        # Allow localhost
        if domain == "localhost":
            return True

        # Domain name validation pattern
        pattern = r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$"
        if re.match(pattern, domain):
            return True

        return False

    def save_settings(self):
        """Save the settings to the config.ini file."""
        self.config["server"]["host"] = self.host_entry.get_text()
        self.config["server"]["port"] = self.port_entry.get_text()
        self.config["hotkey"]["mic_only"] = self.hotkey_entry.get_text()
        self.config["hotkey"]["mic_and_output"] = self.mic_and_output_entry.get_text()
        self.config["recording"]["max_duration"] = self.duration_entry.get_text()

        config_path = Path.home() / ".config" / "whisper-client" / "config.ini"
        with open(config_path, "w") as f:
            self.config.write(f)

    def restore_defaults(self, button):
        """Restore default settings values for port, hotkey and duration."""
        self.port_entry.set_text("43007")
        self.hotkey_entry.set_text("<Ctrl><Alt>R")
        self.mic_and_output_entry.set_text("<Ctrl><Alt>E")
        self.duration_entry.set_text("60")


class TranscriptViewerDialog(Gtk.Dialog):
    """Dialog for viewing and copying transcripts."""

    def __init__(self, parent, transcript_path):
        super().__init__(
            title="Transcript History",
            parent=parent,
            flags=Gtk.DialogFlags.MODAL,
        )

        self.set_default_size(600, 400)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_keep_above(True)

        # Add close button
        self.add_button(Gtk.STOCK_CLOSE, Gtk.ResponseType.CLOSE)

        # Create scrolled window
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        box = self.get_content_area()
        box.pack_start(scrolled, True, True, 0)

        # Create list store and view
        self.store = Gtk.ListStore(str, str)  # timestamp, text
        self.view = Gtk.TreeView(model=self.store)

        # Add columns
        timestamp_renderer = Gtk.CellRendererText()
        timestamp_renderer.props.wrap_width = 150
        timestamp_col = Gtk.TreeViewColumn("Timestamp", timestamp_renderer, text=0)
        timestamp_col.set_resizable(True)
        timestamp_col.set_min_width(150)
        self.view.append_column(timestamp_col)

        text_renderer = Gtk.CellRendererText()
        text_renderer.props.wrap_width = 350
        text_renderer.props.wrap_mode = 2  # WRAP_WORD
        text_col = Gtk.TreeViewColumn("Transcript", text_renderer, text=1)
        text_col.set_resizable(True)
        text_col.set_min_width(350)
        self.view.append_column(text_col)

        # Replace the copy button column code with this button-styled version
        copy_renderer = Gtk.CellRendererPixbuf()
        copy_renderer.props.icon_name = "edit-copy-symbolic"
        copy_renderer.props.stock_size = Gtk.IconSize.BUTTON
        copy_renderer.props.xpad = 8
        copy_renderer.props.ypad = 6

        copy_col = Gtk.TreeViewColumn()
        copy_col.pack_start(copy_renderer, True)
        copy_col.set_fixed_width(36)
        copy_col.set_alignment(0.5)
        copy_col.set_title("")
        self.view.append_column(copy_col)

        # Update CSS styling to include button effects
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
            treeview {
                padding: 5px;
            }
            treeview:hover {
                background-color: alpha(@theme_selected_bg_color, 0.1);
            }
            .cell {
                padding: 4px;
            }
            .cell:hover {
                background-color: @theme_selected_bg_color;
                border-radius: 4px;
                box-shadow: inset 0 1px rgba(255, 255, 255, 0.1),
                           inset 0 -1px rgba(0, 0, 0, 0.1);
            }
            .copy-button {
                background-color: @theme_bg_color;
                border: 1px solid @borders;
                border-radius: 4px;
                padding: 4px;
                box-shadow: inset 0 1px rgba(255, 255, 255, 0.1),
                           inset 0 -1px rgba(0, 0, 0, 0.1);
            }
            .copy-button:hover {
                background-color: @theme_selected_bg_color;
            }
        """)

        # Apply the CSS styling
        style_context = self.view.get_style_context()
        style_context.add_provider(
            css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        style_context.add_class("copy-button")

        # Update the ListStore to not include the icon name since we set it in the renderer
        self.store = Gtk.ListStore(str, str)  # timestamp, text only
        self.view.set_model(self.store)

        scrolled.add(self.view)

        # Load transcripts
        try:
            if transcript_path.exists():
                with open(transcript_path, "r", encoding="utf-8") as f:
                    transcripts = json.load(f)
                    # Sort by timestamp in reverse order (newest first)
                    for timestamp in sorted(transcripts.keys(), reverse=True):
                        self.store.append([timestamp, transcripts[timestamp]])
        except Exception as e:
            print(f"Error loading transcripts: {e}")

        # Handle click events for copy button
        self.view.connect("button-press-event", self.on_button_press)

        self.show_all()

    def on_button_press(self, treeview, event):
        """Handle click events on the tree view."""
        if event.button != 1:  # Left click only
            return False

        path_info = treeview.get_path_at_pos(int(event.x), int(event.y))
        if not path_info:
            return False

        path, column, _, _ = path_info
        if (
            column == treeview.get_columns()[-1]
        ):  # Check if it's the last column (copy button)
            model = treeview.get_model()
            text = model[path][1]  # Get transcript text

            # Copy to clipboard
            clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
            clipboard.set_text(text, -1)

            # Show a more subtle feedback tooltip instead of a dialog
            tooltip = Gtk.Window(type=Gtk.WindowType.POPUP)
            tooltip.set_type_hint(Gdk.WindowTypeHint.TOOLTIP)
            tooltip.set_position(Gtk.WindowPosition.MOUSE)

            label = Gtk.Label(label="Copied to clipboard!")
            label.set_padding(10, 5)
            tooltip.add(label)
            tooltip.show_all()

            # Remove tooltip after 1 second
            GLib.timeout_add(1000, tooltip.destroy)
            return True

        return False


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
        self.mic_hotkey = self.config["hotkey"]["mic_only"]
        self.mic_and_output_hotkey = self.config["hotkey"]["mic_and_output"]
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
        self.is_recording_mic_for_transcription = False
        self.is_recording_mic_and_output = False
        self.audio_process_for_mic_transcription: Optional[subprocess.Popen] = None
        self.netcat_process: Optional[subprocess.Popen] = None
        self.text_queue: queue.Queue = queue.Queue()
        self.seen_segments: Set[str] = set()
        self.recording_start_time: Optional[float] = None
        self.recording_duration = 0
        self.last_successful_connection = time.time()
        self.timer_id: Optional[int] = None
        self.transcript_path = Path.home() / "whisper-transcript.json"
        self.max_recording_duration = int(self.config["recording"]["max_duration"])
        self.current_session_text = []
        self.session_start_time = None
        self.recording_path = Path.home() / "whisper-recordings"
        self.recording_path.mkdir(parents=True, exist_ok=True)
        self.audio_process_for_recording_mic_and_output: Optional[subprocess.Popen] = (
            None
        )

    def init_ui(self) -> None:
        """Initialize UI components."""
        self.setup_status_labels()
        self.setup_indicator()
        self.setup_menu()

    def setup_status_labels(self) -> None:
        """Set up status message templates."""
        self.labels = {
            "recording_error": "🚫 Recording Error",
            "recording_mic_only": f"🔴 Recording Mic Only (Press {self.mic_hotkey} to stop)",
            "recording_mic_and_output": f"🔴 Recording Mic and Output (Press {self.mic_and_output_hotkey} to stop)",
            "ready": "🎙️ Ready",
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
        toggle_item = Gtk.MenuItem(
            label=f"Toggle Mic Transcribe+Type ({self.mic_hotkey})"
        )
        toggle_item.connect("activate", self.toggle_mic_transcription)
        self.menu.append(toggle_item)

        toggle_item = Gtk.MenuItem(
            label=f"Toggle Mic and Output Recording ({self.mic_and_output_hotkey})"
        )
        toggle_item.connect("activate", self.toggle_recording_mic_and_output)
        self.menu.append(toggle_item)

        # Add Settings item
        settings_item = Gtk.MenuItem(label="Settings")
        settings_item.connect("activate", self.show_settings)
        self.menu.append(settings_item)

        # Add Transcript History item
        history_item = Gtk.MenuItem(label="Transcript History")
        history_item.connect("activate", self.show_transcript_history)
        self.menu.append(history_item)

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
        Keybinder.bind(self.mic_hotkey, self.toggle_mic_transcription)
        Keybinder.bind(self.mic_and_output_hotkey, self.toggle_recording_mic_and_output)

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
                if not self.is_recording_mic_for_transcription:
                    self.update_status(self.labels["ready"])
            elif not self.is_recording_mic_for_transcription:
                self.update_status(self.labels["server_error"])

        except Exception as e:
            print(f"Server check error: {e}")
            if not self.is_recording_mic_for_transcription:
                self.update_status(self.labels["server_error"])

        self.update_server_last_connection_time_label()
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

    def update_server_last_connection_time_label(self) -> None:
        """Update the status text with time since last connection."""
        elapsed = time.time() - self.last_successful_connection
        if elapsed < 60:
            time_text = f"{int(elapsed)}s ago"
        elif elapsed < 3600:
            time_text = f"{int(elapsed / 60)}m ago"
        else:
            time_text = f"{int(elapsed / 3600)}h ago"

        current_text = self.status_item.get_label()
        base_text = current_text.split(" (Server Last seen:")[0]
        self.status_item.set_label(f"{base_text} (Server Last seen: {time_text})")

    def toggle_mic_transcription(self, *args) -> None:
        """Toggle recording + transcription of mic."""
        if not self.is_recording_mic_for_transcription:
            self.start_mic_recording_for_transcription()
        else:
            self.stop_mic_recording_for_transcription()

    def toggle_recording_mic_and_output(self, *args) -> None:
        """Toggle recording of both microphone and system audio."""
        if not self.audio_process_for_recording_mic_and_output:
            self.start_mic_and_output_recording()
        else:
            self.stop_mic_and_output_recording()

    def start_mic_recording_for_transcription(self) -> None:
        """Start a new recording session."""
        self.is_recording_mic_for_transcription = True
        self.seen_segments.clear()
        self.current_session_text = []
        self.session_start_time = time.strftime("%Y-%m-%d_%H-%M-%S")

        if self.start_mic_recording_and_streaming_processes():
            self.recording_duration = 0
            self.recording_start_time = time.time()
            self.indicator.set_label(f"0/{self.max_recording_duration}s", "")
            self.timer_id = GLib.timeout_add(1000, self.update_timer)
            self.update_status(self.labels["recording"])
            GLib.timeout_add(100, self.process_text_queue)
        else:
            self.is_recording_mic_for_transcription = False
            self.indicator.set_label("", "")
            self.update_status(self.labels["recording_error"])

    def stop_mic_recording_for_transcription(self) -> None:
        """Stop the current mic-only recording session."""
        if self.current_session_text:
            self.save_session_transcript()
        self.is_recording_mic_for_transcription = False
        self.cleanup_recording()
        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = None
        self.indicator.set_label("", "")
        self.update_status(self.labels["ready"])

    def start_mic_recording_and_streaming_processes(self) -> bool:
        """Start the recording and network processes.

        This method:
        1. Starts arecord to capture audio
        2. Pipes audio to netcat (nc) which sends it to the whisper server
        3. Creates a thread to read the server's responses
        """
        try:
            self.audio_process_for_mic_transcription = subprocess.Popen(
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

            self.netcat_process = subprocess.Popen(
                ["nc", self.config["server"]["host"], self.config["server"]["port"]],
                stdin=self.audio_process_for_mic_transcription.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=os.setsid,
            )

            if self.audio_process_for_mic_transcription.stdout:
                self.audio_process_for_mic_transcription.stdout.close()

            self.read_thread = threading.Thread(target=self.read_output)
            self.read_thread.daemon = True
            self.read_thread.start()

            self.last_successful_connection = time.time()
            self.update_server_last_connection_time_label()
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
        while (
            self.is_recording_mic_for_transcription
            and self.netcat_process
            and self.netcat_process.stdout
        ):
            try:
                line = self.netcat_process.stdout.readline().decode().strip()
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
        return self.is_recording_mic_for_transcription

    def type_text(self, text: str) -> bool:
        """Type the text and save to transcript."""
        try:
            # Append to current session first in case the text is not typed. We don't want to lose anything.
            self.append_to_transcript(text.strip())
            subprocess.run(
                ["xdotool", "type", "--clearmodifiers", "--delay", "1", text],
                check=True,
            )
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error typing text: {e}")
            return False

    def append_to_transcript(self, text: str) -> None:
        """Append text to the current session."""
        self.current_session_text.append(text)

    def save_session_transcript(self) -> None:
        """Save the current session's transcript to the JSON file."""
        try:
            # Create empty JSON if file doesn't exist
            if not self.transcript_path.exists():
                with open(self.transcript_path, "w", encoding="utf-8") as f:
                    json.dump({}, f, indent=2)

            # Read existing transcripts
            with open(self.transcript_path, "r", encoding="utf-8") as f:
                transcripts = json.load(f)

            # Add new session
            if self.session_start_time:
                transcripts[self.session_start_time] = " ".join(
                    self.current_session_text
                )

            # Write back to file
            with open(self.transcript_path, "w", encoding="utf-8") as f:
                json.dump(transcripts, f, indent=2)

        except Exception as e:
            print(f"Error saving transcript: {e}")

    def update_timer(self) -> bool:
        """Update the recording timer display."""
        if not self.is_recording_mic_for_transcription:
            return False

        if self.recording_start_time is not None:
            self.recording_duration = int(time.time() - self.recording_start_time)
        else:
            self.recording_duration = 0

        # Show current/max duration format
        self.indicator.set_label(
            f"{self.recording_duration}/{self.max_recording_duration}s", ""
        )

        if self.recording_duration >= self.max_recording_duration:
            # Stop the timer, toggle recording, and play a beep sound to indicate the end of the recording
            GLib.idle_add(self.toggle_mic_transcription)
            subprocess.run(
                ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"]
            )
            return False

        return True

    def cleanup_recording(self) -> None:
        """Clean up recording processes."""
        for proc_name, proc in [
            ("audio", self.audio_process_for_mic_transcription),
            ("network", self.netcat_process),
        ]:
            if proc:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except Exception as e:
                    print(f"Error killing {proc_name} process: {e}")

        self.audio_process_for_mic_transcription = None
        self.netcat_process = None

    def cleanup_and_quit(self, *args) -> bool:
        """Clean up and quit the application."""
        self.is_recording_mic_for_transcription = False
        self.cleanup_recording()
        self.stop_mic_recording_for_transcription()
        self.stop_mic_and_output_recording()

        # Clean up any temporary files that might exist
        if hasattr(self, "current_recording_timestamp"):
            try:
                mic_file = (
                    self.recording_path / f"{self.current_recording_timestamp}_mic.wav"
                )
                output_file = (
                    self.recording_path
                    / f"{self.current_recording_timestamp}_output.wav"
                )
                if mic_file.exists():
                    mic_file.unlink()
                if output_file.exists():
                    output_file.unlink()
            except Exception as e:
                print(f"Error cleaning up temporary files: {e}")

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
        while True:  # Keep showing dialog until valid input or cancel
            response = self.settings_dialog.run()

            if response == Gtk.ResponseType.OK:
                if self.settings_dialog.validate():
                    self.settings_dialog.save_settings()
                    # Rebind hotkeys with new combination
                    Keybinder.unbind(self.mic_hotkey)
                    self.mic_hotkey = self.config["hotkey"]["mic_only"]
                    Keybinder.bind(self.mic_hotkey, self.toggle_mic_transcription)
                    Keybinder.unbind(self.mic_and_output_hotkey)
                    self.mic_and_output_hotkey = self.config["hotkey"]["mic_and_output"]
                    Keybinder.bind(
                        self.mic_and_output_hotkey, self.toggle_recording_mic_and_output
                    )
                    # Update max recording duration
                    self.max_recording_duration = int(
                        self.config["recording"]["max_duration"]
                    )
                    # Update status labels with new hotkey
                    self.setup_status_labels()
                    self.update_status(self.labels["ready"])
                    break  # Exit loop only if validation succeeds
                # If validation fails, continue loop to show dialog again
            else:  # CANCEL or dialog closed
                break  # Exit loop if user cancels

        self.settings_dialog.destroy()
        self.settings_dialog = None

    def show_transcript_history(self, widget) -> None:
        """Show the transcript history dialog."""
        dialog = TranscriptViewerDialog(None, self.transcript_path)
        dialog.run()
        dialog.destroy()

    def start_mic_and_output_recording(self) -> None:
        """Start recording both microphone and system audio output to separate files."""
        try:
            print("Starting mic and output recording...")
            self.current_recording_timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            mic_file = (
                self.recording_path / f"{self.current_recording_timestamp}_mic.wav"
            )
            output_file = (
                self.recording_path / f"{self.current_recording_timestamp}_output.wav"
            )

            print(f"Recording to: {mic_file} and {output_file}")

            # Start two separate ffmpeg processes
            mic_cmd = [
                "ffmpeg",
                "-f",
                "pulse",
                "-i",
                "default",
                "-ac",
                "1",  # Mono for mic
                str(mic_file),
            ]

            output_cmd = [
                "ffmpeg",
                "-f",
                "pulse",
                "-i",
                "$(pactl get-default-sink).monitor",  # This might be the issue - shell expansion
                "-ac",
                "1",  # Mono for system audio
                str(output_file),
            ]

            print(f"Starting mic recording: {' '.join(mic_cmd)}")
            # Start both recording processes with stderr redirected to stdout
            self.mic_recording_proc = subprocess.Popen(
                mic_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Redirect stderr to stdout
                preexec_fn=os.setsid,
            )

            # Get the actual sink monitor name
            sink_monitor = (
                subprocess.check_output(
                    ["pactl", "get-default-sink"], text=True
                ).strip()
                + ".monitor"
            )

            output_cmd = [
                "ffmpeg",
                "-f",
                "pulse",
                "-i",
                sink_monitor,
                "-ac",
                "1",
                str(output_file),
            ]

            print(f"Starting output recording: {' '.join(output_cmd)}")
            self.output_recording_proc = subprocess.Popen(
                output_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Redirect stderr to stdout
                preexec_fn=os.setsid,
            )

            # Start threads to monitor ffmpeg output
            threading.Thread(
                target=self.monitor_process_output,
                args=(self.mic_recording_proc, "mic ffmpeg"),
                daemon=True,
            ).start()
            threading.Thread(
                target=self.monitor_process_output,
                args=(self.output_recording_proc, "output ffmpeg"),
                daemon=True,
            ).start()

            self.is_recording_mic_and_output = True
            self.is_recording_mic_for_transcription = True
            self.update_status(self.labels["recording_mic_and_output"])
            print("Recording started successfully")

        except Exception as e:
            print(f"Error starting mic+output audio recording: {e}")
            self.is_recording_mic_for_transcription = False
            self.cleanup_recording_processes()

    def monitor_process_output(self, process: subprocess.Popen, name: str) -> None:
        """Monitor and log output from a subprocess."""
        try:
            while True:
                if process.stdout:
                    line = process.stdout.readline()
                    if not line:
                        break
                    print(f"{name}: {line.decode().strip()}")
        except Exception as e:
            print(f"Error monitoring {name}: {e}")

    def stop_mic_and_output_recording(self) -> None:
        """Stop recording and combine the audio files with normalization."""
        if self.is_recording_mic_and_output:
            try:
                # Stop recording processes
                self.cleanup_recording_processes()
                time.sleep(0.5)

                # Combine files with normalization and mixing
                mic_file = (
                    self.recording_path / f"{self.current_recording_timestamp}_mic.wav"
                )
                output_file = (
                    self.recording_path
                    / f"{self.current_recording_timestamp}_output.wav"
                )
                final_file = (
                    self.recording_path
                    / f"{self.current_recording_timestamp}_combined.wav"
                )

                # More explicit ffmpeg command with format specifications
                combine_cmd = [
                    "ffmpeg",
                    "-i",
                    str(mic_file),
                    "-i",
                    str(output_file),
                    "-filter_complex",
                    "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=mono[a0];"
                    "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=mono[a1];"
                    "[a0]volume=1.5[v0];[a1]volume=0.8[v1];"
                    "[v0][v1]amerge=inputs=2,pan=stereo|c0=c0|c1=c1[aout]",
                    "-map",
                    "[aout]",
                    str(final_file),
                ]

                print(f"Running combine command: {' '.join(combine_cmd)}")

                # Run ffmpeg and capture both stdout and stderr
                process = subprocess.Popen(
                    combine_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )

                stdout, stderr = process.communicate()
                if process.returncode != 0:
                    print(f"FFmpeg stdout: {stdout}")
                    print(f"FFmpeg stderr: {stderr}")
                    raise subprocess.CalledProcessError(
                        process.returncode, combine_cmd, stdout, stderr
                    )

                print("Successfully combined audio files")

                # Clean up temporary files only if combine was successful
                mic_file.unlink()
                output_file.unlink()

            except Exception as e:
                print(f"Error stopping and combining audio recording: {e}")
                # Don't delete temp files if combine failed
            finally:
                self.is_recording_mic_for_transcription = False
                self.is_recording_mic_and_output = False
                self.audio_process_for_recording_mic_and_output = None
                self.update_status(self.labels["ready"])

    def cleanup_recording_processes(self) -> None:
        """Helper to clean up recording processes."""
        if hasattr(self, "mic_recording_proc") and self.mic_recording_proc:
            os.killpg(os.getpgid(self.mic_recording_proc.pid), signal.SIGTERM)
            self.mic_recording_proc = None
        if hasattr(self, "output_recording_proc") and self.output_recording_proc:
            os.killpg(os.getpgid(self.output_recording_proc.pid), signal.SIGTERM)
            self.output_recording_proc = None

    def run(self) -> None:
        """Start the application main loop."""
        Gtk.main()


if __name__ == "__main__":
    setup_display()
    app = WhisperIndicatorApp()
    app.run()
