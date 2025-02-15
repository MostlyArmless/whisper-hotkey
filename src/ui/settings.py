import re
import socket
from pathlib import Path
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk  # noqa: E402 # type: ignore[import]


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
