import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
import math
import random
import threading
import time

class WritingApp(tk.Tk):
	"""A writing workspace with a countdown and optional human-like typing."""

	TYPING_WPM = 120
	CHARS_PER_WORD = 5
	TYPO_CHANCE = 0.1
	SLOWDOWN_CHANCE = 0.3
	MAX_SLOWDOWN_WPM = 40

	def __init__(self):
		super().__init__()
		self.title("AntiAI Write")
		self.geometry("900x600")
		self.minsize(620, 420)
		self.configure(bg="#10141c")

		self.remaining = 5
		self.running = False
		self.paused = False
		self.typing_started = False
		self.timer_id = None
		self.typing_countdown_id = None
		self.typing_thread = None
		self.stop_typing = threading.Event()
		self.pause_typing = threading.Event()
		self.typing_content = ""
		self.typing_index = 0
		self.current_file = None
		self.dirty = False
		self.q_poll_id = None
		self.q_down = False

		self._build_styles()
		self._build_ui()
		self.text.bind("<KeyRelease>", self._on_key_release)
		self.text.bind("<<Modified>>", self._on_modified)
		self.bind_all("<Control-c>", self._handle_ctrl_c)
		self.bind_all("<KeyPress-q>", self._handle_pause_key)
		self.bind_all("<KeyPress-Q>", self._handle_pause_key)
		self.protocol("WM_DELETE_WINDOW", self._close)
		self.q_poll_id = self.after(50, self._poll_global_q)

	def _build_styles(self):
		style = ttk.Style(self)
		style.theme_use("clam")
		style.configure("Start.TButton", background="#7c5cff", foreground="white",
						borderwidth=0, padding=(24, 11), font=("Segoe UI", 10, "bold"))
		style.map("Start.TButton", background=[("active", "#947cff")])

	def _build_ui(self):
		self.columnconfigure(0, weight=1)
		self.rowconfigure(1, weight=1)
		header = tk.Frame(self, bg="#10141c")
		header.grid(row=0, column=0, sticky="ew", padx=34, pady=(26, 18))
		header.columnconfigure(1, weight=1)
		tk.Label(header, text="AntiAI", bg="#10141c", fg="#f5f7fb",
				 font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
		tk.Label(header, text="  /  write freely", bg="#10141c", fg="#788398",
				 font=("Segoe UI", 11)).grid(row=0, column=1, sticky="w")

		editor = tk.Frame(self, bg="#191f2a", highlightthickness=1,
						  highlightbackground="#293243")
		editor.grid(row=1, column=0, sticky="nsew", padx=34)
		editor.rowconfigure(0, weight=1)
		editor.columnconfigure(0, weight=1)
		self.text = tk.Text(editor, wrap="word", undo=True, borderwidth=0,
							padx=28, pady=24, bg="#191f2a", fg="#e9edf5",
							insertbackground="#9b87ff", selectbackground="#4b3d89",
							font=("Segoe UI", 13), spacing1=4)
		self.text.grid(row=0, column=0, sticky="nsew")
		scrollbar = ttk.Scrollbar(editor, orient="vertical", command=self.text.yview)
		scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 6), pady=8)
		self.text.configure(yscrollcommand=scrollbar.set)

		footer = tk.Frame(self, bg="#10141c")
		footer.grid(row=2, column=0, sticky="ew", padx=34, pady=(18, 26))
		footer.columnconfigure(1, weight=1)
		self.timer_label = tk.Label(footer, text="~ 0 seconds to type", bg="#10141c",
									fg="#aeb8c9", font=("Segoe UI", 10))
		self.timer_label.grid(row=0, column=0, sticky="w")
		self.status_label = tk.Label(footer, text="Ready", bg="#10141c", fg="#788398",
									 font=("Segoe UI", 10))
		self.status_label.grid(row=0, column=1)
		self.word_count = tk.Label(footer, text="0 words", bg="#10141c", fg="#788398",
								   font=("Segoe UI", 10))
		self.word_count.grid(row=0, column=1, sticky="e", padx=(0, 90))
		self.start_button = ttk.Button(footer, text="Start", style="Start.TButton",
									   command=self.toggle_timer)
		self.start_button.grid(row=0, column=2, sticky="e")

	def _on_text_changed(self):
		content = self.text.get("1.0", "end-1c")
		words = len(content.split())
		self.word_count.configure(text=f"{words:,} {'word' if words == 1 else 'words'}")
		self.dirty = bool(content)
		if not self.running and not self.paused:
			self.timer_label.configure(text=f"~ {self._estimated_seconds(content)} seconds to type")

	def _on_key_release(self, _event=None):
		self._on_text_changed()

	def _on_modified(self, _event=None):
		self.text.edit_modified(False)

	def _estimated_seconds(self, content=None):
		if content is None:
			content = self.text.get("1.0", "end-1c")
		if not content:
			return 0
		seconds = len(content) * 60 / (self.TYPING_WPM * self.CHARS_PER_WORD)
		return max(1, math.ceil(seconds))

	def _handle_pause_key(self, _event=None):
		if _event is not None and getattr(_event, "keysym", "").lower() == "q":
			self.q_down = True
		if not (self.running or self.paused):
			return None
		if self.running:
			self.paused = True
			self.running = False
			self.pause_typing.set()
			self._cancel_after("timer_id")
			self._cancel_after("typing_countdown_id")
			self.start_button.configure(text="Resume")
			self.status_label.configure(text="Paused")
		else:
			self.paused = False
			self.running = True
			self.pause_typing.clear()
			self.start_button.configure(text="Cancel")
			self.status_label.configure(text="Typing" if self.typing_started else "Switch to Word...")
			if self.typing_started:
				self.typing_countdown_id = self.after(1000, self._count_typing_time)
			else:
				self._tick()
		return "break"

	def _poll_global_q(self):
		"""Detect Q even after pyautogui has moved focus to another application."""
		try:
			import ctypes
			q_pressed = bool(ctypes.windll.user32.GetAsyncKeyState(0x51) & 0x8000)
		except (AttributeError, OSError):
			q_pressed = False

		if q_pressed and not self.q_down:
			self.q_down = True
			self._handle_pause_key()
		elif not q_pressed:
			self.q_down = False
		self.q_poll_id = self.after(50, self._poll_global_q)

	def _handle_ctrl_c(self, event=None):
		# Preserve normal copy behavior unless a typing session is active.
		if self.running or self.paused:
			return self._handle_pause_key(event)
		return None

	def _cancel_after(self, attribute):
		identifier = getattr(self, attribute)
		if identifier is not None:
			try:
				self.after_cancel(identifier)
			except tk.TclError:
				pass
			setattr(self, attribute, None)

	def _confirm_discard(self):
		if not self.dirty:
			return True
		answer = messagebox.askyesnocancel("Unsaved changes", "Save your changes before continuing?", parent=self)
		if answer is None:
			return False
		return self.save_document() if answer else True

	def new_document(self):
		if not self._confirm_discard():
			return
		self.text.delete("1.0", "end")
		self.current_file = None
		self.dirty = False
		self.title("AntiAI Write")
		self.status_label.configure(text="Ready")
		self._on_text_changed()

	def open_document(self):
		if not self._confirm_discard():
			return
		chosen = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
		if not chosen:
			return
		try:
			content = Path(chosen).read_text(encoding="utf-8")
		except (OSError, UnicodeError) as error:
			messagebox.showerror("Open failed", str(error), parent=self)
			return
		self.text.delete("1.0", "end")
		self.text.insert("1.0", content)
		self.current_file = Path(chosen)
		self.dirty = False
		self.title(f"{self.current_file.name} - AntiAI Write")
		self.status_label.configure(text="Ready")
		self._on_text_changed()
		self.dirty = False

	def save_document(self, save_as=False):
		path = self.current_file
		if path is None or save_as:
			chosen = filedialog.asksaveasfilename(defaultextension=".txt",
												  filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
			if not chosen:
				return False
			path = Path(chosen)
		try:
			path.write_text(self.text.get("1.0", "end-1c"), encoding="utf-8")
		except OSError as error:
			messagebox.showerror("Save failed", str(error), parent=self)
			return False
		self.current_file = path
		self.dirty = False
		self.title(f"{path.name} - AntiAI Write")
		self.status_label.configure(text="Saved")
		return True

	def toggle_timer(self):
		if self.paused:
			self.stop_typing.set()
			self.pause_typing.clear()
			self.paused = False
			self.typing_started = False
			self.typing_index = 0
		if self.running:
			self.running = False
			self.stop_typing.set()
			self._cancel_after("timer_id")
			self._cancel_after("typing_countdown_id")
			self.start_button.configure(text="Start")
			self.status_label.configure(text="Ready")
			return
		content = self.text.get("1.0", "end-1c")
		if not content:
			messagebox.showinfo("Nothing to type", "Paste or write some text first.", parent=self)
			return
		self.remaining = 5
		self.typing_content = content
		self.typing_index = 0
		self.typing_started = False
		self.stop_typing.clear()
		self.pause_typing.clear()
		self.running = True
		self.start_button.configure(text="Cancel")
		self.status_label.configure(text="Switch to Word...")
		self._tick()

	def _tick(self):
		if not self.running:
			return
		if self.remaining <= 0:
			self.timer_id = None
			self.typing_started = True
			self.remaining = self._estimated_seconds(self.typing_content)
			self.status_label.configure(text="Typing")
			self.timer_label.configure(text=f"{self.remaining} seconds remaining")
			self.typing_thread = threading.Thread(target=self._type_like_human,
												   args=(self.typing_content,), daemon=True)
			self.typing_thread.start()
			self.typing_countdown_id = self.after(1000, self._count_typing_time)
			return
		self.timer_label.configure(text=f"{self.remaining} seconds until typing")
		self.remaining -= 1
		self.timer_id = self.after(1000, self._tick)

	def _count_typing_time(self):
		if not self.running or not self.typing_started:
			self.typing_countdown_id = None
			return
		self.remaining = max(0, self.remaining - 1)
		self.timer_label.configure(text=f"{self.remaining} seconds remaining")
		self.typing_countdown_id = self.after(1000, self._count_typing_time)

	def _type_like_human(self, content):
		try:
			import pyautogui
		except ImportError:
			self.after(0, self._typing_failed)
			return
		pyautogui.PAUSE = 0.001
		for index in range(self.typing_index, len(content)):
			while self.pause_typing.is_set() and not self.stop_typing.is_set():
				time.sleep(0.02)
			if self.stop_typing.is_set():
				return
			character = content[index]
			if character == "\n":
				pyautogui.press("enter")
			elif character == "\t":
				pyautogui.press("tab")
			else:
				if character.isalpha() and random.random() < self.TYPO_CHANCE:
					pyautogui.write(random.choice("abcdefghijklmnopqrstuvwxyz"))
					pyautogui.press("backspace")
				pyautogui.write(character)
			self.typing_index = index + 1
			wpm = self.TYPING_WPM
			if random.random() < self.SLOWDOWN_CHANCE:
				wpm -= random.randint(0, self.MAX_SLOWDOWN_WPM)
			interval = 60 / (wpm * self.CHARS_PER_WORD)
			time.sleep(interval * random.uniform(0.35, 1.8))
		self.after(0, self._typing_finished)

	def _typing_failed(self):
		self.running = False
		self._cancel_after("typing_countdown_id")
		self.start_button.configure(text="Start")
		self.status_label.configure(text="Typing unavailable")
		messagebox.showerror("Typing unavailable", "Install pyautogui with: pip install pyautogui", parent=self)

	def _typing_finished(self):
		self.running = False
		self._cancel_after("typing_countdown_id")
		self.start_button.configure(text="Start")
		self.status_label.configure(text="Complete")
		self.typing_started = False
		self.timer_label.configure(text=f"~ {self._estimated_seconds(self.typing_content)} seconds to type")

	def _close(self):
		if self.dirty and not messagebox.askyesno("Unsaved changes", "Exit without saving?", parent=self):
			return
		self.running = False
		self._cancel_after("timer_id")
		self._cancel_after("typing_countdown_id")
		self._cancel_after("q_poll_id")
		self.stop_typing.set()
		self.pause_typing.clear()
		self.destroy()


if __name__ == "__main__":
	WritingApp().mainloop()

