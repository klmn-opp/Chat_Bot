import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from tkinter import font as tkfont
import threading
from core.stream_controller import StreamController
from ui.components.conversation_manager import ConversationManager
from ui.components.realtime_display import RealtimeDisplay

class MedicalRobotStreamUI:
    """
    流式医疗机器人UI
    全新的流式对话UI，完全独立于传统UI
    """
    
    def __init__(self, root):
        self.root = root
        self.root.title("智护夜巡 - 流式对话版")
        self.root.geometry("1200x800")
        self.root.configure(bg='#f8f9fa')
        
        # 设备设置
        self.input_device_index = 2
        self.output_device_index = None
        
        # 核心组件初始化
        self.stream_controller = StreamController(
            input_device_index=self.input_device_index,
            output_device_index=self.output_device_index
        )
        
        # UI管理组件
        self.conversation_manager = ConversationManager(self.on_ui_update)
        self.realtime_display = None  # 在创建界面后初始化
        
        # 当前状态 - 强制初始化为idle
        self.current_state = "idle"
        self.current_language = "普通话"  # 默认语言
        
        # 创建界面
        self.create_widgets()
        
        # 初始化实时显示组件
        self.realtime_display = RealtimeDisplay(self.chat_display)
        
        # 绑定回调
        self.setup_callbacks()
        
        # 强制重置状态确保同步
        self.force_reset_state()
        
        # 启动UI更新循环
        self.process_ui_updates()
        
        print("🎉 流式UI初始化完成")
    
    def setup_callbacks(self):
        """设置流式控制器的回调（UI只订阅，不修改）"""
        self.stream_controller.set_state_change_callback(self._on_controller_state_change)
        self.stream_controller.set_transcription_callback(self.on_realtime_transcription)
        self.stream_controller.set_final_result_callback(self.on_final_result)
        self.stream_controller.set_ai_response_callback(self.on_ai_response)
        self.stream_controller.set_error_callback(self.on_error)
    
    def create_widgets(self):
        """创建现代化UI界面"""
        # 主容器
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 标题区域
        self.create_header(main_frame)
        
        # 状态指示器
        self.create_status_indicator(main_frame)
        
        # 对话显示区域
        self.create_chat_area(main_frame)
        
        # 控制按钮区域
        self.create_control_panel(main_frame)
        
        # 底部状态栏
        self.create_status_bar(main_frame)
    
    def create_header(self, parent):
        """创建标题区域"""
        header_frame = ttk.Frame(parent)
        header_frame.pack(fill=tk.X, pady=(0, 20))
        
        # 主标题
        title_font = tkfont.Font(family="Microsoft YaHei", size=28, weight="bold")
        title_label = ttk.Label(
            header_frame,
            text="🤖 智护夜巡",
            font=title_font,
            foreground="#2c3e50"
        )
        title_label.pack(side=tk.LEFT)
        
        # 副标题
        subtitle_font = tkfont.Font(family="Microsoft YaHei", size=12)
        subtitle_label = ttk.Label(
            header_frame,
            text="实时语音对话系统",
            font=subtitle_font,
            foreground="#7f8c8d"
        )
        subtitle_label.pack(side=tk.LEFT, padx=(10, 0))
        
        # 版本标识
        version_label = ttk.Label(
            header_frame,
            text="Stream v2.0",
            font=("Microsoft YaHei", 10),
            foreground="#95a5a6"
        )
        version_label.pack(side=tk.RIGHT)
    
    def create_status_indicator(self, parent):
        """创建状态指示器"""
        status_frame = ttk.Frame(parent)
        status_frame.pack(fill=tk.X, pady=(0, 15))
        
        # 状态指示灯
        self.status_canvas = tk.Canvas(status_frame, width=20, height=20, highlightthickness=0)
        self.status_canvas.pack(side=tk.LEFT, padx=(0, 10))
        
        # 状态圆圈
        self.status_circle = self.status_canvas.create_oval(2, 2, 18, 18, fill="#34C759", outline="")
        
        # 状态文字
        self.status_text = ttk.Label(
            status_frame,
            text="🎤 点击开始对话",
            font=("Microsoft YaHei", 12, "bold"),
            foreground="#34C759"
        )
        self.status_text.pack(side=tk.LEFT)
        
        # 语言指示器
        self.language_indicator = ttk.Label(
            status_frame,
            text=f"语言: {self.current_language}",
            font=("Microsoft YaHei", 10),
            foreground="#7f8c8d"
        )
        self.language_indicator.pack(side=tk.RIGHT)
    
    def create_chat_area(self, parent):
        """创建对话显示区域"""
        chat_frame = ttk.LabelFrame(parent, text=" 对话记录 ", padding="15")
        chat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 20))
        
        # 对话显示文本框
        self.chat_display = scrolledtext.ScrolledText(
            chat_frame,
            wrap=tk.WORD,
            width=100,
            height=30,
            font=("Microsoft YaHei", 12),
            bg="#ffffff",
            fg="#2c3e50",
            padx=15,
            pady=15,
            relief=tk.FLAT,
            borderwidth=0
        )
        self.chat_display.pack(fill=tk.BOTH, expand=True)
        
        # 添加欢迎消息
        welcome_msg = "欢迎使用智护夜巡实时对话系统！\n点击\"开始对话\"开始语音交互。\n\n"
        self.chat_display.insert(tk.END, welcome_msg, "system")
    
    def create_control_panel(self, parent):
        """创建控制按钮面板（修复布局，确保按钮显示）"""
        control_frame = ttk.Frame(parent)
    # 关键修改：用pack(fill=tk.X, pady=20)，确保面板显示在对话区域下方
        control_frame.pack(fill=tk.X, pady=20)
    
    # 直接显示按钮，去掉多余的居中容器（先让按钮显示）
        style = ttk.Style()
        style.configure(
	"Action.TButton",
    	padding=(20, 10),
	font=("Microsoft YaHei", 14, "bold")
    )
    
    # 主要对话按钮（必显示）
        self.conversation_button = ttk.Button(
	    control_frame,
    	    text="🎤 开始对话",
    	    command=self.toggle_conversation,
	    style="Action.TButton",
    	    width=20
        )
    # 直接pack，不嵌套容器，确保显示
        self.conversation_button.pack(pady=10)
    
    # 第二排按钮（可选，先简化）
        second_row = ttk.Frame(control_frame)
        second_row.pack(fill=tk.X, pady=5)
    
        self.language_button = ttk.Button(
	    second_row,
	    text=f"语言: {self.current_language}",
       	    command=self.toggle_language,
	    width=15
        )
        self.language_button.pack(side=tk.LEFT, padx=5)
    
        self.device_button = ttk.Button(
	    second_row,
	    text="🔧 设备设置",
	    command=self.show_device_dialog,
	    width=15
        )
        self.device_button.pack(side=tk.LEFT, padx=5)
    
        self.clear_button = ttk.Button(
	    second_row,
	    text="🗑️ 清除对话",
	    command=self.clear_conversation,
	    width=15
        )
        self.clear_button.pack(side=tk.LEFT, padx=5)
        
    def create_status_bar(self, parent):
        """创建底部状态栏"""
        status_bar = ttk.Frame(parent, relief=tk.SUNKEN)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.bottom_status = ttk.Label(
            status_bar,
            text="就绪 | Docker状态: 连接中...",
            font=("Microsoft YaHei", 9),
            foreground="#7f8c8d"
        )
        self.bottom_status.pack(side=tk.LEFT, padx=5, pady=2)
        
        # 版权信息
        copyright_label = ttk.Label(
            status_bar,
            text="© 2024 智护夜巡团队",
            font=("Microsoft YaHei", 8),
            foreground="#bdc3c7"
        )
        copyright_label.pack(side=tk.RIGHT, padx=5, pady=2)
    
    def toggle_conversation(self):
        """切换对话状态（仅发送指令，不预判状态）"""
        print(f"🔘 按钮被点击，当前UI显示状态: {self.current_state}")
        
        # ✅ 核心修改：不再根据 UI 状态判断，直接把指令发给 Controller
        # 由 Controller 内部决定当前状态下是否能执行 start/stop
        if self.current_state == "idle" or self.current_state == "listening":
            # 简单的切换逻辑：如果是 idle 就 start，如果是 listening 就 stop
            # 但最终决定权在 Controller
            if self.current_state == "idle":
                print("▶️  UI发送“开始”指令")
                self.stream_controller.start_conversation()
            else:
                print("⏹️  UI发送“停止”指令")
                self.stream_controller.stop_conversation()
        else:
            messagebox.showinfo("提示", f"系统繁忙中，请稍候... (状态: {self.current_state})")
    
    def start_conversation(self):
        """开始对话"""
        success = self.stream_controller.start_conversation()
        if not success:
            messagebox.showerror("错误", "启动对话失败，请检查麦克风设备和网络连接")
    
    def stop_conversation(self):
        """停止对话"""
        success = self.stream_controller.stop_conversation()
        if not success:
            messagebox.showerror("错误", "停止对话失败")
    
    def toggle_language(self):
        """切换语言"""
        languages = ["粤语", "普通话", "英语"]
        current_index = languages.index(self.current_language)
        next_index = (current_index + 1) % len(languages)
        new_language = languages[next_index]
        
        self.current_language = new_language
        self.stream_controller.set_language(new_language)
        
        # 更新UI显示
        self.language_button.configure(text=f"语言: {new_language}")
        self.language_indicator.configure(text=f"语言: {new_language}")
        
        # 添加系统消息
        self.realtime_display.add_system_message(f"已切换到{new_language}")
    
    def clear_conversation(self):
        """清除对话"""
        if messagebox.askyesno("确认", "确定要清除所有对话记录吗？"):
            self.realtime_display.clear_all()
            self.stream_controller.clear_conversation_history()
            self.conversation_manager.clear_conversation()
            
            # 重新添加欢迎消息
            welcome_msg = "对话记录已清除。\n点击\"开始对话\"开始新的语音交互。\n\n"
            self.chat_display.insert(tk.END, welcome_msg, "system")
    
    def show_device_dialog(self):
        """显示设备设置对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title("音频设备设置")
        dialog.geometry("1600x1400")
        dialog.transient(self.root)
        dialog.grab_set()
        
        try:
            input_devices, output_devices = self.stream_controller.list_audio_devices()
        except Exception as e:
            messagebox.showerror("错误", f"获取设备列表失败: {e}")
            dialog.destroy()
            return
        
        # 主框架
        main_frame = ttk.Frame(dialog, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 录音设备选择
        input_frame = ttk.LabelFrame(main_frame, text=" 录音设备 ", padding="10")
        input_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.input_var = tk.StringVar(value="default")
        default_input = ttk.Radiobutton(
            input_frame,
            text="使用系统默认设备",
            variable=self.input_var,
            value="default"
        )
        default_input.pack(anchor=tk.W, pady=2)
        
        for device in input_devices:
            ttk.Radiobutton(
                input_frame,
                text=f"设备 {device['index']}: {device['name']}",
                variable=self.input_var,
                value=str(device['index'])
            ).pack(anchor=tk.W, pady=1)
        
        # 播放设备选择
        output_frame = ttk.LabelFrame(main_frame, text=" 播放设备 ", padding="10")
        output_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.output_var = tk.StringVar(value="default")
        default_output = ttk.Radiobutton(
            output_frame,
            text="使用系统默认设备",
            variable=self.output_var,
            value="default"
        )
        default_output.pack(anchor=tk.W, pady=2)
        
        for device in output_devices:
            ttk.Radiobutton(
                output_frame,
                text=f"设备 {device['index']}: {device['name']}",
                variable=self.output_var,
                value=str(device['index'])
            ).pack(anchor=tk.W, pady=1)
        
        # 按钮区域
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        def apply_device_settings():
            input_choice = self.input_var.get()
            output_choice = self.output_var.get()
            
            input_idx = None if input_choice == "default" else int(input_choice)
            output_idx = None if output_choice == "default" else int(output_choice)
            
            self.stream_controller.set_devices(2, output_idx)
            print("在总ui.py中[385]强制使用2作为input_device")
            self.input_device_index = 2
            self.output_device_index = output_idx
            
            self.realtime_display.add_system_message("音频设备设置已更新")
            dialog.destroy()
        
        ttk.Button(button_frame, text="应用", command=apply_device_settings).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.RIGHT)
    
    # 回调函数处理
    def on_state_change(self, new_state, data):
        """状态变化回调"""
        self.current_state = new_state
        self.update_ui_state(new_state)
    
    def on_realtime_transcription(self, text, is_final):
        """实时转录回调"""
        if not is_final:
            self.realtime_display.show_realtime_text(text)
    
    def on_final_result(self, text):
        """最终识别结果回调"""
        timestamp = self.conversation_manager._get_timestamp()
        self.realtime_display.confirm_final_text(text, "user", timestamp)
        self.conversation_manager.finalize_user_input(text)
    
    def on_ai_response(self, response):
        """AI响应回调"""
        timestamp = self.conversation_manager._get_timestamp()
        self.realtime_display.confirm_final_text(response, "ai", timestamp)
        self.conversation_manager.add_ai_response(response)
    
    def on_error(self, error):
        """错误回调"""
        self.realtime_display.add_system_message(f"错误: {error}")
        self.current_state = "idle"
        self.update_ui_state("idle")
    
    def on_ui_update(self, event_type, data):
        """UI更新回调"""
        # 处理来自ConversationManager的UI更新事件
        pass
    
    def _on_controller_state_change(self, new_state, data):
        """
        【唯一合法的状态更新入口】
        只有 Controller 能调用这个方法来改变 UI 显示
        UI 绝不主动调用这个方法
        """
        print(f"📥 [Controller→UI] 状态更新: {data.get('old_state', '?')} → {new_state}")
        
        # ✅ 只更新 UI 自己的显示变量，不动 Controller 的任何东西
        self.current_state = new_state
        self.update_ui_state(new_state)

    def update_ui_state(self, state):
        """更新UI状态显示"""
        state_config = {
            "idle": {
                "color": "#34C759",
                "text": "🎤 开始对话",
                "status": "🎤 点击开始对话",
                "button_text": "🎤 开始对话"
            },
            "listening": {
                "color": "#FF3B30", 
                "text": "🛑 停止对话",
                "status": "🔴 正在聆听...",
                "button_text": "🛑 停止对话"
            },
            "processing": {
                "color": "#FF9500",
                "text": "⏳ 处理中...",
                "status": "⏳ AI思考中...",
                "button_text": "⏳ 处理中..."
            },
            "speaking": {
                "color": "#5856D6",
                "text": "🔊 播报中...",
                "status": "🔊 正在播报...",
                "button_text": "🔊 播报中..."
            }
        }
        
        config = state_config.get(state, state_config["idle"])
        
        # 更新状态指示灯
        self.status_canvas.itemconfig(self.status_circle, fill=config["color"])
        
        # 更新状态文字
        self.status_text.configure(text=config["status"], foreground=config["color"])
        
        # 更新按钮
        self.conversation_button.configure(text=config["button_text"])
        
        # 根据状态启用/禁用按钮
        if state in ["processing", "speaking"]:
            self.conversation_button.configure(state="disabled")
            self.language_button.configure(state="disabled")
        else:
            self.conversation_button.configure(state="normal")
            self.language_button.configure(state="normal")
    
    def process_ui_updates(self):
        """UI更新循环（仅做健康检查，绝不修改状态）"""
        try:
            # ✅ 移除所有 "检测到状态不同步" 后强制覆盖的代码
            # ✅ 只做一些纯 UI 的、只读的更新（比如滚动条、时间显示等）
            pass
        except Exception as e:
            print(f"⚠️ UI循环异常: {e}")
        
        # 继续循环
        self.root.after(200, self.process_ui_updates)
    
    def force_reset_state(self):
        """强制重置（仅重置 UI 显示，不碰 Controller）"""
        print("🔄 [UI] 仅重置 UI 显示状态为 idle")
        self.current_state = "idle"
        self.update_ui_state("idle")
        # ❌ 绝对禁止：self.stream_controller.conversation_state = "idle"
