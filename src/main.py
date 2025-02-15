from pathlib import Path
import queue
import signal
import socket
import subprocess
import threading
import time
from typing import Optional, Set
import os
import json

import gi
from config import Config
from ui.settings import SettingsDialog
from ui.transcript import TranscriptViewerDialog
from utils import setup_display

# These version requirements must be set before importing the gi modules
# They ensure we're using compatible versions of GTK and related libraries
# for creating the GUI, handling global hotkeys, and system tray functionality
gi.require_version("Gtk", "3.0")
gi.require_version("Keybinder", "3.0")
gi.require_version("AppIndicator3", "0.1")
from gi.repository import Gtk, GLib, Keybinder, AppIndicator3, Gdk  # noqa: E402 # type: ignore[import]


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
        self.settings_dialog = None

        self.init_state()
        self.init_ui()
        self.init_keybinding()
        self.set_up_server_status_check_timer()

    def toggle_mic_transcription(self, *args) -> None:
        """Toggle recording + transcription of mic."""
        if not self.is_recording:
            self.start_mic_recording_for_transcription()
        else:
            self.stop_mic_recording_for_transcription()

    def toggle_recording_mic_and_output(self, *args) -> None:
        """Toggle recording of both microphone and system audio."""
        if not self.audio_process_for_recording_mic_and_output:
            self.start_mic_and_output_recording()
        else:
            self.stop_mic_and_output_recording()

    def init_state(self) -> None:
        """Initialize application state variables.

        These variables track:
        - Recording state and processes
        - Text queue for processed speech
        - Timers and durations
        - File paths and settings
        """
        self.is_recording = False
        self.audio_process_for_mic_transcription: Optional[subprocess.Popen] = None
        self.netcat_process: Optional[subprocess.Popen] = None
        self.text_queue: queue.Queue = queue.Queue()
        self.seen_segments: Set[str] = set()
        self.recording_start_time: Optional[float] = None
        self.recording_duration = 0
        self.server_last_seen_at = time.time()
        # Used to periodically update the recording duration in the toolbar:
        self.timer_id_for_gui_updates: Optional[int] = None
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
            "ready": "🎙️ Ready",
            "transcribing": f"🔴 Transcribing Mic (Press {self.mic_hotkey} to stop)",
            "recording_mic_and_output": f"🔴 Recording Mic and Output (Press {self.mic_and_output_hotkey} to stop)",
            "recording_error": "🚫 Recording Error",
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

    def set_up_server_status_check_timer(self) -> None:
        """Set up a timer to check the connection status to the whisper server."""
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
                self.server_last_seen_at = time.time()
                if not self.is_recording:
                    self.update_status_text(self.labels["ready"])
            elif not self.is_recording:
                self.update_status_text(self.labels["server_error"])

        except Exception as e:
            print(f"Server check error: {e}")
            if not self.is_recording:
                self.update_status_text(self.labels["server_error"])

        self.update_server_last_connection_time_label()
        return True

    def update_status_text(self, text: str) -> None:
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
        elapsed = time.time() - self.server_last_seen_at
        if elapsed < 60:
            time_text = f"{int(elapsed)}s ago"
        elif elapsed < 3600:
            time_text = f"{int(elapsed / 60)}m ago"
        else:
            time_text = f"{int(elapsed / 3600)}h ago"

        current_text = self.status_item.get_label()
        base_text = current_text.split(" (Server Last seen:")[0]
        self.status_item.set_label(f"{base_text} (Server Last seen: {time_text})")

    def start_mic_recording_for_transcription(self) -> None:
        """Start a new recording session."""
        self.is_recording = True
        self.seen_segments.clear()
        self.current_session_text = []
        self.session_start_time = time.strftime("%Y-%m-%d_%H-%M-%S")

        if self.start_mic_recording_and_streaming_processes():
            GLib.timeout_add(50, self.process_text_queue)
            self.recording_duration = 0
            self.recording_start_time = time.time()
            self.indicator.set_label(f"0/{self.max_recording_duration}s", "")
            self.timer_id_for_gui_updates = GLib.timeout_add(
                1000, self.update_timer_for_transcription
            )
            self.update_status_text(self.labels["transcribing"])
        else:
            self.is_recording = False
            self.indicator.set_label("", "")
            self.update_status_text(self.labels["recording_error"])

    def stop_mic_recording_for_transcription(self) -> None:
        """Stop the current mic-only recording session."""
        if self.current_session_text:
            self.save_session_transcript()
        self.is_recording = False
        self.kill_transcription_processes()
        self.reset_to_ready_state()

    def reset_to_ready_state(self) -> None:
        """Cancel the timer for periodically updating the recording duration in the toolbar and reset the indicator label and status text."""
        self.is_recording = False
        if self.timer_id_for_gui_updates:
            GLib.source_remove(self.timer_id_for_gui_updates)
            self.timer_id_for_gui_updates = None
        self.indicator.set_label("", "")
        self.update_status_text(self.labels["ready"])

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
            # Make it a daemon thread so it doesn't block the main thread from exiting
            self.read_thread.daemon = True
            self.read_thread.start()
            return True

        except Exception as e:
            print(f"Error starting recording: {e}")
            self.stop_mic_and_output_recording()
            return False

    def read_output(self) -> None:
        """Read and process output from the whisper server.

        The server sends lines in format:
        "start_ms end_ms  transcribed_text"

        This method parses these lines and queues the text for typing.
        """
        while self.is_recording and self.netcat_process and self.netcat_process.stdout:
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
        return self.is_recording

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

    def update_timer_for_transcription(self) -> bool:
        """Update the recording timer display."""
        if not self.is_recording:
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
            return False  # Don't continue the timer

        return True  # Continue the timer

    def update_timer_for_recording_mic_and_output(self) -> bool:
        """Update the recording timer display."""

        if not self.is_recording:
            print("Not recording, returning False")
            return False

        if self.recording_start_time is not None:
            duration = time.time() - self.recording_start_time
            print(f"Recording duration: {duration}")
            self.recording_duration = int(duration)
        else:
            print("Recording start time is None, setting duration to 0")
            self.recording_duration = 0

        self.indicator.set_label(f"{self.recording_duration}s", "")

        return True

    def kill_transcription_processes(self) -> None:
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
        self.stop_mic_recording_for_transcription()
        self.stop_mic_and_output_recording()

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
                    self.update_status_text(self.labels["ready"])
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
            self.recording_duration = 0
            self.recording_start_time = time.time()
            self.indicator.set_label(f"0s", "")
            self.timer_id_for_gui_updates = GLib.timeout_add(
                1000, self.update_timer_for_recording_mic_and_output
            )
            current_recording_timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            mic_file = self.recording_path / f"{current_recording_timestamp}_mic.wav"
            output_file = (
                self.recording_path / f"{current_recording_timestamp}_output.wav"
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
                "$(pactl get-default-sink).monitor",
                "-ac",
                "1",  # Mono for system audio
                str(output_file),
            ]

            print(f"Starting mic recording: {' '.join(mic_cmd)}")
            # Start both recording processes with stderr redirected to stdout
            self.mic_recording_proc = subprocess.Popen(
                mic_cmd,
                stdout=subprocess.PIPE,
                # stderr=subprocess.STDOUT,  # Redirect stderr to stdout
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
                # stderr=subprocess.STDOUT,  # Redirect stderr to stdout
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

            # Used to track if the recording is still running
            self.audio_process_for_recording_mic_and_output = self.mic_recording_proc
            self.is_recording = True
            self.timer_id_for_gui_updates = GLib.timeout_add(
                1000, self.update_timer_for_recording_mic_and_output
            )
            self.update_status_text(self.labels["recording_mic_and_output"])
            print("Recording started successfully")

        except Exception as e:
            print(f"Error starting mic+output audio recording: {e}")
            self.is_recording = False
            self.kill_recording_processes()

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
        if self.audio_process_for_recording_mic_and_output:
            try:
                self.kill_recording_processes()
            except Exception as e:
                print(f"Error stopping audio recording: {e}")
            finally:
                self.reset_to_ready_state()
                self.audio_process_for_recording_mic_and_output = None

    def kill_recording_processes(self) -> None:
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
