import os
import sys
import queue
# 强制定义PY_SSIZE_T_CLEAN宏，解决pyaudio兼容问题
if not os.environ.get('PY_SSIZE_T_CLEAN'):
    os.environ['PY_SSIZE_T_CLEAN'] = '1'
# 兼容Linux下的pyaudio加载
try:
    if sys.platform == 'linux':
        sys.setdlopenflags(sys.getdlopenflags() | 0x00000010)  # RTLD_GLOBAL
except:
    pass

import asyncio
import edge_tts
import time
import tempfile
import uuid
import threading
from pathlib import Path

class TextToSpeech:
    def __init__(self, audio_stream=None,audio_player=None):  # 改参数名，更清晰
        self.audio_player = audio_player  # 专门用于播放音频
        self.audio_stream = audio_stream  # 专门用于暂停/恢复识别
        # 确保temp目录存在
        self.temp_dir = Path("temp")
        self.temp_dir.mkdir(exist_ok=True)
        # 添加线程锁防止并发问题
        self._lock = threading.Lock()
        # 正在处理的TTS任务计数
        self._active_tasks = 0
        # 新增：TTS请求队列（缓存待处理的请求）
        self._tts_queue = queue.Queue()

    # 新增：分别设置播放和识别对象
    def set_audio_player(self, audio_player):
        """设置音频播放器（用于播放TTS音频）"""
        self.audio_player = audio_player

    def set_audio_stream(self, audio_stream):
        """设置音频流处理器（用于暂停/恢复语音识别）"""
        self.audio_stream = audio_stream
        
    def before_tts_exec(self):
        """TTS 执行前的内存保护"""
        # 3. 强制垃圾回收，释放未引用的内存
        import gc
        gc.collect()
        print("✅ TTS执行前内存保护完成，无残留音频流资源")
    
    def _complete_task_and_check_queue(self):
        """任务完成后重置计数，并检查队列是否有新任务需要执行"""
        print("🔄 TTS任务完成，检查队列中是否有等待的任务...", flush=True)
        with self._lock:
            self._active_tasks = max(0, self._active_tasks - 1)
            
            # 检查队列是否有等待的任务
            if not self._tts_queue.empty():
                print(f"📋 队列中有等待的TTS请求，准备执行下一个任务 (当前活跃任务数: {self._active_tasks})", flush=True)
                # 取出队列第一个任务
                try:
                    next_request = self._tts_queue.get_nowait()
                    print(f"▶️ 从队列中取出下一个TTS请求: {next_request['text'][:20]}... (剩余队列长度: {self._tts_queue.qsize()})", flush=True)
                    
                    # 核心修复：不用递归，新开线程执行下一个TTS（避免asyncio事件循环阻塞）
                    def run_next_tts():
                        self.text_to_speech(
                            text=next_request["text"],
                            voice=next_request["voice"],
                            callback=next_request["callback"]
                        )
                    # 新开守护线程执行，避免阻塞当前流程
                    print("⏳ 准备执行下一个TTS请求，稍等片刻...", flush=True)
                    time.sleep(0.5)  # 短暂延迟
                    threading.Thread(target=run_next_tts, daemon=True, name="NextTTSWorker").start()
                    
                    print(f"▶️ 已启动新线程执行队列中的下一个TTS请求: {next_request['text'][:20]}... (剩余队列长度: {self._tts_queue.qsize()})", flush=True)
                except queue.Empty:
                    pass
            else:
                print(f"🔄 TTS任务完成,请继续输入...", flush=True)

    def text_to_speech(self, text, voice, callback=None):
        # 封装请求参数
        request = {
            "text": text,
            "voice": voice,
            "callback": callback,
            "retry_count": 0  # 新增：重试计数器
        }
        print(f"[tts] 收到TTS请求:text:{text[:10]}", flush=True)
        with self._lock:
            # 检查是否有活跃任务
            if self._active_tasks > 0:
                # 有活跃任务 → 加入队列
                self._tts_queue.put(request)
                print(f"[tts] TTS请求已入队等待: {text[:10]}... (队列当前长度: {self._tts_queue.qsize()})", flush=True)
                return
            # 无活跃任务 → 直接执行
            self._active_tasks += 1
        
        # 核心修改：把异步TTS合成放到后台线程
        def _tts_worker():
            async def _tts():
                unique_id = str(uuid.uuid4())[:8]
                max_retries = 3  # 最大重试次数
                retry_delay = 2.0  # 初始重试延迟（秒）
                
                for attempt in range(max_retries):
                    temp_mp3_file = None
                    try:
                        # 如果是重试，先等待退避时间
                        if attempt > 0:
                            print(f"🔄 TTS第{attempt}次重试，等待{retry_delay}秒...", flush=True)
                            await asyncio.sleep(retry_delay)
                            retry_delay += 2  # 增加退避时间，避免频繁重试
                        
                        tts_start_time = time.time()
                        print(f"[tts] 开始TTS合成 (尝试 {attempt+1}/{max_retries}): {text[:30]}...", flush=True)
                        
                        communicate = edge_tts.Communicate(text, voice)
                        temp_mp3_file = self.temp_dir / f"tts_{unique_id}.mp3"
                        
                        await communicate.save(str(temp_mp3_file))
                        
                        if not temp_mp3_file.exists():
                            print(f"❌ TTS文件生成失败: {temp_mp3_file}", flush=True)
                            if attempt == max_retries - 1 and callback:
                                callback(success=False, error="TTS文件生成失败")
                            continue
                        
                        output_file = self.temp_dir / f"output_{unique_id}.wav"
                        success = self._convert_mp3_to_wav(str(temp_mp3_file), str(output_file))
                        
                        # 清理MP3
                        try:
                            if temp_mp3_file.exists():
                                temp_mp3_file.unlink()
                        except:
                            pass
                            
                        if not success:
                            if attempt == max_retries - 1 and callback:
                                callback(success=False, error="音频格式转换失败")
                            continue

                        tts_end_time = time.time()
                        tts_cost = tts_end_time - tts_start_time

                        GREEN = "\033[32m"
                        YELLOW = "\033[33m"
                        RED = "\033[31m"
                        RESET = "\033[0m"
                        
                        if tts_cost < 1.0:
                            colored_num = f"{GREEN}{tts_cost * 1000:.2f}{RESET}"
                        elif 1.0 <= tts_cost <= 2.5:
                            colored_num = f"{YELLOW}{tts_cost * 1000:.2f}{RESET}"
                        else:
                            colored_num = f"{RED}{tts_cost * 1000:.2f}{RESET}"

                        print(f"[tts] TTS合成并转换成功，耗时: {colored_num} ms", flush=True)

                        # 播放逻辑
                        if self.audio_player:
                            def on_play_complete(success, error=None):
                                try:
                                    print(f"🔍 TTS播放回调触发: success={success}, error={error}")
                                    try:
                                        if output_file.exists():
                                            output_file.unlink()
                                            print(f"🗑️ 已删除临时音频文件: {output_file}")
                                    except:
                                        pass
                                    
                                    if self.audio_stream:
                                        print(f"🔍 准备恢复语音识别: audio_stream={self.audio_stream}")
                                        time.sleep(0.1)
                                        self.audio_stream.resume_recognition()
                                        
                                except Exception as e:
                                    print(f"❌ 播放完成回调异常: {e}", flush=True)
                                finally:
                                    self._complete_task_and_check_queue()
                                    if callback:
                                        callback(success=success, error=error)
                            
                            self.audio_player.play_audio(str(output_file), on_play_complete)
                        else:
                            self._fallback_play(str(output_file), callback, output_file, unique_id)
                        
                        return  # 成功，直接退出重试循环
                        
                    except Exception as e:
                        print(f"❌ TTS过程错误 (尝试 {attempt+1}/{max_retries}): {e}", flush=True)
                        if attempt == max_retries - 1:
                            import traceback
                            print(f"📜 TTS最终异常栈: {traceback.format_exc()}", flush=True)
                            
                            # 最终失败后的兜底恢复
                            if self.audio_stream:
                                try:
                                    print("🔊 TTS最终失败，兜底恢复语音识别")
                                    self.audio_stream.resume_recognition()
                                except:
                                    pass
                            
                            self._complete_task_and_check_queue()
                            if callback:
                                callback(success=False, error=str(e))
            
            # 执行异步TTS
            asyncio.run(_tts())
        
        # 启动后台线程执行TTS
        threading.Thread(target=_tts_worker, daemon=True, name="TTSWorker").start()

    def _convert_mp3_to_wav(self, mp3_file, wav_file):
        """将MP3文件转换为标准WAV格式"""
        try:
            # 检查输入文件是否存在
            if not os.path.exists(mp3_file):
                print(f"❌ 输入文件不存在: {mp3_file}")
                return False
            
            # 使用pydub进行音频格式转换
            try:
                from pydub import AudioSegment
                audio = AudioSegment.from_mp3(mp3_file)
                audio.export(wav_file, format="wav")
                return True
            except ImportError:
                print("⚠️ pydub未安装，尝试使用ffmpeg...")
                tts_start_time = time.time()
                result = os.system(f"ffmpeg -i '{mp3_file}' -y '{wav_file}' >/dev/null 2>&1")
                
                if result == 0:
                    tts_end_time = time.time()
                    tts_cost = tts_end_time - tts_start_time
                    print(f"⏱️ tts音频格式转换耗时: {round(tts_cost * 1000, 2)} ms")
                    print("✅ ffmpeg转换成功")
                    return True
                else:
                    print("❌ ffmpeg转换失败")
                    return False
                    
        except Exception as e:
            print(f"❌ 音频格式转换错误: {e}")
            return False

    def _fallback_play(self, audio_file, callback, output_file_path, unique_id):
        """回退播放方法"""
        def _system_play():
            try:
                # 根据系统选择播放命令
                import platform
                system = platform.system()
                
                print(f"🔊 使用系统播放器播放: {os.path.basename(audio_file)}")
                
                if system == "Darwin":  # macOS
                    result = os.system(f"afplay '{audio_file}'")
                elif system == "Linux":
                    result = os.system(f"aplay '{audio_file}' || paplay '{audio_file}' || mplayer '{audio_file}'")
                elif system == "Windows":
                    result = os.system(f"start /wait '{audio_file}'")
                else:
                    result = 1
                
                # 播放完成后清理文件
                try:
                    if output_file_path.exists():
                        output_file_path.unlink()
                        print("🗑️ 系统播放完成，文件已清理")
                except Exception as e:
                    print(f"⚠️ 清理文件失败: {e}")
                
                # 核心修改：替换原来的计数重置，调用新方法
                self._complete_task_and_check_queue()
                
                # 恢复识别
                if self.audio_stream:
                    self.audio_stream.resume_recognition()
                
                if callback:
                    if result == 0:
                        print("✅ 系统播放成功")
                        callback(success=True)
                    else:
                        print("❌ 系统播放失败")
                        callback(success=False, error="系统播放命令执行失败")
                        
            except Exception as e:
                print(f"❌ 系统播放错误: {e}")
                # 异常时也调用新方法
                self._complete_task_and_check_queue()
                # 恢复识别
                if self.audio_stream:
                    self.audio_stream.resume_recognition()
                if callback:
                    callback(success=False, error=str(e))
        
        # 在新线程中执行系统播放
        thread = threading.Thread(target=_system_play, daemon=True)
        thread.start()
