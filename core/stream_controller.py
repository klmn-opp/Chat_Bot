import threading
import os
import time
from datetime import datetime
from typing import Callable, Optional
from core.audio_stream import AudioStreamProcessor
from core.chat import ChatBot
from core.tts import TextToSpeech
from ui.components.audio_player import AudioPlayer
from core.motion_analyzer import MotionAnalyzer


# 注意：这里不再需要 import rclpy，避免版本冲突

class StreamController:
    """
    流式控制器
    统一管理音频流、AI对话、TTS的控制器
    将三个独立组件串联成完整的对话流程
    """
    
    def __init__(self, 
                 server_host="localhost",
                 server_port=9090,
                 input_device_index=2,
                 output_device_index=None):
        
        # 初始化核心组件
        self.audio_stream = AudioStreamProcessor(
            server_host=server_host,
            server_port=server_port,
            language="zh",
            input_device_index=input_device_index,
            output_device_index=output_device_index
        )
        self.chat_bot = ChatBot()
        self.tts = TextToSpeech(audio_stream=self.audio_stream, audio_player=None)
        self.audio_player = AudioPlayer(output_device_index=output_device_index)
        self.motion_analyzer = MotionAnalyzer()
        
        # 线程锁（保护共享状态）
        self._lock = threading.Lock()  # 用于保护共享状态的锁
        self._state_lock = threading.Lock()  # 专门用于保护对话状态的锁
        # 语言配置
        self.languages = {
            "粤语": {"whisper": "yue", "tts": "zh-HK-HiuGaaiNeural"},
            "普通话": {"whisper": "zh", "tts": "zh-CN-XiaoxiaoNeural"},
            "英语": {"whisper": "en", "tts": "en-US-JennyNeural"}
        }
        self.current_language = "普通话"
        
        # 状态管理
        self.conversation_state = "listening"  # idle, listening, processing, speaking
        self.current_transcription = ""
        
        # 回调函数
        self.on_state_change: Optional[Callable] = None
        self.on_transcription_update: Optional[Callable] = None
        self.on_final_result: Optional[Callable] = None
        self.on_ai_response: Optional[Callable] = None
        self.on_error: Optional[Callable] = None
        
        # 系统提示词
        self.system_prompt = ""
        self._load_system_prompt()
        
        # 对话日志相关
        self.log_dir = "conversation_logs"
        os.makedirs(self.log_dir, exist_ok=True)
        self.session_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file_path = os.path.join(self.log_dir, "reply.txt")
        self.current_user_text = ""
        
        # 设置音频流回调
        self._setup_audio_callbacks()
        
        print("🎯 流式控制器初始化完成 (ROS控制已切换至命令行模式)")

    def _load_system_prompt(self):
        """加载系统提示词"""
        try:
            with open("configs/system_prompt.txt", "r", encoding="utf-8") as f:
                self.system_prompt = f.read()
        except Exception as e:
            print(f"加载系统提示词失败: {e}")
            self.system_prompt = "你是一个医疗机器人助手。你可以做比如挥手，拥抱等的动作，你在回复我的时候，可以根据你回复的内容，多说一句比如“我们来握手吧”之类的话。"

    def _setup_audio_callbacks(self):
        """设置音频流回调"""
        self.audio_stream.set_transcription_callback(self._on_transcription_update)
        self.audio_stream.set_final_callback(self._on_final_transcription)
        self.audio_stream.set_error_callback(self._on_audio_error)

    def _save_conversation_to_file(self, user_text: str, ai_response: str):
        """保存对话到本地文件"""
        try:
            conversation_content = f"\n用户: {user_text}\nAI: {ai_response}\n"
            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(conversation_content)
            print(f"✅ 对话已保存到: {self.log_file_path}")
        except Exception as e:
            print(f"❌ 保存对话日志失败: {e}")

    def _on_ai_response_received(self, success: bool, response: str = None, error: str = None):
        """关键修改：状态更新加锁+异常兜底+多分句多动作执行+动作去重"""
        # 新增线程锁（需在__init__中定义self._state_lock = threading.Lock()）
        with self._state_lock:
            if success and response:
                print(f"\n\n💬 AI响应: {response}", flush=True)
                
                # ========== 核心修改：多分句多动作执行+去重逻辑 ==========
                def run_motion_bridge():
                    try:
                        # 1. 按句号拆分AI回复（兼容中文/英文句号）
                        sentences = response.replace("。", "|").replace("，", "|").replace(".", "|").replace(",", "|").replace("?", "|").replace("？", "|").split("|")
                        # 清洗空句子和空白字符
                        valid_sentences = [s.strip() for s in sentences if s.strip()]
                        
                        if not valid_sentences:
                            print(f"⚠️ 动作执行失败: AI回复拆分后无有效句子", flush=True)
                            return
                        
                        print(f"🤖 [Motion Control] AI回复拆分出 {len(valid_sentences)} 个有效句子，开始逐个匹配动作...")
                        
                        # 新增：记录上一句的动作（用于去重）
                        last_action = None
                        
                        # 2. 逐个句子匹配动作并发送ROS2指令
                        for idx, sentence in enumerate(valid_sentences, 1):
                            YELLOW = "\033[33m"
                            RESET = "\033[0m"
                            print(f"\n🤖 [Motion Control] 处理第{idx}句：{YELLOW}{sentence}{RESET}")
                            # 调用原有analyze_text（单句匹配单个动作）
                            matched_action = self.motion_analyzer.analyze_text(sentence)
                            
                            if matched_action:
                                # 核心判断：如果当前动作和上一句相同，跳过发送
                                print(f"matched_action: {matched_action}, last_action: {last_action}")  # 调试日志
                                if matched_action == last_action:
                                    print(f"⏭️ [Motion Control] 第{idx}句动作【{matched_action}】与上一句相同，跳过发送")
                                else:
                                    # 发送ROS2动作指令
                                    cmd = f'ros2 topic pub -1 /arm_command std_msgs/msg/String "{{data: \'{matched_action}\'}}" > /dev/null 2>&1'
                                    os.system(cmd) 
                                    RED = "\033[31m"
                                    RESET = "\033[0m"
                                    #matched_action = f"{RED}{matched_action}{RESET}"
                                    print(f"🚀 [Robot Control] 第{idx}句已发送动作指令: {RED}{matched_action}{RESET}", flush=True)
                                    # 更新上一句动作记录
                                    last_action = matched_action
                                    # 可选：动作执行间隔（避免指令发送过快）
                                    #time.sleep(0.5)
                            else:
                                print(f"⚠️ [Motion Control] 第{idx}句无匹配动作")
                                # 无匹配动作时，重置last_action（避免影响下一句）
                                last_action = None
                                
                    except Exception as e:
                        print(f"⚠️ 动作执行失败: {e}", flush=True)
                
                # ========== 保留原有线程调用逻辑 ==========
                threading.Thread(target=run_motion_bridge, daemon=True).start()

                # 原有流程：回调+保存对话
                if self.on_ai_response:
                    self.on_ai_response(response)
                self._save_conversation_to_file(self.current_user_text, response)
                
                # 强制更新状态为speaking（加锁保护）
                self.conversation_state = "speaking"
                self._update_state("speaking")
                print(f"📌 状态已更新为speaking，开始播报", flush=True)
                
                # 调用语音播报（加异常捕获）
                try:
                    self._speak_response(response)
                except Exception as e:
                    print(f"❌ 启动语音播报失败: {e}", flush=True)
                    self.conversation_state = "listening"  # 播报失败后回退到listening状态，允许继续对话
                    self._update_state("listening")
            else:
                print(f"❌ AI响应失败: {error}", flush=True)
                self.conversation_state = "listening"  # AI响应失败时回退到listening状态，允许继续对话
                self._update_state("listening")
    # --- 以下方法保持原有逻辑，不做改动 ---

    def set_language(self, language: str):
        if language in self.languages:
            self.current_language = language
            whisper_lang = self.languages[language]["whisper"]
            self.audio_stream.language = whisper_lang
            if self.on_state_change:
                self.on_state_change("language_changed", {"language": language})

    def set_devices(self, input_device_index: Optional[int], output_device_index: Optional[int]):
        if input_device_index is not None:
            self.audio_stream.set_input_device(input_device_index)
        if output_device_index is not None:
            self.audio_player.set_output_device(output_device_index)

    def start_conversation(self):
        """修改：彻底移除idle状态判断，点击开始直接启动持续录音"""
        try:
            # 强制设置为listening状态（仅用于标识，无实际判断作用）
            self.conversation_state = "listening"
            self._update_state("listening")
            
            # 清空历史转录结果
            self.current_transcription = ""
            self.current_user_text = ""
            
            # 启动音频流（不管之前状态，直接启动）
            if not self.audio_stream.is_streaming:
                self.audio_stream.is_running = True
                self.audio_stream.start_streaming()
            
            print("▶️  已启动持续录音+自动转录模式，等待语音输入...")
            return True
        except Exception as e:
            print(f"❌ 启动持续录音失败: {e}")
            # 即使失败，也设为listening（避免状态卡壳）
            self.conversation_state = "listening"
            self._update_state("listening")
            return False
        
    def stop_conversation(self):
        """修改：停止录音，状态仍设为listening（无idle）"""
        try:
            self.audio_stream.stop_streaming()
            # 停止后仍保留listening状态，方便下次直接转录
            self.conversation_state = "listening"
            self._update_state("listening")
            print("⏹️  已停止持续录音+自动转录")
            return True
        except Exception as e:
            print(f"❌ 停止持续录音失败: {e}")
            self.conversation_state = "listening"
            self._update_state("listening")
            return False
        

    def _on_transcription_update(self, text: str, is_final: bool = False):
        self.current_transcription = text
        if self.on_transcription_update:
            self.on_transcription_update(text, is_final)

    def _on_final_transcription(self, text: str):
        """修改：每次自动转录完成后，若有有效文本则触发AI对话"""
        if text.strip():
            # 记录本次转录结果
            self.current_user_text = text.strip()
            print(f"\n[stream_controller] 收到本次转录结果: {self.current_user_text}")

            self._process_final_text(text.strip())  # 调用原有逻辑，发给AI
            # 只有当前状态是listening时，才触发AI对话（避免重复触发）
            # if self.conversation_state == "listening":
                

            # else:
            #     print(f"⚠️ 当前状态不是listening，跳过AI调用: {self.conversation_state}")
        else:
            print("[stream_controller] 本次转录无有效文本，跳过AI调用")


    def _process_final_text(self, text: str):
        try:
            self._update_state("processing")
            if self.on_final_result: self.on_final_result(text)
            print(f"\n[StreamController] 发送给ai: {text}", flush=True)
            self.chat_bot.chat_with_ai(text, self.system_prompt, callback=self._on_ai_response_received)
        except Exception as e:
            self._update_state("listening")

    def _speak_response(self, text: str):
        print(f"📢 开始执行_tts", flush=True)
        try:
            # 1. TTS播报前暂停识别（直接调用audio_stream）
            self.audio_stream.pause_recognition()
            time.sleep(0.2)
            tts_voice = self.languages[self.current_language]["tts"]
            #print(f"[stream controller] 使用TTS语音包: {tts_voice}", flush=True)
            
            self.tts.before_tts_exec() 

            # 2. 给TTS设置播放用的audio_player
            self.tts.set_audio_player(self.audio_player)
            
            #print(f"[stream controller] 调用TTS.text_to_speech，文本长度: {len(text)}", flush=True)
            self.tts.text_to_speech(text, tts_voice, callback=self._on_tts_complete)
        except Exception as e:
            import traceback
            print(f"[stream controller] ❌ _speak_response执行异常: {e}", flush=True)
            print(f"[stream controller] 📜 异常栈: {traceback.format_exc()}", flush=True)
            # 异常时恢复识别
            self.audio_stream.resume_recognition()
            self._update_state("listening")


    def _on_tts_complete(self, success: bool, error: str = None):
        try:
            print(f"🔍 TTS兜底回调触发: success={success}, error={error}")
            # ✅ 移除所有直接操作 audio_stream 的代码
            # 因为恢复逻辑已经在 TextToSpeech.py 的播放回调里做了一次
            # 这里只更新 Controller 自己的状态即可
            with self._state_lock:
                self.conversation_state = "listening"
                self._update_state("listening")
            print("✅ TTS回调完成，重置状态为listening")
        except Exception as e:
            print(f"❌ 回调恢复识别失败: {e}")


    def _on_audio_error(self, error: str):
        self._update_state("listening")

    def _update_state(self, new_state: str):
        if self.conversation_state != new_state:
            old_state = self.conversation_state
            self.conversation_state = new_state
            if self.on_state_change:
                self.on_state_change(new_state, {"old_state": old_state, "new_state": new_state})

    def clear_conversation_history(self):
        self.chat_bot.clear_history()

    def get_current_state(self) -> str:
        return self.conversation_state

    def list_audio_devices(self):
        return self.audio_stream.list_audio_devices()

    def set_state_change_callback(self, callback: Callable): self.on_state_change = callback
    def set_transcription_callback(self, callback: Callable): self.on_transcription_update = callback
    def set_final_result_callback(self, callback: Callable): self.on_final_result = callback
    def set_ai_response_callback(self, callback: Callable): self.on_ai_response = callback
    def set_error_callback(self, callback: Callable): self.on_error = callback