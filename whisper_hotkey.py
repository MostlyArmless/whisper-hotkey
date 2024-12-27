#!/usr/bin/env python3
"""
GTK-based application for recording and transcribing audio using Whisper.
Allows toggling recording with a hotkey and types the transcribed text.
"""

import gi
from typing import Optional, Set, Tuple
from pathlib import Path
import subprocess
import threading
import signal
import os
import time
import queue
import logging
from dataclasses import dataclass
import argparse
import json
from typing import Optional, Set, Tuple, NamedTuple
from pathlib import Path

gi.require_version('Gtk', '3.0')
gi.require_version('Keybinder', '3.0')
from gi.repository import Gtk, GLib, Keybinder

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class TranscriptionSegment:
    """Represents a segment of transcribed text with timing information."""
    text: str
    received_time: float
    chunk_duration: float
    chunk_start_time: float

class ServerConfig(NamedTuple):
    """Configuration for the Whisper server connection."""
    host: str
    port: int

class WhisperHotkeyApp:
    """Main application class for the Whisper Hotkey transcription tool."""

    CONFIG_FILE = Path(__file__).parent / "whisper_config.json"
    DEFAULT_PORT = 43007
    
    @classmethod
    def load_config(cls) -> ServerConfig:
        """Load server configuration from file or return default values."""
        try:
            if cls.CONFIG_FILE.exists():
                with open(cls.CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                    return ServerConfig(
                        host=config.get('host', 'localhost'),
                        port=config.get('port', cls.DEFAULT_PORT)
                    )
        except Exception as e:
            logger.error(f"Error loading config: {e}")
        
        return ServerConfig('localhost', cls.DEFAULT_PORT)

    @classmethod
    def save_config(cls, host: str, port: int) -> None:
        """Save server configuration to file."""
        try:
            with open(cls.CONFIG_FILE, 'w') as f:
                json.dump({'host': host, 'port': port}, f)
        except Exception as e:
            logger.error(f"Error saving config: {e}")

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None) -> None:
        """
        Initialize the WhisperHotkey application.
        
        Args:
            host: Optional server host address
            port: Optional server port number
        """
        # Load config first
        saved_config = self.load_config()
        
        # Use provided values or fall back to saved/default values
        self.server_config = ServerConfig(
            host=host or saved_config.host,
            port=port or saved_config.port
        )
        
        print(f'Using whisper host {self.server_config.host} on port {self.server_config.port}')

        # Save new configuration if host was provided
        if host:
            self.save_config(self.server_config.host, self.server_config.port)
        
        # Initialize the rest of the application
        self._setup_window()
        self._init_variables()
        self._setup_keybinding()
        self._setup_periodic_tasks()

    def _setup_window(self) -> None:
        """Initialize and configure the GTK window and its widgets."""
        self.window = Gtk.Window(title="Whisper Hotkey")
        self.window.set_keep_above(True)
        self.window.set_decorated(True)
        self.window.set_default_size(150, 40)

        # Set up window layout
        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.window.add(outer_box)

        header = Gtk.HeaderBar()
        header.set_decoration_layout("close:")
        header.set_show_close_button(True)
        self.window.set_titlebar(header)

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        outer_box.pack_start(self.box, True, True, 0)

        self.label = Gtk.Label(label="🎙️ Ready (Favorites key)")
        self.box.pack_start(self.label, True, True, 0)

        self._setup_window_visual()
        self.window.show_all()

    def _setup_window_visual(self) -> None:
        """Configure window transparency and visual settings."""
        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.window.set_visual(visual)
        self.window.set_app_paintable(True)
        self.window.connect("draw", self._draw_window_background)

    def _init_variables(self) -> None:
        """Initialize instance variables."""
        self.recording: bool = False
        self.audio_proc: Optional[subprocess.Popen] = None
        self.nc_proc: Optional[subprocess.Popen] = None
        self.text_queue: queue.Queue = queue.Queue()
        self.seen_segments: Set[str] = set()
        self.recording_start_time: Optional[float] = None
        self.transcript_path: Path = Path.home() / "whisper-transcript.txt"

    def _setup_keybinding(self) -> None:
        """Set up global hotkey binding."""
        Keybinder.init()
        Keybinder.bind("XF86Favorites", self.toggle_recording)
        self.window.connect("delete-event", self.cleanup_and_quit)

    def _setup_periodic_tasks(self) -> None:
        """Set up periodic task for processing the text queue."""
        GLib.timeout_add(100, self.process_text_queue)

    def _draw_window_background(self, widget: Gtk.Widget, context: 'cairo.Context') -> bool:
        """Draw semi-transparent window background."""
        context.set_source_rgba(0, 0, 0, 0.8)
        context.set_operator(1)
        context.paint()
        return False

    def append_to_transcript(self, text: str) -> None:
        """Append transcribed text to the transcript file with timestamp."""
        try:
            timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
            with open(self.transcript_path, 'a', encoding='utf-8') as f:
                f.write(f"{timestamp} - {text}\n")
        except Exception as e:
            logger.error(f"Error writing to transcript: {e}")

    def type_text(self, text: str) -> bool:
        """Type the transcribed text using xdotool."""
        try:
            subprocess.run([
                'xdotool', 'type', '--clearmodifiers', '--delay', '1', text
            ], check=True)
            self.append_to_transcript(text.strip())
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error typing text: {e}")
            return False

    def process_text_queue(self) -> bool:
        """Process queued transcription segments."""
        try:
            while True:
                segment = self.text_queue.get_nowait()
                self.type_text(segment.text + " ")
                self.text_queue.task_done()
        except queue.Empty:
            pass
        return self.recording

    def read_output(self) -> None:
        """Read and process output from the transcription service."""
        while self.recording and self.nc_proc:
            try:
                line = self.nc_proc.stdout.readline().decode().strip()
                if line:
                    self._process_transcription_line(line)
            except Exception as e:
                logger.error(f"Error reading output: {e}")
                break

    def _process_transcription_line(self, line: str) -> None:
        """Process a single line of transcription output."""
        parts = line.split('  ', 1)
        if len(parts) != 2:
            return

        timestamp, text = parts
        start_ms, end_ms = map(int, timestamp.split())
        
        if timestamp not in self.seen_segments:
            self.seen_segments.add(timestamp)
            chunk_duration = (end_ms - start_ms) / 1000
            chunk_start_time = start_ms / 1000
            received_time = time.time() - self.recording_start_time
            
            segment = TranscriptionSegment(
                text=text,
                received_time=received_time,
                chunk_duration=chunk_duration,
                chunk_start_time=chunk_start_time
            )
            self.text_queue.put(segment)

    def start_recording(self) -> bool:
        """Start the recording and transcription processes."""
        try:
            self.recording_start_time = time.time()
            self._start_audio_process()
            self._start_network_process()
            self._start_reading_thread()
            return True
        except Exception as e:
            logger.error(f"Error starting recording: {e}")
            self.cleanup_recording()
            return False

    def _start_audio_process(self) -> None:
        """Start the audio recording process."""
        self.audio_proc = subprocess.Popen(
            ['arecord', '-f', 'S16_LE', '-c1', '-r', '16000', '-t', 'raw', '-D', 'default'],
            stdout=subprocess.PIPE,
            preexec_fn=os.setsid
        )

    def _start_network_process(self) -> None:
        """Start the network connection to the transcription service."""
        self.nc_proc = subprocess.Popen(
            ['nc', self.server_config.host, str(self.server_config.port)],
            stdin=self.audio_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid
        )
        self.audio_proc.stdout.close()

    def _start_reading_thread(self) -> None:
        """Start the thread for reading transcription output."""
        self.read_thread = threading.Thread(target=self.read_output)
        self.read_thread.daemon = True
        self.read_thread.start()

    def cleanup_recording(self) -> None:
        """Clean up recording processes."""
        for proc_name, proc in [("audio", self.audio_proc), ("network", self.nc_proc)]:
            if proc:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except Exception as e:
                    logger.error(f"Error cleaning up {proc_name} process: {e}")

        self.audio_proc = None
        self.nc_proc = None

    def cleanup_and_quit(self, *args) -> bool:
        """Clean up and quit the application."""
        self.recording = False
        self.cleanup_recording()
        Gtk.main_quit()
        return False

    def toggle_recording(self, key: Optional[str] = None) -> None:
        """Toggle recording state."""
        if not self.recording:
            self._start_new_recording()
        else:
            self._stop_recording()

    def _start_new_recording(self) -> None:
        """Start a new recording session."""
        self.recording = True
        self.seen_segments.clear()
        if self.start_recording():
            self.label.set_text("🎤 Recording... (Favorites key to stop)")
            GLib.timeout_add(100, self.process_text_queue)
        else:
            self.recording = False
            self.label.set_text("🚫 Recording Error")

    def _stop_recording(self) -> None:
        """Stop the current recording session."""
        self.recording = False
        self.cleanup_recording()
        self.label.set_text("🎙️ Ready (Favorites key)")

    def run(self) -> None:
        """Start the application main loop."""
        Gtk.main()


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Whisper Hotkey - Voice transcription tool'
    )
    parser.add_argument(
        '--host',
        help='Whisper server host address'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=WhisperHotkeyApp.DEFAULT_PORT,
        help=f'Whisper server port (default: {WhisperHotkeyApp.DEFAULT_PORT})'
    )
    return parser.parse_args()

def main() -> None:
    """Application entry point."""
    args = parse_args()
    app = WhisperHotkeyApp(host=args.host, port=args.port)
    app.run()

if __name__ == "__main__":
    main()