This depends on you running `whisper_streaming_server.py` on the razr laptop with the good GPU like this:
```bash
export LD_LIBRARY_PATH=`python3 -c 'import os; import nvidia.cublas.lib; import nvidia.cudnn.lib; print(os.path.dirname(nvidia.cublas.lib.__file__) + ":" + os.path.dirname(nvidia.cudnn.lib.__file__))'`
python whisper_online_server.py --backend faster-whisper --lan en --task transcribe --model small --host 0.0.0.0
```

Then, on your desktop or whatever other ubuntu machine you're using, you can use this tool to give you a hotkey + GUI that'll stream audio to the whisper server and stream the text into whatever app you have focused at the current cursor position.

# Setup
install dependencies
```bash
sudo apt install python3-gi gir1.2-gtk-3.0 python3-keybinder gir1.2-keybinder-3.0 xdotool python3-gi-cairo
pip install PyGObject
```

# Run
This DOES NOT WORK from the vs code built in terminal if you have it installed as a snap package, run it from a native terminal window.
```bash
python whisper_hotkey.py
```
Now hit ctrl+alt+R to start/stop recording