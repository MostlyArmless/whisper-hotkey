from whisper_hotkey.utils import setup_display
from whisper_hotkey.main import WhisperIndicatorApp


def main():
    setup_display()
    app = WhisperIndicatorApp()
    app.run()


if __name__ == "__main__":
    main()
