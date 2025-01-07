# Whisper Hotkey

This depends on you running [`whisper_online_server.py`](https://github.com/ufal/whisper_streaming/blob/main/whisper_online_server.py) on another local machine with a good GPU. Run it like this:

```bash
export LD_LIBRARY_PATH=`python3 -c 'import os; import nvidia.cublas.lib; import nvidia.cudnn.lib; print(os.path.dirname(nvidia.cublas.lib.__file__) + ":" + os.path.dirname(nvidia.cudnn.lib.__file__))'`
python whisper_online_server.py --backend faster-whisper --lan en --task transcribe --model small.en --host 0.0.0.0
```

Then, on your desktop or whatever other ubuntu machine you're using, you can use this tool to give you a hotkey + GUI that'll stream audio to the whisper server and stream the text into whatever app you have focused at the current cursor position.

## Setup

Install dependencies:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-keybinder gir1.2-keybinder-3.0 xdotool python3-gi-cairo gir1.2-appindicator3-0.1
pip install PyGObject
```

Copy the service file to its destination, then enable it to run at startup:

```bash
cp whisper-client.service ~/.config/systemd/user/whisper-client.service
systemctl --user enable whisper-client
systemctl --user start whisper-client
```

## Run

The service should automatically start when you log into ubuntu. To start audio transcription, just hit the hotkey which is `Ctrl+Alt+R` by default.