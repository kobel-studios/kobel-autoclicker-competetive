# Auto-Clicker Hub

A simple GUI auto-clicker built with Tkinter.

## Features

- **Adjustable interval** between clicks using **minutes**, **seconds**, and **milliseconds**.
- **Mouse button** selector (left / right / middle).
- **F6 hotkey** to start/stop from anywhere, plus an on-screen Start/Stop button.
- **Esc** (or closing the window) quits.
- **Fail-safe**: slam your mouse to a screen corner to instantly abort (PyAutoGUI).

## Setup

```bash
pip install -r requirements.txt
```

## Run

Run **without a console window popping up** (recommended) using `pythonw`:

```bash
pythonw autoclicker_hub.py
```

Or just double-click **`Launch Auto-Clicker Hub.vbs`**, which starts it hidden.

Running with regular `python` also works but shows a console window:

```bash
python autoclicker_hub.py
```

## How it works

1. Set the time between clicks (minutes + seconds + milliseconds are added together).
2. Move your mouse to the target and press **F6** (or click **Start**).
3. It clicks continuously at the cursor's current location until you press **F6** again (or click **Stop**).

## Notes

- Global hotkeys via the `keyboard` library may require running the terminal **as Administrator** on Windows.
- Clicks land wherever the cursor currently is, so position your mouse before starting.
