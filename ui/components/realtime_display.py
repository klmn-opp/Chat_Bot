import tkinter as tk
from typing import Optional

class RealtimeDisplay:
    """
    实时显示组件
    专门处理实时文字显示的UI组件
    """
    
    def __init__(self, text_widget: tk.Text):
        self.text_widget = text_widget
        self.realtime_line_start = None
        self.realtime_line_end = None
        
        # 配置文本样式
        self._setup_text_tags()
    
    def _setup_text_tags(self):
        """设置文本标签样式"""
        # 实时文本样式（灰色、斜体）
        self.text_widget.tag_configure("realtime", 
                                     foreground="#8E8E93", 
                                     font=("TkDefaultFont", 12, "italic"))
        
        # 用户输入样式（蓝色）
        self.text_widget.tag_configure("user", 
                                     foreground="#007AFF", 
                                     font=("TkDefaultFont", 12, "bold"))
        
        # AI响应样式（绿色）
        self.text_widget.tag_configure("ai", 
                                     foreground="#34C759", 
                                     font=("TkDefaultFont", 12))
        
        # 系统消息样式（灰色）
        self.text_widget.tag_configure("system", 
                                     foreground="#8E8E93", 
                                     font=("TkDefaultFont", 10))
        
        # 时间戳样式（浅灰色、小字）
        self.text_widget.tag_configure("timestamp", 
                                     foreground="#C7C7CC", 
                                     font=("TkDefaultFont", 9))
    
    def show_realtime_text(self, text: str):
        """显示实时识别文本（灰色、斜体）"""
        # 如果已有实时文本，先清除
        if self.realtime_line_start is not None:
            self.text_widget.delete(self.realtime_line_start, self.realtime_line_end)
        
        # 插入新的实时文本
        self.realtime_line_start = self.text_widget.index(tk.INSERT)
        self.text_widget.insert(tk.INSERT, f"[识别中] {text}", "realtime")
        self.realtime_line_end = self.text_widget.index(tk.INSERT)
        
        # 滚动到底部
        self.text_widget.see(tk.END)
    
    def confirm_final_text(self, text: str, speaker: str = "user", timestamp: str = ""):
        """确认最终文本（正常颜色）"""
        # 清除实时文本
        self.clear_realtime()
        
        # 选择样式
        if speaker == "user":
            tag = "user"
            prefix = "你说"
        elif speaker == "ai":
            tag = "ai" 
            prefix = "AI"
        elif speaker == "system":
            tag = "system"
            prefix = "系统"
        else:
            tag = "system"
            prefix = speaker
        
        # 插入时间戳（如果提供）
        if timestamp:
            self.text_widget.insert(tk.END, f"[{timestamp}] ", "timestamp")
        
        # 插入正式文本
        self.text_widget.insert(tk.END, f"{prefix}: {text}\n", tag)
        
        # 滚动到底部
        self.text_widget.see(tk.END)
    
    def add_system_message(self, message: str, timestamp: str = ""):
        """添加系统消息"""
        self.confirm_final_text(message, "system", timestamp)
    
    def clear_realtime(self):
        """清除实时显示"""
        if self.realtime_line_start is not None:
            self.text_widget.delete(self.realtime_line_start, self.realtime_line_end)
            self.realtime_line_start = None
            self.realtime_line_end = None
    
    def clear_all(self):
        """清除所有显示内容"""
        self.text_widget.delete(1.0, tk.END)
        self.realtime_line_start = None
        self.realtime_line_end = None
    
    def add_conversation_bubble(self, text: str, speaker: str = "user", timestamp: str = ""):
        """添加对话气泡样式的消息"""
        # 为未来扩展预留的气泡样式功能
        self.confirm_final_text(text, speaker, timestamp) 