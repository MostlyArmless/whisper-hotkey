# Whisper Hotkey

This is an Ubuntu tool that provides a hotkey to start audio transcription from your microphone, using the [whisper_streaming](https://github.com/ufal/whisper_streaming) server. The transcribed text will be typed into whatever app you have focused at the current cursor position.

## Server requirements

You must first setup and run a whisper_streaming server on either your own machine or another local machine with a good GPU.
I've forked the original whisper_streaming repo and made some changes to make it easier to setup and run.
To set up the server as a systemd service that will run on system boot, follow [my setup instructions](https://github.com/MostlyArmless/whisper_streaming/blob/mike/mike-readme.md).

Then, on your Ubuntu computer, you can use this tool to give you a hotkey that'll stream audio to the whisper server and stream the text into whatever app you have focused at the current cursor position.

## Setup

Note: This tool has only been tested on Ubuntu 22.04 with the standard GNOME desktop environment, with Python 3.10.12.
It may work on other versions of Ubuntu or other Linux distributions, but it has not been tested.

`git clone` this repo `cd` into it, then run:

```bash
# Feel free to read this script before running it.
# It will apt install some packages and pip install some python packages in a venv in this repo directory.
chmod +x install.sh
./install.sh
```

You should now see a microphone icon appear in your toolbar. Click on it to open the menu, which provides several options:

- Toggle Recording: Start/stop transcription (same as using the hotkey)
- Settings: Configure server connection, hotkey, and recording duration
- Transcript History: View and copy previous transcriptions
- Restart/Quit Service: Control the whisper-client service

## Configuration

All settings can be configured through the Settings dialog in the menu:

- Whisper server IP address and port number
- Hotkey combination (default: Ctrl+Alt+R)
- Maximum recording duration in seconds (default: 60)

## Usage

The service automatically starts when you log into Ubuntu. To start audio transcription:

1. Press the hotkey (default: Ctrl+Alt+R) or use the menu's Toggle Recording option
2. Speak into your microphone
3. The transcribed text will appear at your cursor position
4. Press the hotkey again to stop recording, or let it stop automatically after the configured duration

The toolbar icon shows:
- Recording status and duration (e.g., "12/60s" while recording)
- Server connection status
- Time since last server contact

## Transcripts

All transcribed text is automatically saved and can be accessed through the Transcript History option in the menu. The history viewer shows:
- Timestamps for each recording session
- Full text of each transcription
- Copy buttons to easily copy any transcript to the clipboard

Transcripts are stored in `~/whisper-transcript.json` for future reference, even if they weren't successfully typed into an application.

## Troubleshooting

You can find the service definition file at `~/.config/systemd/user/whisper-client.service` if needed.
To see the logs run `journalctl --user -u whisper-client.service -f`.
If you make changes to the service file, you can reload it with `systemctl --user daemon-reload`.
To restart the service run `systemctl --user restart whisper-client.service`.

## Feature wishlist

* Automatically detect when there is no valid microphone connected and disable the microphone icon and hotkey.
  * The icon should change to the "no microphone" icon.