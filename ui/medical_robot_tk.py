import tkinter as tk
from tkinter import ttk, scrolledtext
from tkinter import font as tkfont
import threading
from core.chat import ChatBot
from core.audio import AudioProcessor
from core.tts import TextToSpeech

class MedicalRobotUI:
    def __init__(self, root):
        self.root = root
        self.root.title("智护夜巡")
        self.root.geometry("1000x700")
        self.root.configure(bg='#f0f0f0')

        # 语言设置
        self.languages = {
            "粤语": {"whisper": "yue", "tts": "zh-HK-HiuGaaiNeural"},
            "普通话": {"whisper": "zh", "tts": "zh-CN-XiaoxiaoNeural"},
            "英语": {"whisper": "en", "tts": "en-US-JennyNeural"}
        }
        self.current_language = "粤语"

        # 业务逻辑核心
        self.chat_core = ChatBot()
        self.audio_core = AudioProcessor()
        self.tts_core = TextToSpeech()

        # 读取system prompt
        with open("configs/system_prompt.txt", "r", encoding="utf-8") as f:
            self.system_prompt = f.read()

        # 创建界面
        self.create_widgets()
        self.process_messages()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        title_font = tkfont.Font(family="Microsoft YaHei", size=24, weight="bold")
        title_label = ttk.Label(
            main_frame,
            text="智护夜巡机器人",
            font=title_font,
            foreground="#2c3e50"
        )
        title_label.pack(pady=(0, 20))
        chat_frame = ttk.Frame(main_frame)
        chat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 20))
        self.chat_display = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            width=80,
            height=25,
            font=("Microsoft YaHei", 12),
            bg="#ffffff",
            fg="#2c3e50",
            padx=10,
            pady=10
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(0, 10))
        inner_button_frame = ttk.Frame(button_frame)
        inner_button_frame.pack(expand=True)
        style = ttk.Style()
        style.configure(
            "Custom.TButton",
            padding=10,
            font=("Microsoft YaHei", 12),
            background="#3498db",
            foreground="#2c3e50"
        )
        self.language_button = ttk.Button(
            inner_button_frame,
            text=f"当前语言: {self.current_language}",
            command=self.toggle_language,
            style="Custom.TButton",
            width=15
        )
        self.language_button.pack(side=tk.LEFT, padx=5)
        self.record_button = ttk.Button(
            inner_button_frame,
            text="开始录音",
            command=self.start_recording,
            style="Custom.TButton",
            width=15
        )
        self.record_button.pack(side=tk.LEFT, padx=5)
        self.clear_button = ttk.Button(
            inner_button_frame,
            text="清除对话",
            command=self.clear_chat,
            style="Custom.TButton",
            width=15
        )
        self.clear_button.pack(side=tk.LEFT, padx=5)
        self.status_label = ttk.Label(
            main_frame,
            text="就绪",
            font=("Microsoft YaHei", 10),
            foreground="#7f8c8d"
        )
        self.status_label.pack(pady=(0, 5))

    def toggle_language(self):
        languages = list(self.languages.keys())
        current_index = languages.index(self.current_language)
        next_index = (current_index + 1) % len(languages)
        self.current_language = languages[next_index]
        self.language_button.configure(text=f"当前语言: {self.current_language}")
        self.chat_display.insert(tk.END, f"已切换到{self.current_language}\n", "system")
        self.chat_display.tag_configure("system", foreground="#7f8c8d")
        self.chat_display.see(tk.END)

    def start_recording(self):
        self.record_button.configure(state="disabled", text="录音中...")
        self.status_label.configure(text="正在录音...")
        self.chat_display.insert(tk.END, "正在录音...\n")
        self.chat_display.see(tk.END)
        self.audio_core.record_audio("temp.wav", callback=self._on_record_complete)

    def _on_record_complete(self, success, filename=None, error=None):
        self.record_button.configure(state="normal", text="开始录音")
        self.status_label.configure(text="就绪")
        if success:
            self.audio_core.transcribe_audio(filename, self.languages[self.current_language]["whisper"], callback=self._on_transcribe_complete)
        else:
            self.chat_display.insert(tk.END, f"录音失败: {error}\n", "error")
            self.chat_display.tag_configure("error", foreground="#e74c3c")
            self.chat_display.see(tk.END)

    def _on_transcribe_complete(self, success, text=None, error=None):
        if success and text and text.strip():
            self.chat_display.insert(tk.END, f"你说: {text}\n", "user")
            self.chat_display.tag_configure("user", foreground="#2980b9")
            self.chat_display.see(tk.END)
            self.status_label.configure(text="AI处理中...")
            self.chat_core.chat_with_ai(text, self.system_prompt, callback=self._on_ai_response)
        else:
            self.chat_display.insert(tk.END, f"没有检测到语音或识别失败: {error}\n", "error")
            self.chat_display.tag_configure("error", foreground="#e74c3c")
            self.chat_display.see(tk.END)
            self.status_label.configure(text="就绪")

    def _on_ai_response(self, success, response=None, error=None):
        if success:
            self.chat_display.insert(tk.END, f"AI: {response}\n", "ai")
            self.chat_display.tag_configure("ai", foreground="#27ae60")
            self.chat_display.see(tk.END)
            self.status_label.configure(text="正在播报...")
            self.tts_core.text_to_speech(response, self.languages[self.current_language]["tts"], callback=self._on_tts_complete)
        else:
            self.chat_display.insert(tk.END, f"AI接口错误: {error}\n", "error")
            self.chat_display.tag_configure("error", foreground="#e74c3c")
            self.chat_display.see(tk.END)
            self.status_label.configure(text="就绪")

    def _on_tts_complete(self, success, error=None):
        if not success:
            self.chat_display.insert(tk.END, f"语音合成错误: {error}\n", "error")
            self.chat_display.tag_configure("error", foreground="#e74c3c")
        self.status_label.configure(text="就绪")

    def process_messages(self):
        self.root.after(100, self.process_messages)

    def clear_chat(self):
        self.chat_display.delete(1.0, tk.END)
        self.chat_core.clear_history() 