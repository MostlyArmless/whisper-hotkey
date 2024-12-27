# Whisper Hotkey

This depends on you running [`whisper_online_server.py`](https://github.com/ufal/whisper_streaming/blob/main/whisper_online_server.py) on another local machine with a good GPU like this:

```bash
export LD_LIBRARY_PATH=`python3 -c 'import os; import nvidia.cublas.lib; import nvidia.cudnn.lib; print(os.path.dirname(nvidia.cublas.lib.__file__) + ":" + os.path.dirname(nvidia.cudnn.lib.__file__))'`
python whisper_online_server.py --backend faster-whisper --lan en --task transcribe --model small.en --host 0.0.0.0
```

Then, on your desktop or whatever other ubuntu machine you're using, you can use this tool to give you a hotkey + GUI that'll stream audio to the whisper server and stream the text into whatever app you have focused at the current cursor position.

## Setup

Install dependencies:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-keybinder gir1.2-keybinder-3.0 xdotool python3-gi-cairo
pip install PyGObject
```

## Run

This DOES NOT WORK from the vs code built in terminal if you have it installed as a snap package, run it from a native terminal window.

```bash
python whisper_hotkey.py
```

Now hit the Favorites button to start/stop recording

## TODO

The `install.sh` script is meant to install this as a systemd service, but it doesn't work yet.
For now I'm just using an alias in my zshrc to launch this python script, and subsequently using the Favorites key to toggle recording on/off.
