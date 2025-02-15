import configparser
from pathlib import Path


class Config:
    """Handles configuration loading and management."""

    @staticmethod
    def load() -> configparser.ConfigParser:
        config = configparser.ConfigParser()

        # These default values will be used if no config file exists
        config["server"] = {"host": "localhost", "port": "43007"}
        config["hotkey"] = {
            "mic_only": "<Ctrl><Alt>R",
            "mic_and_output": "<Ctrl><Alt>E",
        }
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
