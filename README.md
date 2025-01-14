# Whisper Hotkey

This is an Ubuntu tool that provides a hotkey to start audio transcription from your microphone, using the [whisper_streaming](https://github.com/ufal/whisper_streaming) server. The transcribed text will be typed into whatever app you have focused at the current cursor position.

## Server requirements

You must first setup and run a [`whisper_online_server.py`](https://github.com/ufal/whisper_streaming/blob/main/whisper_online_server.py) on either your own machine or another local machine with a good GPU.
Follow their setup instructions, then you'll run it like this:

```bash
export LD_LIBRARY_PATH=`python3 -c 'import os; import nvidia.cublas.lib; import nvidia.cudnn.lib; print(os.path.dirname(nvidia.cublas.lib.__file__) + ":" + os.path.dirname(nvidia.cudnn.lib.__file__))'`
python whisper_online_server.py --backend faster-whisper --lan en --task transcribe --model small.en --host 0.0.0.0
```

Then, on your ubuntu computer, you can use this tool to give you a hotkey + GUI that'll stream audio to the whisper server and stream the text into whatever app you have focused at the current cursor position.

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

You should now see a microphone icon appear in your toolbar. Click on it to open the GUI, where you can see the current status of the whisper client, and change the hotkey and the whisper server IP address and port number.

### Modify config.ini file to point to the correct whisper server

```bash
nano ~/.config/whisper-client/config.ini
# Modify the `server` field to point to the your whisper server IP address and port number, if not already set correctly
```

## Run

The service should automatically start when you log into Ubuntu. To start audio transcription, just hit the hotkey which is `Ctrl+Alt+R` by default. The text will be typed into whatever app you have focused at the current cursor position. All transcribed text will be saved to `~/whisper-transcript.txt`, regardless of whether it is successfully typed into a target application or not, so you can always refer back to it later.

## Troubleshooting

You can find the service definition file at `~/.config/systemd/user/whisper-client.service` if needed.
To see the logs run `journalctl --user -u whisper-client.service -f`.
If you make changes to the service file, you can reload it with `systemctl --user daemon-reload`.
To restart the service run `systemctl --user restart whisper-client.service`.