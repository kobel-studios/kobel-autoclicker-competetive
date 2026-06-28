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
import urllib.parse
import webbrowser
import base64

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
# GitHub URL for leaderboard data (using API to bypass caching)
LEADERBOARD_GITHUB_URL = "https://api.github.com/repos/kobel-studios/kobel-autoclicker-competetive/contents/clicker_data.json"
# TEST MODE: Use local file for testing
# LEADERBOARD_GITHUB_URL = "file:///C:/Users/jacks/CascadeProjects/autoclicker-hub/clicker_data_test.json"
# GitHub Issues URL for submitting leaderboard data
GITHUB_ISSUES_URL = "https://github.com/kobel-studios/kobel-autoclicker-competetive/issues/new"


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
        # Track if click tester window is open (to avoid counting autoclicker clicks)
        self.click_tester_open = False
        # Track if user is actively clicking on the click tester circle
        self.user_clicking_on_tester = False

        self._apply_dark_theme()
        self._load_config()
        self._build_ui()
        self._load_data()
        self._cleanup_old_data()
        self._check_for_leaderboard_updates()  # Check for updates on launch

        keyboard.add_hotkey(HOTKEY, self._hotkey_pressed)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        # Bind click handler to entire window to remove focus from text boxes
        self.root.bind("<Button-1>", self._on_background_click)

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
        self.github_token = None

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config = json.load(f)
                    self.username = config.get("username")
                    self.participate_leaderboard = config.get("participate_leaderboard", False)
                    self.github_token = config.get("github_token")
            except Exception:
                pass

        # If no username or not participating, prompt user
        if not self.username or not self.participate_leaderboard:
            self._prompt_username()

    def _ask_github_token(self):
        """Ask user for GitHub token with clickable link."""
        import webbrowser
        
        dialog = tk.Toplevel(self.root)
        dialog.title("GitHub Token")
        dialog.geometry("500x400")
        dialog.configure(bg=BG)
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Instructions
        instructions = tk.Label(
            dialog,
            text="WHAT THIS DOES:\n"
                   "This lets the app add your score to the leaderboard automatically.\n"
                   "It does NOT give us access to your GitHub account or repos.\n"
                   "You create the token yourself, so you control it.\n\n"
                   "STEP 1: Click the link below\n"
                   "STEP 2: Click 'Generate new token' (or 'Generate new token (classic)')\n"
                   "STEP 3: Type a name (like 'autoclicker')\n"
                   "STEP 4: Check the box that says 'repo'\n"
                   "STEP 5: Click the green button\n"
                   "STEP 6: Copy the code it shows you\n"
                   "STEP 7: Paste it in the box below",
            fg=FG,
            bg=BG,
            font=("Segoe UI", 10),
            justify="left"
        )
        instructions.pack(pady=20, padx=20)
        
        # Clickable link
        def open_link():
            webbrowser.open("https://github.com/settings/tokens")
        
        link_label = tk.Label(
            dialog,
            text="https://github.com/settings/tokens",
            fg=ACCENT,
            bg=BG,
            font=("Segoe UI", 10, "underline"),
            cursor="hand2"
        )
        link_label.pack(pady=5)
        link_label.bind("<Button-1>", lambda e: open_link())
        
        # Safety note
        safety_note = tk.Label(
            dialog,
            text="This is NOT your GitHub password. It's a special code you create.\n"
                   "You can delete it anytime from GitHub settings.\n\n"
                   "(Leave empty to use manual submission instead)",
            fg=MUTED,
            bg=BG,
            font=("Segoe UI", 9),
            justify="left"
        )
        safety_note.pack(pady=10, padx=20)
        
        # Token input
        token_var = tk.StringVar()
        token_entry = tk.Entry(
            dialog,
            textvariable=token_var,
            show="*",
            font=("Segoe UI", 10),
            bg=SURFACE,
            fg=FG,
            insertbackground=FG
        )
        token_entry.pack(pady=10, padx=20, fill="x")
        token_entry.focus()
        
        # Buttons
        button_frame = tk.Frame(dialog, bg=BG)
        button_frame.pack(pady=20)
        
        result = [None]
        
        def on_ok():
            result[0] = token_var.get()
            dialog.destroy()
        
        def on_cancel():
            result[0] = ""
            dialog.destroy()
        
        ok_button = tk.Button(
            button_frame,
            text="OK",
            command=on_ok,
            bg=ACCENT,
            fg="white",
            font=("Segoe UI", 10),
            relief="flat",
            padx=20
        )
        ok_button.pack(side="left", padx=5)
        
        cancel_button = tk.Button(
            button_frame,
            text="Cancel",
            command=on_cancel,
            bg=SURFACE,
            fg=FG,
            font=("Segoe UI", 10),
            relief="flat",
            padx=20
        )
        cancel_button.pack(side="left", padx=5)
        
        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # Wait for dialog to close
        self.root.wait_window(dialog)
        
        return result[0]

    def _prompt_username(self):
        """Prompt user for leaderboard participation and username."""
        # Ask if they want to participate in leaderboard
        result = messagebox.askyesno(
            "Leaderboard Participation",
            "Do you want to participate in the global leaderboard?\n\n"
            "Your click sessions will be saved with your username and can be shared with others."
        )

        if result:
            # Ask for username (loop until unique or cancelled)
            while True:
                username = simpledialog.askstring(
                    "Username",
                    "Enter your username for the leaderboard:",
                    parent=self.root
                )
                
                if not username or not username.strip():
                    # User cancelled or entered empty username
                    self.participate_leaderboard = False
                    self._save_config()
                    return
                
                username = username.strip()
                
                # Check if username already exists in leaderboard
                if self._username_exists(username):
                    messagebox.showerror(
                        "Username Taken",
                        f"The username '{username}' is already taken. Please choose a different username."
                    )
                    continue
                
                # Username is unique
                self.username = username
                self.participate_leaderboard = True
                # Ask for GitHub token for automatic submission
                token = self._ask_github_token()
                self.github_token = token.strip() if token else None
                self._save_config()
                if self.github_token:
                    messagebox.showinfo("Welcome", f"Welcome, {self.username}! Your sessions will be automatically submitted to the leaderboard.")
                else:
                    messagebox.showinfo("Welcome", f"Welcome, {self.username}! Your sessions will be saved to the leaderboard (manual submission via GitHub Issues).")
                break
        else:
            # User declined participation
            self.participate_leaderboard = False
            self._save_config()

    def _username_exists(self, username):
        """Check if username already exists in the leaderboard."""
        try:
            # Fetch current data from GitHub
            response = urllib.request.urlopen(LEADERBOARD_GITHUB_URL)
            api_response = json.loads(response.read().decode('utf-8'))
            
            # GitHub API returns base64-encoded content
            if "content" in api_response:
                import base64
                content = base64.b64decode(api_response["content"]).decode('utf-8')
                data = json.loads(content)
            else:
                data = {"sessions": []}
            
            sessions = data.get("sessions", [])
            
            # Check if any session has this username
            for session in sessions:
                if session.get("username") == username:
                    return True
            
            return False
        except urllib.error.URLError:
            # Can't connect to GitHub - warn user but allow
            messagebox.showwarning(
                "Connection Error",
                "Cannot check if username is taken (no internet connection).\n"
                "You can continue, but your username might already be taken."
            )
            return False
        except Exception as e:
            # Other error - warn user but allow
            messagebox.showwarning(
                "Error",
                f"Cannot check if username is taken: {e}\n"
                "You can continue, but your username might already be taken."
            )
            return False

    def _save_config(self):
        """Save user configuration to file."""
        config = {
            "username": self.username,
            "participate_leaderboard": self.participate_leaderboard,
            "github_token": self.github_token
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 6}
        container = ttk.Frame(self.root, padding=16)
        container.grid(row=0, column=0, sticky="nsew")

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

    def _on_background_click(self, event):
        """Remove focus from text boxes when clicking on window background."""
        # Check if click was on an interactive widget (text box, button, etc.)
        clicked_widget = event.widget
        
        # Don't remove focus if clicking on an entry (text box)
        if isinstance(clicked_widget, ttk.Entry):
            return
        
        # Walk up the widget hierarchy to check if it's inside an interactive element
        current = clicked_widget
        while current:
            if isinstance(current, ttk.Entry):
                return  # Clicked on or inside a text box, don't remove focus
            if isinstance(current, (ttk.Button, ttk.Combobox, ttk.Checkbutton, ttk.Radiobutton)):
                return  # Clicked on interactive widget, don't remove focus
            try:
                current = current.master
            except AttributeError:
                break
        
        # If we get here, click was on background - remove focus
        self.root.focus_set()


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
        # Ask if user wants to save to leaderboard before saving
        if self.participate_leaderboard and self.total_clicks > 0:
            self._prompt_submit_leaderboard()

    def _click_loop(self, interval, button):
        count = self.total_clicks
        last_ui = 0.0
        last_rate_update = time.time()
        # Minimum sleep to keep UI responsive in kobel mode (0.001ms = 1 microsecond)
        min_sleep = 0.000001
        try:
            while not self.stop_flag.is_set():
                pyautogui.click(button=button)
                # Don't count clicks if user is actively clicking on tester circle
                if not self.user_clicking_on_tester:
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
        graph_window.attributes("-topmost", True)  # Keep window on top

        # Graph type selector
        control_frame = ttk.Frame(graph_window)
        control_frame.pack(fill="x", padx=10, pady=10)

        ttk.Label(control_frame, text="Graph type:").pack(side="left", padx=(0, 8))
        graph_type_var = tk.StringVar(value="line")
        ttk.Radiobutton(control_frame, text="Line chart", variable=graph_type_var, value="line", command=lambda: self._update_graph(graph_window, graph_type_var)).pack(side="left", padx=8)
        ttk.Radiobutton(control_frame, text="Bar chart", variable=graph_type_var, value="bar", command=lambda: self._update_graph(graph_window, graph_type_var)).pack(side="left", padx=8)

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
        # Check for updates before showing leaderboard
        self._check_for_leaderboard_updates()
        
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
            leaderboard_window.attributes("-topmost", True)  # Keep window on top

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

            # Configure Treeview style for dark theme
            style = ttk.Style()
            style.configure("Treeview", 
                          background=BG, 
                          foreground=FG, 
                          fieldbackground=BG,
                          font=("Segoe UI", 10))
            style.configure("Treeview.Heading", 
                          background=SURFACE, 
                          foreground=FG, 
                          font=("Segoe UI", 10, "bold"))
            style.map("Treeview", 
                     background=[('selected', ACCENT)],
                     foreground=[('selected', 'white')])

            columns = ("rank", "username", "date", "max_rate", "avg_rate", "total_clicks")
            tree = ttk.Treeview(tree_frame, columns=columns, show="headings", style="Treeview")
            tree.heading("rank", text="#")
            tree.heading("username", text="Username")
            tree.heading("date", text="Date")
            tree.heading("max_rate", text="Max Rate")
            tree.heading("avg_rate", text="Avg Rate")
            tree.heading("total_clicks", text="Total Clicks")

            tree.column("rank", width=30, anchor="center")
            tree.column("username", width=80)
            tree.column("date", width=90)
            tree.column("max_rate", width=60, anchor="center")
            tree.column("avg_rate", width=60, anchor="center")
            tree.column("total_clicks", width=70, anchor="center")

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

    def _check_for_leaderboard_updates(self):
        """Check for leaderboard updates and prompt user if available."""
        try:
            # Fetch data from GitHub
            response = urllib.request.urlopen(LEADERBOARD_GITHUB_URL)
            api_response = json.loads(response.read().decode('utf-8'))
            
            # GitHub API returns base64-encoded content
            if "content" in api_response:
                import base64
                content = base64.b64decode(api_response["content"]).decode('utf-8')
                remote_data = json.loads(content)
            else:
                remote_data = {"sessions": []}
            
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

            if new_sessions:
                # If first-time user (no local data), auto-download without prompting
                if not local_sessions:
                    local_data["sessions"] = remote_sessions
                    with open(DATA_FILE, "w", encoding="utf-8") as f:
                        json.dump(local_data, f, indent=2)
                    self._load_data()
                else:
                    # Prompt existing user to update
                    result = messagebox.askyesno(
                        "Leaderboard Update Available",
                        f"Found {len(new_sessions)} new session(s) on the global leaderboard.\n\n"
                        f"Do you want to download and merge them now?"
                    )
                    if result:
                        self._update_leaderboard_from_github()
        except urllib.error.URLError:
            # Network error - silently skip on launch
            pass
        except Exception:
            # Other errors - silently skip on launch
            pass

    def _update_leaderboard_from_github(self):
        """Download and merge leaderboard data from GitHub."""
        try:
            # Fetch data from GitHub
            response = urllib.request.urlopen(LEADERBOARD_GITHUB_URL)
            api_response = json.loads(response.read().decode('utf-8'))
            
            # GitHub API returns base64-encoded content
            if "content" in api_response:
                import base64
                content = base64.b64decode(api_response["content"]).decode('utf-8')
                remote_data = json.loads(content)
            else:
                remote_data = {"sessions": []}
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

    def _prompt_submit_leaderboard(self):
        """Prompt user to submit their session data to GitHub."""
        if self.github_token:
            # Automatic submission via GitHub API
            result = messagebox.askyesno(
                "Submit to Leaderboard",
                "Do you want to submit your click session to the global leaderboard?\n\n"
                "The leaderboard is updated monthly. Click 'Update' in the app to download the latest leaderboard data.\n\n"
                "This will automatically submit your data via GitHub API."
            )
            if result:
                # Save the session locally first
                self._save_session()
                # Then submit via GitHub API
                self._submit_to_github_api()
        else:
            # Manual submission via GitHub Issues
            result = messagebox.askyesno(
                "Submit to Leaderboard",
                "Do you want to submit your click session to the global leaderboard?\n\n"
                "The leaderboard is updated monthly. Click 'Update' in the app to download the latest leaderboard data.\n\n"
                "This will open a GitHub Issue where you can create your data."
            )
            if result:
                # Save the session locally first
                self._save_session()
                # Then open GitHub Issues
                self._submit_to_github()

    def _submit_to_github_api(self):
        """Submit session data to GitHub via API."""
        try:
            # Load the latest session data
            if not os.path.exists(DATA_FILE):
                messagebox.showerror("Error", "No session data found to submit.")
                return

            with open(DATA_FILE, "r", encoding="utf-8") as f:
                local_data = json.load(f)
            local_sessions = local_data.get("sessions", [])
            
            if not local_sessions:
                messagebox.showerror("Error", "No session data found to submit.")
                return

            # Get the most recent session
            latest_session = local_sessions[-1]

            # Fetch current data from GitHub
            request = urllib.request.Request(
                LEADERBOARD_GITHUB_URL,
                headers={"Authorization": f"token {self.github_token}"}
            )
            response = urllib.request.urlopen(request)
            api_response = json.loads(response.read().decode('utf-8'))
            
            # GitHub API returns base64-encoded content
            if "content" in api_response:
                import base64
                content = base64.b64decode(api_response["content"]).decode('utf-8')
                remote_data = json.loads(content)
            else:
                remote_data = {"sessions": []}
            
            remote_sessions = remote_data.get("sessions", [])

            # Check if session already exists (by timestamp)
            if any(s.get("timestamp") == latest_session.get("timestamp") for s in remote_sessions):
                messagebox.showinfo("Info", "This session is already on the leaderboard.")
                return

            # Add new session
            remote_sessions.append(latest_session)
            remote_data["sessions"] = remote_sessions

            # Get the SHA of the current file (needed for updating)
            # For this, we need to use the GitHub API to get file info
            api_url = "https://api.github.com/repos/kobel-studios/kobel-autoclicker-competetive/contents/clicker_data.json"
            request = urllib.request.Request(
                api_url,
                headers={"Authorization": f"token {self.github_token}"}
            )
            response = urllib.request.urlopen(request)
            file_info = json.loads(response.read().decode('utf-8'))
            sha = file_info.get("sha")

            # Update the file via GitHub API
            updated_content = json.dumps(remote_data, indent=2)
            import base64
            encoded_content = base64.b64encode(updated_content.encode('utf-8')).decode('utf-8')

            put_data = {
                "message": f"Add session from {self.username}",
                "content": encoded_content,
                "sha": sha
            }

            request = urllib.request.Request(
                api_url,
                data=json.dumps(put_data).encode('utf-8'),
                headers={
                    "Authorization": f"token {self.github_token}",
                    "Content-Type": "application/json"
                },
                method="PUT"
            )
            response = urllib.request.urlopen(request)

            messagebox.showinfo("Success", "Your session has been successfully submitted to the leaderboard!")

        except urllib.error.HTTPError as e:
            if e.code == 401:
                messagebox.showerror("Error", "Invalid GitHub token. Please check your token and try again.")
            elif e.code == 403:
                messagebox.showerror("Error", "GitHub token doesn't have permission to modify the repository. Please ensure your token has 'repo' scope.")
            elif e.code == 404:
                messagebox.showerror("Error", "Repository or file not found. Please check the GitHub URL.")
            else:
                messagebox.showerror("Error", f"GitHub API error: {e.code} - {e.reason}")
        except urllib.error.URLError as e:
            messagebox.showerror("Error", f"Failed to connect to GitHub: {e}\n\nCheck your internet connection.")
        except Exception as e:
            messagebox.showerror("Error", f"An unexpected error occurred: {e}")

    def _submit_to_github(self):
        """Open GitHub Issues with pre-filled leaderboard data."""
        try:
            # Load the latest session data
            if not os.path.exists(DATA_FILE):
                messagebox.showerror("Error", "No session data found to submit.")
                return

            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            sessions = data.get("sessions", [])

            if not sessions:
                messagebox.showerror("Error", "No session data found to submit.")
                return

            # Get the most recent session
            latest_session = sessions[-1]

            # Format the issue body
            issue_title = f"Leaderboard submission from {self.username or 'Anonymous'}"
            issue_body = f"""**Username:** {self.username or 'Anonymous'}

**Session Stats:**
- Total Clicks: {latest_session.get('total_clicks', 0)}
- Duration: {latest_session.get('duration_seconds', 0)} seconds
- Max Clicks/Sec: {latest_session.get('max_clicks_per_sec', 0)}
- Avg Clicks/Sec: {latest_session.get('avg_clicks_per_sec', 0)}

**Raw Data:**
```json
{json.dumps(latest_session, indent=2)}
```

Please merge this into the global leaderboard.
"""

            # Encode the body for URL
            encoded_body = urllib.parse.quote(issue_body)
            encoded_title = urllib.parse.quote(issue_title)

            # Build the URL
            url = f"{GITHUB_ISSUES_URL}?title={encoded_title}&body={encoded_body}"

            # Open in browser
            webbrowser.open(url)

            messagebox.showinfo("Opening GitHub", "A browser window will open with your submission ready.\n\nClick 'Submit new issue' to complete the submission.")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to prepare submission: {e}")

    def _show_click_tester(self):
        """Show a click tester popup for manual clicking speed testing."""
        self.click_tester_open = True
        tester_window = tk.Toplevel(self.root)
        tester_window.title("Click Tester")
        tester_window.geometry("600x500")
        tester_window.configure(bg=BG)
        tester_window.attributes("-topmost", True)
        tester_window.resizable(True, True)  # Make window resizable
        
        # Reset flag when window closes or loses focus
        def on_close():
            self.click_tester_open = False
            self.user_clicking_on_tester = False
            tester_window.destroy()
        
        def on_focus_out(event):
            self.user_clicking_on_tester = False
        
        tester_window.protocol("WM_DELETE_WINDOW", on_close)
        tester_window.bind("<FocusOut>", on_focus_out)

        # Store original dimensions for scaling
        tester_window.original_width = 600
        tester_window.original_height = 500

        # Header
        header_frame = ttk.Frame(tester_window)
        header_frame.pack(fill="x", padx=10, pady=10)
        ttk.Label(
            header_frame,
            text="Click on the circle to test speed",
            font=("Segoe UI", 12, "bold"),
            foreground=FG,
            background=BG,
        ).pack(side="left")

        # Reset button
        ttk.Button(
            header_frame,
            text="Reset",
            command=lambda: self._reset_click_tester(tester_window),
        ).pack(side="right")

        # Canvas for click visualization
        canvas = tk.Canvas(tester_window, bg=BG, highlightthickness=0)
        canvas.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        tester_window.test_canvas = canvas

        # Stats overlay
        stats_frame = tk.Frame(canvas, bg=BG)
        stats_frame.place(relx=0.5, rely=0.05, anchor="n")
        tester_window.stats_frame = stats_frame

        self.test_clicks_var = tk.StringVar(value="Clicks: 0")
        tester_window.clicks_label = tk.Label(stats_frame, textvariable=self.test_clicks_var, font=("Segoe UI", 14, "bold"), fg=FG, bg=BG)
        tester_window.clicks_label.pack()

        self.test_cps_var = tk.StringVar(value="Speed: 0 clicks/sec")
        tester_window.cps_label = tk.Label(stats_frame, textvariable=self.test_cps_var, font=("Segoe UI", 12), fg=ACCENT, bg=BG)
        tester_window.cps_label.pack()

        # Initialize test data
        tester_window.test_clicks = 0
        tester_window.test_start_time = None
        tester_window.test_click_times = []
        tester_window.ripples = []  # Store (circle_id, x, y, creation_time) for ripple effect
        tester_window.center_circle = None  # Static center circle
        tester_window.max_ripples = 50  # Limit active ripples for performance (increased for better visibility)

        # Bind click event
        canvas.bind("<Button-1>", lambda e: self._register_test_click(tester_window, e))

        # Bind resize event to scale UI
        tester_window.bind("<Configure>", lambda e: self._on_tester_resize(tester_window))

        # Create static center circle
        self._create_center_circle(tester_window)

        # Start ripple animation loop
        self._animate_click_tester(tester_window)

    def _on_tester_resize(self, window):
        """Handle window resize and scale UI elements proportionally."""
        current_width = window.winfo_width()
        current_height = window.winfo_height()
        
        # Recreate center circle at new center position
        if window.center_circle:
            window.test_canvas.delete(window.center_circle)
        self._create_center_circle(window)
        
        # Calculate scale factors
        width_scale = current_width / window.original_width
        height_scale = current_height / window.original_height
        
        # Scale font sizes
        base_clicks_font = 14
        base_cps_font = 12
        
        new_clicks_font = max(8, int(base_clicks_font * min(width_scale, height_scale)))
        new_cps_font = max(6, int(base_cps_font * min(width_scale, height_scale)))
        
        window.clicks_label.config(font=("Segoe UI", new_clicks_font, "bold"))
        window.cps_label.config(font=("Segoe UI", new_cps_font))

    def _create_center_circle(self, window):
        """Create a static center circle for the click tester."""
        canvas_width = window.test_canvas.winfo_width()
        canvas_height = window.test_canvas.winfo_height()
        center_x = canvas_width / 2
        center_y = canvas_height / 2
        radius = 50
        
        # Create center circle with lighter background color
        bg_color = BG
        bg_r = int(bg_color[1:3], 16)
        bg_g = int(bg_color[3:5], 16)
        bg_b = int(bg_color[5:7], 16)
        
        # Lighter color (add 30 to each component)
        light_r = min(255, bg_r + 30)
        light_g = min(255, bg_g + 30)
        light_b = min(255, bg_b + 30)
        fill_color = f"#{light_r:02x}{light_g:02x}{light_b:02x}"
        
        window.center_circle = window.test_canvas.create_oval(
            center_x - radius, center_y - radius,
            center_x + radius, center_y + radius,
            fill=fill_color, outline="#000000", width=2
        )
        
        # Store center coordinates for ripple spawning
        window.center_x = center_x
        window.center_y = center_y
        window.center_radius = radius

    def _register_test_click(self, window, event):
        """Register a click in the tester and update stats."""
        import time
        import math
        
        # Check if click is within the center circle
        click_x, click_y = event.x, event.y
        distance = math.sqrt((click_x - window.center_x)**2 + (click_y - window.center_y)**2)
        
        # Only count clicks within the center circle
        if distance > window.center_radius:
            return
        
        # Set flag that user is actively clicking on tester
        self.user_clicking_on_tester = True
        
        current_time = time.time()
        window.test_clicks += 1
        window.test_click_times.append(current_time)
        
        # Create a ripple that starts exactly on the center circle's edge
        # The ripple starts with the same radius as the center circle, then expands
        # Transparent (no fill) with white outline
        circle_id = window.test_canvas.create_oval(
            window.center_x - window.center_radius,
            window.center_y - window.center_radius,
            window.center_x + window.center_radius,
            window.center_y + window.center_radius,
            fill="", outline="white"
        )
        window.ripples.append((circle_id, window.center_x, window.center_y, current_time, window.center_radius))
        
        # Remove oldest ripples if we exceed the limit
        while len(window.ripples) > window.max_ripples:
            old_circle_id, _, _, _, _ = window.ripples.pop(0)
            window.test_canvas.delete(old_circle_id)

        # Remove clicks older than 1 second for current speed calculation
        window.test_click_times = [t for t in window.test_click_times if current_time - t <= 1.0]

        # Update stats
        self.test_clicks_var.set(f"Clicks: {window.test_clicks}")
        current_cps = len(window.test_click_times)
        self.test_cps_var.set(f"Speed: {current_cps} clicks/sec")

        # Update speed display (no progress bar in new design)

    def _animate_click_tester(self, window):
        """Animate ripple effects - circles expand from center circle edge and fade out."""
        if not window.winfo_exists():
            return

        import time
        current_time = time.time()
        ripple_duration = 0.3  # Ripple lasts 0.3 seconds (faster for better visibility at high speeds)
        max_radius = 100  # Maximum radius for ripple (reduced from 150)
        
        # Update and remove old ripples
        ripples_to_keep = []
        for circle_id, center_x, center_y, creation_time, start_radius in window.ripples:
            age = current_time - creation_time
            if age >= ripple_duration:
                window.test_canvas.delete(circle_id)
            else:
                ripples_to_keep.append((circle_id, center_x, center_y, creation_time, start_radius))
                # Calculate progress (0.0 to 1.0)
                progress = age / ripple_duration
                
                # Expand radius from center circle size to max
                radius = start_radius + (max_radius - start_radius) * progress
                
                # Fade outline color (white to transparent/background)
                bg_color = BG
                bg_r = int(bg_color[1:3], 16)
                bg_g = int(bg_color[3:5], 16)
                bg_b = int(bg_color[5:7], 16)
                
                # Interpolate from white (255,255,255) to background
                r = int(255 - (255 - bg_r) * progress)
                g = int(255 - (255 - bg_g) * progress)
                b = int(255 - (255 - bg_b) * progress)
                
                outline_color = f"#{r:02x}{g:02x}{b:02x}"
                
                # Update circle (transparent fill, colored outline)
                window.test_canvas.coords(
                    circle_id,
                    center_x - radius, center_y - radius,
                    center_x + radius, center_y + radius
                )
                window.test_canvas.itemconfig(circle_id, fill="", outline=outline_color)
        
        window.ripples = ripples_to_keep

        # Schedule next animation frame (60 FPS for smooth ripple)
        window.after(16, lambda: self._animate_click_tester(window))

    def _reset_click_tester(self, window):
        """Reset the click tester stats."""
        window.test_clicks = 0
        window.test_click_times = []
        window.ripples = []
        window.test_canvas.delete("all")  # Clear all circles
        # Recreate center circle
        self._create_center_circle(window)
        self.test_clicks_var.set("Clicks: 0")
        self.test_cps_var.set("Speed: 0 clicks/sec")

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
