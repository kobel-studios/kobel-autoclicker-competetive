import json
import os
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from collections import deque
from datetime import datetime, timedelta
import urllib.request
import urllib.error

import keyboard
import pyautogui
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

matplotlib.use("TkAgg")


pyautogui.FAILSAFE = True
# We control timing via the interval, so disable PyAutoGUI's default 0.1s pause
# that is otherwise added after every click.
pyautogui.PAUSE = 0

HOTKEY = "f6"

# Dark theme palette
BG = "#1e1f22"
SURFACE = "#2b2d31"
FG = "#e6e6e6"
MUTED = "#a0a0a0"
ACCENT = "#3b82f6"
ACCENT_ACTIVE = "#2f6fd0"
ENTRY_BG = "#2b2d31"
BORDER = "#3a3d41"

CLICKING_COLOR = "#3fb950"
STOPPED_COLOR = "#e3b341"

# Secret word (case-insensitive) typed into the milliseconds field. Normally the
# milliseconds value cannot go under 1; the code word removes the delay entirely
# so it clicks as fast as the system allows.
SECRET_WORD = "kobel"
MIN_MILLIS = 1.0
DATA_FILE = "clicker_data.json"
MAX_DATA_AGE_WEEKS = 5
CONFIG_FILE = "config.json"
# GitHub URL for leaderboard data (raw file URL)
LEADERBOARD_GITHUB_URL = "https://raw.githubusercontent.com/kobel-studios/kobel-autoclicker-competetive/main/clicker_data.json"


class AutoClickerHub:
    def __init__(self, root):
        self.root = root
        self.root.title("kobel-autoclicker")
        self.root.resizable(False, False)
        # Keep the window visible and in front of all other programs.
        self.root.attributes("-topmost", True)

        self.clicking = False
        self.stop_flag = threading.Event()
        self.worker = None
        # Cumulative click count; persists across stop/start and only resets
        # when the program is closed (a fresh process starts at 0).
        self.total_clicks = 0
        # Click rate tracking: stores (timestamp, clicks_per_second) pairs
        self.click_rate_history = deque(maxlen=60)  # Keep last 60 seconds of data
        self.start_time = None
        self.clicks_at_last_second = 0

        self._apply_dark_theme()
        self._load_config()
        self._build_ui()
        self._load_data()
        self._cleanup_old_data()

        keyboard.add_hotkey(HOTKEY, self._hotkey_pressed)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        # Esc only quits when THIS window is focused (not globally), so clicking
        # off the app and pressing Esc elsewhere won't close it.
        self.root.bind("<Escape>", lambda _e: self.on_close())

    # ---------- Theme ----------
    def _apply_dark_theme(self):
        self.root.configure(bg=BG)
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(".", background=BG, foreground=FG, fieldbackground=ENTRY_BG)
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("TLabelframe", background=BG, foreground=FG, bordercolor=BORDER)
        style.configure("TLabelframe.Label", background=BG, foreground=MUTED)
        style.configure(
            "TButton",
            background=ACCENT,
            foreground="#ffffff",
            borderwidth=0,
            focuscolor=ACCENT,
            padding=8,
        )
        style.map(
            "TButton",
            background=[("active", ACCENT_ACTIVE), ("pressed", ACCENT_ACTIVE)],
        )
        style.configure(
            "TEntry",
            fieldbackground=ENTRY_BG,
            foreground=FG,
            insertcolor=FG,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
        )
        style.configure(
            "TCombobox",
            fieldbackground=ENTRY_BG,
            background=ENTRY_BG,
            foreground=FG,
            arrowcolor=FG,
            bordercolor=BORDER,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", ENTRY_BG)],
            foreground=[("readonly", FG)],
        )

        self.root.option_add("*TCombobox*Listbox.background", SURFACE)
        self.root.option_add("*TCombobox*Listbox.foreground", FG)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

    def _load_config(self):
        """Load user configuration or prompt for username on first launch."""
        self.username = None
        self.participate_leaderboard = False

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.username = config.get("username")
                    self.participate_leaderboard = config.get("participate_leaderboard", False)
            except Exception:
                pass

        # If no username or not participating, prompt user
        if not self.username or not self.participate_leaderboard:
            self._prompt_username()

    def _prompt_username(self):
        """Prompt user for leaderboard participation and username."""
        # Ask if they want to participate in leaderboard
        result = messagebox.askyesno(
            "Leaderboard Participation",
            "Do you want to participate in the global leaderboard?\n\n"
            "Your click sessions will be saved with your username and can be shared with others."
        )

        if result:
            # Ask for username
            username = simpledialog.askstring(
                "Username",
                "Enter your username for the leaderboard:",
                parent=self.root
            )
            if username and username.strip():
                self.username = username.strip()
                self.participate_leaderboard = True
                self._save_config()
                messagebox.showinfo("Welcome", f"Welcome, {self.username}! Your sessions will be saved to the leaderboard.")
            else:
                # User cancelled or entered empty username
                self.participate_leaderboard = False
                self._save_config()
        else:
            # User declined participation
            self.participate_leaderboard = False
            self._save_config()

    def _save_config(self):
        """Save user configuration to file."""
        config = {
            "username": self.username,
            "participate_leaderboard": self.participate_leaderboard
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}
        container = ttk.Frame(self.root, padding=16)
        container.grid(row=0, column=0, sticky="nsew")
        # Bind click handler to container for background clicks
        container.bind("<Button-1>", self._on_window_click)

        title = ttk.Label(container, text="kobel-autoclicker", font=("Segoe UI", 16, "bold"))
        title.grid(row=0, column=0, columnspan=4, pady=(0, 12))

        # Interval section with tab-style Hours toggle
        interval_frame = ttk.LabelFrame(container, text="Time between clicks", padding=12)
        interval_frame.grid(row=1, column=0, columnspan=4, sticky="ew", **pad)

        # Top row: Hours tab (left) + all interval fields (right)
        top_row = ttk.Frame(interval_frame)
        top_row.pack(fill="x", pady=(0, 8))

        # Hours tab (toggle)
        self.hours_visible = False
        self.hours_tab = ttk.Button(
            top_row,
            text="Hours",
            width=8,
            command=self._toggle_hours,
        )
        self.hours_tab.pack(side="left", padx=(0, 12))

        # All interval fields in one row (Hours appears inline when toggled)
        self.minutes_var = tk.StringVar(value="0")
        self.seconds_var = tk.StringVar(value="0")
        self.millis_var = tk.StringVar(value="0")
        self.hours_var = tk.StringVar(value="0")

        # Container for interval fields
        fields_frame = ttk.Frame(top_row)
        fields_frame.pack(side="left", fill="x", expand=True)

        # Hours field (hidden by default, appears inline when toggled) - column 0
        self.hours_entry_frame = ttk.Frame(fields_frame)
        self._add_interval_field(self.hours_entry_frame, "Hours", self.hours_var, 0)
        self._add_interval_field(fields_frame, "Minutes", self.minutes_var, 1)
        self._add_interval_field(fields_frame, "Seconds", self.seconds_var, 2)
        self._add_interval_field(fields_frame, "Milliseconds", self.millis_var, 3, millis=True)

        # Mouse button
        options_frame = ttk.LabelFrame(container, text="Click options", padding=12)
        options_frame.grid(row=2, column=0, columnspan=4, sticky="ew", **pad)

        ttk.Label(options_frame, text="Mouse button").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.button_var = tk.StringVar(value="left")
        ttk.Combobox(
            options_frame,
            textvariable=self.button_var,
            values=["left", "right", "middle"],
            state="readonly",
            width=8,
        ).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        # Click Tester button
        self.click_tester_button = ttk.Button(options_frame, text="Click Tester", command=self._show_click_tester, width=10)
        self.click_tester_button.grid(row=0, column=2, padx=6, pady=4)

        # Status
        self.status_var = tk.StringVar(value="Idle")
        self.status_label = ttk.Label(
            container, textvariable=self.status_var, font=("Segoe UI", 11, "bold"), foreground=MUTED
        )
        self.status_label.grid(row=3, column=0, columnspan=4, pady=(10, 2))

        # Row 4: Graph button (left) + Clicks performed (centered) + Leaderboard buttons (right)
        row4_frame = ttk.Frame(container)
        row4_frame.grid(row=4, column=0, columnspan=4, pady=(0, 8), sticky="ew")

        self.graph_button = ttk.Button(row4_frame, text="Graph", command=self._show_graph, width=8)
        self.graph_button.pack(side="left", padx=(0, 12))

        self.count_var = tk.StringVar(value="Clicks performed: 0")
        ttk.Label(row4_frame, textvariable=self.count_var, foreground=MUTED).pack(side="left", expand=True)

        leaderboard_buttons_frame = ttk.Frame(row4_frame)
        leaderboard_buttons_frame.pack(side="right", padx=(12, 0))

        self.leaderboard_button = ttk.Button(leaderboard_buttons_frame, text="Leaderboard", command=self._show_leaderboard, width=11)
        self.leaderboard_button.pack(side="left", padx=(0, 4))

        self.update_leaderboard_button = ttk.Button(leaderboard_buttons_frame, text="Update", command=self._update_leaderboard_from_github, width=7)
        self.update_leaderboard_button.pack(side="left")

        # Controls
        self.toggle_button = ttk.Button(container, text="Start (F6)", command=self._toggle)
        self.toggle_button.grid(row=5, column=0, columnspan=4, sticky="ew", padx=6, pady=(6, 2))

        hint = ttk.Label(
            container,
            text="Press F6 anywhere to start/stop. Press Esc here (or close the window) to quit.\n"
                 "Fail-safe: slam mouse to a screen corner to abort.",
            foreground=MUTED,
            justify="center",
        )
        hint.grid(row=6, column=0, columnspan=4, pady=(8, 0))

    def _add_interval_field(self, parent, label, var, column, millis=False):
        ttk.Label(parent, text=label).grid(row=0, column=column, padx=4, pady=(0, 2))
        entry = ttk.Entry(parent, textvariable=var, width=6, justify="center")
        entry.grid(row=1, column=column, padx=4, pady=(0, 2))
        # Clear the field on focus so typing starts fresh (no appending to existing "0").
        entry.bind("<FocusIn>", lambda _e, v=var: self._clear_on_focus(v))
        if millis:
            entry.bind("<FocusOut>", lambda _e, v=var: self._validate_millis(v))
            # Store reference to the millis entry for window click detection
            self.millis_entry = entry
        else:
            entry.bind("<FocusOut>", lambda _e, v=var: self._validate_interval(v))
        # Store references to all interval entries for window click detection
        if not hasattr(self, 'interval_entries'):
            self.interval_entries = []
        self.interval_entries.append(entry)

    def _toggle_hours(self):
        self.hours_visible = not self.hours_visible
        if self.hours_visible:
            self.hours_entry_frame.grid(row=0, column=0, rowspan=2, padx=4)
            self.hours_tab.config(text="Remove Hours")
        else:
            self.hours_entry_frame.grid_forget()
            self.hours_tab.config(text="Hours")

    def _on_window_click(self, event):
        """Validate interval fields when clicking on window background."""
        # Check if click was on an interval entry
        if hasattr(self, 'interval_entries'):
            clicked_widget = event.widget
            # Walk up the widget hierarchy to see if it's an interval entry
            current = clicked_widget
            while current:
                if current in self.interval_entries:
                    return  # Clicked on an interval entry, don't validate
                try:
                    current = current.master
                except AttributeError:
                    break
            # If we get here, click was not on an interval entry - validate all
            self._validate_interval(self.minutes_var)
            self._validate_interval(self.seconds_var)
            self._validate_interval(self.hours_var)
            self._validate_millis(self.millis_var)

    def _validate_interval(self, var):
        """Validate interval field (seconds, minutes, hours) and reset to 0 if invalid."""
        text = var.get().strip()
        if text == "":
            var.set("0")
            return
        try:
            value = float(text)
        except ValueError:
            var.set("0")
            return
        # Reject negative and non-whole numbers
        if value < 0:
            var.set("0")
        elif value != int(value):
            var.set("0")

    def _validate_millis(self, var):
        """Validate milliseconds field and reset to 0 if invalid."""
        text = var.get().strip()
        if text == "":
            var.set("0")
            return
        if text.lower() == SECRET_WORD:
            return  # secret mode: keep the word in the field
        try:
            value = float(text)
        except ValueError:
            var.set("0")
            return
        # Reject sub-1ms and non-whole numbers in normal mode
        if value < 0:
            var.set("0")
        elif value < MIN_MILLIS:
            var.set("0")
        elif value != int(value):
            var.set("0")

    def _clear_on_focus(self, var):
        var.set("")

    def _fill_zero_if_empty(self, var):
        if var.get().strip() == "":
            var.set("0")

    # ---------- Input parsing ----------
    def _is_secret_millis(self):
        return self.millis_var.get().strip().lower() == SECRET_WORD

    def _get_interval_seconds(self):
        # Check which tab is active by seeing if hours has a non-zero value.
        hours = self._parse_number(self.hours_var.get(), "Hours")
        if hours > 0:
            # Hours tab in use: ignore minutes/seconds/millis.
            if hours < 0:
                raise ValueError("Hours cannot be negative.")
            if hours == 0:
                raise ValueError("The interval must be greater than 0.")
            return hours * 3600  # hours to seconds

        # Min/Sec/Millis tab in use.
        minutes = self._parse_number(self.minutes_var.get(), "Minutes")
        seconds = self._parse_number(self.seconds_var.get(), "Seconds")
        if self._is_secret_millis():
            # Code word: no added delay -> click as fast as the system allows.
            return minutes * 60 + seconds
        millis = self._parse_millis(self.millis_var.get())
        total = minutes * 60 + seconds + millis / 1000.0
        if total <= 0:
            raise ValueError("The interval must be greater than 0.")
        return total

    def _parse_millis(self, raw):
        value = self._parse_number(raw, "Milliseconds")
        if value < 0:
            raise ValueError("Milliseconds cannot be negative.")
        if value == 0:
            return 0.0
        if value < MIN_MILLIS:
            raise ValueError("Milliseconds must be at least 1 in normal mode. Type 'kobel' for max speed.")
        # Require whole numbers only in normal mode (no decimals/fractions).
        if value != int(value):
            raise ValueError("Milliseconds must be a whole number in normal mode. Type 'kobel' for max speed.")
        return value

    @staticmethod
    def _parse_number(raw, field_name):
        raw = (raw or "").strip()
        if raw == "":
            return 0
        try:
            value = float(raw)
        except ValueError:
            raise ValueError(f"'{field_name}' must be a number.")
        if value < 0:
            raise ValueError(f"'{field_name}' cannot be negative.")
        return value

    # ---------- Click control ----------
    def _hotkey_pressed(self):
        # keyboard callbacks run on a different thread; marshal to the GUI thread.
        self.root.after(0, self._toggle)

    def _toggle(self):
        if self.clicking:
            self.stop_clicking()
        else:
            self.start_clicking()

    def start_clicking(self):
        # Snap fields to their enforced values so the display matches what runs
        # (e.g. a sub-1 ms entry becomes 1) even when started via the F6 hotkey.
        self._validate_interval(self.minutes_var)
        self._validate_interval(self.seconds_var)
        self._validate_interval(self.hours_var)
        self._validate_millis(self.millis_var)
        try:
            interval = self._get_interval_seconds()
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        button = self.button_var.get()
        self.clicking = True
        self.stop_flag.clear()
        self.start_time = time.time()
        self.clicks_at_last_second = self.total_clicks
        self.click_rate_history.clear()
        self.worker = threading.Thread(
            target=self._click_loop, args=(interval, button), daemon=True
        )
        self.worker.start()

        self.toggle_button.config(text="Stop (F6)")
        self._set_status("Clicking...", CLICKING_COLOR)

    def stop_clicking(self):
        self.stop_flag.set()
        self.clicking = False
        self.toggle_button.config(text="Start (F6)")
        self._set_status("Stopped", STOPPED_COLOR)
        # Save the session data when stopping
        if self.click_rate_history:
            self._save_session()

    def _click_loop(self, interval, button):
        count = self.total_clicks
        last_ui = 0.0
        last_rate_update = time.time()
        # Minimum sleep to keep UI responsive in kobel mode (0.001ms = 1 microsecond)
        min_sleep = 0.000001
        try:
            while not self.stop_flag.is_set():
                pyautogui.click(button=button)
                count += 1
                self.total_clicks = count

                # Throttle UI updates so very fast clicking can't flood the GUI
                # event queue (which could otherwise freeze the window).
                now = time.perf_counter()
                if now - last_ui >= 0.05:
                    last_ui = now
                    self.root.after(0, self._update_count, count)

                # Track click rate every second
                current_time = time.time()
                if current_time - last_rate_update >= 1.0:
                    clicks_this_second = count - self.clicks_at_last_second
                    rate = clicks_this_second / (current_time - last_rate_update)
                    self.click_rate_history.append((current_time - self.start_time, rate))
                    self.clicks_at_last_second = count
                    last_rate_update = current_time

                # Sleep in small slices so a stop request is responsive.
                # In kobel mode (interval=0), use minimum sleep to keep UI responsive.
                effective_interval = max(interval, min_sleep)
                slept = 0.0
                while slept < effective_interval and not self.stop_flag.is_set():
                    step = min(0.02, effective_interval - slept)
                    time.sleep(step)
                    slept += step
        except Exception:
            pass  # e.g. PyAutoGUI fail-safe; fall through to reset the UI
        finally:
            self.root.after(0, self._on_loop_done)

    def _on_loop_done(self):
        self.clicking = False
        self.toggle_button.config(text="Start (F6)")
        self.count_var.set(f"Clicks performed: {self.total_clicks}")
        self._set_status("Stopped", STOPPED_COLOR)

    # ---------- Status helpers ----------
    def _set_status(self, text, color):
        self.status_var.set(text)
        self.status_label.config(foreground=color)

    def _update_count(self, performed):
        self.count_var.set(f"Clicks performed: {performed}")

    def _show_graph(self):
        if not self.click_rate_history:
            messagebox.showinfo("No data", "Start clicking to generate graph data.")
            return

        graph_window = tk.Toplevel(self.root)
        graph_window.title("Click Rate Graph")
        graph_window.geometry("600x450")
        graph_window.configure(bg=BG)

        # Graph type selector
        control_frame = ttk.Frame(graph_window)
        control_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(control_frame, text="Graph type:").pack(side="left", padx=(0, 8))
        graph_type_var = tk.StringVar(value="line")
        ttk.Radiobutton(control_frame, text="Line chart", variable=graph_type_var, value="line").pack(side="left", padx=8)
        ttk.Radiobutton(control_frame, text="Bar chart", variable=graph_type_var, value="bar").pack(side="left", padx=8)

        # Refresh button
        ttk.Button(control_frame, text="Refresh", command=lambda: self._update_graph(graph_window, graph_type_var)).pack(side="right", padx=8)

        # Matplotlib figure
        fig, ax = plt.subplots(figsize=(6, 3.5), facecolor=BG)
        self._update_graph_content(ax, graph_type_var.get())

        canvas = FigureCanvasTkAgg(fig, master=graph_window)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Store canvas reference for refresh
        graph_window.canvas = canvas
        graph_window.ax = ax
        graph_window.fig = fig

    def _update_graph(self, window, graph_type_var):
        ax = window.ax
        fig = window.fig
        ax.clear()
        self._update_graph_content(ax, graph_type_var.get())
        window.canvas.draw()

    def _update_graph_content(self, ax, graph_type):
        times = [t for t, _ in self.click_rate_history]
        rates = [r for _, r in self.click_rate_history]

        if not times:
            ax.text(0.5, 0.5, "No data", ha="center", va="center", color=FG)
            return

        # Calculate target rate based on current interval setting
        try:
            interval = self._get_interval_seconds()
            target_rate = 1.0 / interval if interval > 0 else 0
        except ValueError:
            target_rate = 0

        if graph_type == "line":
            ax.plot(times, rates, color=ACCENT, linewidth=2, label="Actual")
            ax.fill_between(times, rates, alpha=0.3, color=ACCENT)
            # Add target rate line
            if target_rate > 0:
                ax.axhline(y=target_rate, color=STOPPED_COLOR, linestyle='--', linewidth=2, label="Target")
        else:  # bar chart
            ax.bar(times, rates, color=ACCENT, alpha=0.7, width=0.8, label="Actual")
            # Add target rate line
            if target_rate > 0:
                ax.axhline(y=target_rate, color=STOPPED_COLOR, linestyle='--', linewidth=2, label="Target")

        ax.set_facecolor(SURFACE)
        ax.set_xlabel("Time (seconds)", color=FG)
        ax.set_ylabel("Clicks per second", color=FG)
        ax.set_title("Click Rate Over Time", color=FG, fontsize=12, fontweight="bold")
        ax.tick_params(axis="x", colors=FG)
        ax.tick_params(axis="y", colors=FG)
        ax.spines["bottom"].set_color(BORDER)
        ax.spines["top"].set_color(BORDER)
        ax.spines["left"].set_color(BORDER)
        ax.spines["right"].set_color(BORDER)
        ax.grid(True, alpha=0.2, color=MUTED)
        ax.legend(facecolor=SURFACE, edgecolor=BORDER, labelcolor=FG)

    # ---------- Data persistence ----------
    def _load_data(self):
        """Load saved session data from JSON file."""
        if not os.path.exists(DATA_FILE):
            return
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Data is loaded but not used in current session - only for leaderboard
            self.saved_sessions = data.get("sessions", [])
        except Exception:
            self.saved_sessions = []

    def _cleanup_old_data(self):
        """Remove sessions older than MAX_DATA_AGE_WEEKS."""
        if not os.path.exists(DATA_FILE):
            return
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            sessions = data.get("sessions", [])
            cutoff = datetime.now() - timedelta(weeks=MAX_DATA_AGE_WEEKS)
            filtered = [
                s for s in sessions
                if datetime.fromisoformat(s["timestamp"]) > cutoff
            ]
            if len(filtered) != len(sessions):
                data["sessions"] = filtered
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
        except Exception:
            pass

    def _save_session(self):
        """Save current session data to JSON file."""
        try:
            # Only save if user participates in leaderboard
            if not self.participate_leaderboard:
                return

            # Load existing data
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"sessions": []}

            # Calculate session stats
            if not self.click_rate_history:
                return
            times = [t for t, _ in self.click_rate_history]
            rates = [r for _, r in self.click_rate_history]
            avg_rate = sum(rates) / len(rates) if rates else 0
            max_rate = max(rates) if rates else 0
            total_clicks = self.total_clicks
            duration = times[-1] - times[0] if times else 0

            session = {
                "timestamp": datetime.now().isoformat(),
                "username": self.username,
                "total_clicks": total_clicks,
                "duration_seconds": round(duration, 2),
                "avg_clicks_per_sec": round(avg_rate, 2),
                "max_clicks_per_sec": round(max_rate, 2),
                "rate_history": list(self.click_rate_history),
            }

            data["sessions"].append(session)
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _show_leaderboard(self):
        """Show a leaderboard of saved sessions."""
        if not os.path.exists(DATA_FILE):
            messagebox.showinfo("No data", "No saved sessions found.")
            return

        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            sessions = data.get("sessions", [])

            if not sessions:
                messagebox.showinfo("No data", "No saved sessions found.")
                return

            # Sort by max clicks per second (descending)
            sorted_sessions = sorted(
                sessions, key=lambda s: s.get("max_clicks_per_sec", 0), reverse=True
            )

            leaderboard_window = tk.Toplevel(self.root)
            leaderboard_window.title("Leaderboard")
            leaderboard_window.geometry("500x400")
            leaderboard_window.configure(bg=BG)

            # Header
            ttk.Label(
                leaderboard_window,
                text="Click Rate Leaderboard",
                font=("Segoe UI", 14, "bold"),
                foreground=FG,
                background=BG,
            ).pack(pady=10)

            # Treeview for leaderboard
            tree_frame = ttk.Frame(leaderboard_window)
            tree_frame.pack(fill="both", expand=True, padx=10, pady=5)

            columns = ("rank", "username", "date", "max_rate", "avg_rate", "total_clicks")
            tree = ttk.Treeview(tree_frame, columns=columns, show="headings")
            tree.heading("rank", text="#")
            tree.heading("username", text="Username")
            tree.heading("date", text="Date")
            tree.heading("max_rate", text="Max Rate")
            tree.heading("avg_rate", text="Avg Rate")
            tree.heading("total_clicks", text="Total Clicks")

            tree.column("rank", width=40, anchor="center")
            tree.column("username", width=100)
            tree.column("date", width=120)
            tree.column("max_rate", width=80, anchor="center")
            tree.column("avg_rate", width=80, anchor="center")
            tree.column("total_clicks", width=100, anchor="center")

            tree.pack(side="left", fill="both", expand=True)

            scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
            scrollbar.pack(side="right", fill="y")
            tree.configure(yscrollcommand=scrollbar.set)

            # Populate leaderboard
            for i, session in enumerate(sorted_sessions[:20], 1):  # Top 20
                date_str = datetime.fromisoformat(session["timestamp"]).strftime("%Y-%m-%d %H:%M")
                username = session.get("username", "Unknown")
                tree.insert(
                    "",
                    "end",
                    values=(
                        i,
                        username,
                        date_str,
                        f"{session['max_clicks_per_sec']:.1f}",
                        f"{session['avg_clicks_per_sec']:.1f}",
                        session["total_clicks"],
                    ),
                )

            # Close button
            ttk.Button(
                leaderboard_window,
                text="Close",
                command=leaderboard_window.destroy,
            ).pack(pady=10)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to load leaderboard: {e}")

    def _update_leaderboard_from_github(self):
        """Download and merge leaderboard data from GitHub."""
        try:
            # Fetch data from GitHub
            response = urllib.request.urlopen(LEADERBOARD_GITHUB_URL)
            remote_data = json.loads(response.read().decode('utf-8'))
            remote_sessions = remote_data.get("sessions", [])

            # Load local data
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    local_data = json.load(f)
            else:
                local_data = {"sessions": []}
            local_sessions = local_data.get("sessions", [])

            # Count new sessions
            local_timestamps = {s["timestamp"] for s in local_sessions}
            new_sessions = [s for s in remote_sessions if s["timestamp"] not in local_timestamps]

            if not new_sessions:
                messagebox.showinfo("Up to date", "Your leaderboard is already up to date.")
                return

            # Show confirmation dialog
            result = messagebox.askyesno(
                "Update Leaderboard",
                f"Found {len(new_sessions)} new session(s) from GitHub.\n\n"
                f"Do you want to download and merge them with your local data?"
            )

            if result:
                # Merge sessions (avoid duplicates by timestamp)
                merged_sessions = local_sessions + new_sessions
                # Sort by timestamp (newest first)
                merged_sessions.sort(key=lambda s: s["timestamp"], reverse=True)

                # Save merged data
                local_data["sessions"] = merged_sessions
                with open(DATA_FILE, "w", encoding="utf-8") as f:
                    json.dump(local_data, f, indent=2)

                # Reload data
                self._load_data()

                messagebox.showinfo("Success", f"Successfully merged {len(new_sessions)} new session(s).")

        except urllib.error.URLError as e:
            messagebox.showerror("Error", f"Failed to connect to GitHub: {e}\n\nCheck your internet connection and the GitHub URL.")
        except json.JSONDecodeError:
            messagebox.showerror("Error", "Failed to parse data from GitHub. The file may be corrupted.")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")

    def _show_click_tester(self):
        """Show a click tester popup for manual clicking speed testing."""
        tester_window = tk.Toplevel(self.root)
        tester_window.title("Click Tester")
        tester_window.geometry("400x300")
        tester_window.configure(bg=BG)
        tester_window.attributes("-topmost", True)

        # Header
        ttk.Label(
            tester_window,
            text="Manual Click Speed Tester",
            font=("Segoe UI", 14, "bold"),
            foreground=FG,
            background=BG,
        ).pack(pady=15)

        # Click area button
        click_area = ttk.Button(
            tester_window,
            text="CLICK HERE",
            font=("Segoe UI", 16, "bold"),
            command=lambda: self._register_test_click(tester_window),
        )
        click_area.pack(pady=20, ipadx=20, ipady=10)

        # Stats display
        stats_frame = ttk.Frame(tester_window)
        stats_frame.pack(fill="x", padx=20, pady=10)

        self.test_clicks_var = tk.StringVar(value="Clicks: 0")
        ttk.Label(stats_frame, textvariable=self.test_clicks_var, font=("Segoe UI", 12), foreground=FG, background=BG).pack()

        self.test_cps_var = tk.StringVar(value="Speed: 0 clicks/sec")
        ttk.Label(stats_frame, textvariable=self.test_cps_var, font=("Segoe UI", 12), foreground=ACCENT, background=BG).pack()

        # Visual speed bar
        ttk.Label(tester_window, text="Speed Meter", foreground=MUTED, background=BG).pack(pady=(10, 5))
        self.test_speed_bar = ttk.Progressbar(tester_window, orient="horizontal", length=300, mode="determinate")
        self.test_speed_bar.pack(pady=5)

        # Reset button
        ttk.Button(
            tester_window,
            text="Reset",
            command=lambda: self._reset_click_tester(tester_window),
        ).pack(pady=10)

        # Initialize test data
        tester_window.test_clicks = 0
        tester_window.test_start_time = None
        tester_window.test_click_times = []

    def _register_test_click(self, window):
        """Register a click in the tester and update stats."""
        import time
        current_time = time.time()
        window.test_clicks += 1
        window.test_click_times.append(current_time)

        # Remove clicks older than 1 second for current speed calculation
        window.test_click_times = [t for t in window.test_click_times if current_time - t <= 1.0]

        # Update stats
        self.test_clicks_var.set(f"Clicks: {window.test_clicks}")
        current_cps = len(window.test_click_times)
        self.test_cps_var.set(f"Speed: {current_cps} clicks/sec")

        # Update speed bar (scale: 0-20 clicks/sec for full bar)
        max_cps = 20
        progress = min(current_cps / max_cps, 1.0) * 100
        self.test_speed_bar['value'] = progress

    def _reset_click_tester(self, window):
        """Reset the click tester stats."""
        window.test_clicks = 0
        window.test_click_times = []
        self.test_clicks_var.set("Clicks: 0")
        self.test_cps_var.set("Speed: 0 clicks/sec")
        self.test_speed_bar['value'] = 0

    # ---------- Lifecycle ----------
    def on_close(self):
        self.stop_flag.set()
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        self.root.destroy()


def main():
    root = tk.Tk()
    AutoClickerHub(root)
    root.mainloop()


if __name__ == "__main__":
    main()
