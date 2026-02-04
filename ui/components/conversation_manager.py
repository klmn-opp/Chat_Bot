from typing import Callable, List, Dict, Optional
import threading

class ConversationManager:
    """
    对话状态管理器
    管理对话状态、历史记录和实时反馈
    """
    
    def __init__(self, ui_callback: Optional[Callable] = None):
        self.ui_callback = ui_callback
        
        # 对话状态: idle, listening, processing, speaking
        self.state = "idle"
        
        # 实时识别文本
        self.realtime_text = ""
        
        # 对话历史记录
        self.conversation_log = []
        
        # 线程锁
        self.lock = threading.Lock()
    
    def update_state(self, new_state: str):
        """更新对话状态并通知UI"""
        with self.lock:
            if self.state != new_state:
                old_state = self.state
                self.state = new_state
                print(f"状态变化: {old_state} → {new_state}")
                
                if self.ui_callback:
                    self.ui_callback("state_change", {
                        "old_state": old_state,
                        "new_state": new_state
                    })
    
    def get_state(self) -> str:
        """获取当前状态"""
        with self.lock:
            return self.state
    
    def add_realtime_text(self, text: str):
        """更新实时识别文本"""
        with self.lock:
            self.realtime_text = text
            
            if self.ui_callback:
                self.ui_callback("realtime_text", {
                    "text": text,
                    "is_final": False
                })
    
    def finalize_user_input(self, text: str):
        """确认用户输入并添加到历史"""
        with self.lock:
            # 清除实时文本
            self.realtime_text = ""
            
            # 添加到对话历史
            self.conversation_log.append({
                "role": "user",
                "content": text,
                "timestamp": self._get_timestamp()
            })
            
            if self.ui_callback:
                self.ui_callback("user_input", {
                    "text": text,
                    "is_final": True
                })
    
    def add_ai_response(self, text: str):
        """添加AI响应到历史"""
        with self.lock:
            self.conversation_log.append({
                "role": "assistant", 
                "content": text,
                "timestamp": self._get_timestamp()
            })
            
            if self.ui_callback:
                self.ui_callback("ai_response", {
                    "text": text
                })
    
    def add_system_message(self, message: str):
        """添加系统消息"""
        with self.lock:
            self.conversation_log.append({
                "role": "system",
                "content": message,
                "timestamp": self._get_timestamp()
            })
            
            if self.ui_callback:
                self.ui_callback("system_message", {
                    "text": message
                })
    
    def clear_conversation(self):
        """清除对话历史和实时文本"""
        with self.lock:
            self.conversation_log.clear()
            self.realtime_text = ""
            self.state = "idle"
            
            if self.ui_callback:
                self.ui_callback("conversation_cleared", {})
    
    def get_conversation_history(self) -> List[Dict]:
        """获取对话历史"""
        with self.lock:
            return self.conversation_log.copy()
    
    def get_realtime_text(self) -> str:
        """获取当前实时文本"""
        with self.lock:
            return self.realtime_text
    
    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        import datetime
        return datetime.datetime.now().strftime("%H:%M:%S") 