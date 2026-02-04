import os
import sys
# 强制定义PY_SSIZE_T_CLEAN宏，解决pyaudio兼容问题
if not os.environ.get('PY_SSIZE_T_CLEAN'):
    os.environ['PY_SSIZE_T_CLEAN'] = '1'
# 兼容Linux下的pyaudio加载
sys.setdlopenflags(sys.getdlopenflags() | 0x00000010)  # RTLD_GLOBAL
import asyncio
import edge_tts
import time
import tempfile
import uuid
import threading
from pathlib import Path

class TextToSpeech:
    def __init__(self, audio_processor=None):
        self.audio_processor = audio_processor
        # 确保temp目录存在
        self.temp_dir = Path("temp")
        self.temp_dir.mkdir(exist_ok=True)
        # 添加线程锁防止并发问题
        self._lock = threading.Lock()
        # 正在处理的TTS任务计数
        self._active_tasks = 0

    def set_audio_processor(self, audio_processor):
        """设置音频处理器，用于播放音频"""
        self.audio_processor = audio_processor

    def text_to_speech(self, text, voice, callback=None):
        """文字转语音，完成后调用callback"""
        # 检查是否有正在进行的TTS任务
        with self._lock:
            if self._active_tasks > 0:
                print(f"⚠️ 已有TTS任务在进行中，跳过新的TTS请求: {text[:20]}...")
                if callback:
                    callback(success=False, error="TTS任务冲突，已跳过")
                return
            self._active_tasks += 1
        
        async def _tts():
            unique_id = str(uuid.uuid4())[:8]
            try:
                print(f"🔊 开始TTS合成: {text[:30]}...")
                
                communicate = edge_tts.Communicate(
                    text,
                    voice
                )
                # 使用UUID生成唯一文件名
                temp_mp3_file = self.temp_dir / f"tts_{unique_id}.mp3"
                await communicate.save(str(temp_mp3_file))
                
                print(f"✅ TTS音频文件已生成: {temp_mp3_file}")
                
                # 检查文件是否真的存在
                if not temp_mp3_file.exists():
                    print(f"❌ TTS文件生成失败: {temp_mp3_file}")
                    if callback:
                        callback(success=False, error="TTS文件生成失败")
                    return
                
                # 转换MP3为标准WAV格式
                output_file = self.temp_dir / f"output_{unique_id}.wav"
                success = self._convert_mp3_to_wav(str(temp_mp3_file), str(output_file))
                
                if not success:
                    print("❌ 音频格式转换失败")
                    # 清理失败的文件
                    try:
                        temp_mp3_file.unlink()
                    except:
                        pass
                    if callback:
                        callback(success=False, error="音频格式转换失败")
                    return
                
                print(f"✅ 音频格式转换完成: {output_file}")
                
                # 清理临时MP3文件
                try:
                    temp_mp3_file.unlink()
                    print("🗑️ 临时MP3文件已清理")
                except Exception as e:
                    print(f"⚠️ 清理MP3文件失败: {e}")
                
                # 如果有音频处理器，使用它来播放音频
                if self.audio_processor:
                    print("🔊 使用音频处理器播放...")
                    # 使用AudioProcessor的play_audio方法
                    def on_play_complete(success, error=None):
                        # 播放完成后清理WAV文件
                        try:
                            if output_file.exists():
                                output_file.unlink()
                                print("🗑️ 输出音频文件已清理")
                        except Exception as e:
                            print(f"⚠️ 清理WAV文件失败: {e}")
                        
                        # 重置任务计数
                        with self._lock:
                            self._active_tasks = max(0, self._active_tasks - 1)
                        
                        if callback:
                            if success:
                                callback(success=True)
                            else:
                                callback(success=False, error=f"播放失败: {error}")
                    
                    self.audio_processor.play_audio(str(output_file), on_play_complete)
                else:
                    print("🔊 使用系统播放器...")
                    # 回退到系统播放命令
                    self._fallback_play(str(output_file), callback, output_file, unique_id)
                    
            except Exception as e:
                print(f"❌ TTS过程错误: {e}")
                # 重置任务计数
                with self._lock:
                    self._active_tasks = max(0, self._active_tasks - 1)
                if callback:
                    callback(success=False, error=str(e))
        
        asyncio.run(_tts())

    def _convert_mp3_to_wav(self, mp3_file, wav_file):
        """将MP3文件转换为标准WAV格式"""
        try:
            # 检查输入文件是否存在
            if not os.path.exists(mp3_file):
                print(f"❌ 输入文件不存在: {mp3_file}")
                return False
            
            print(f"🔄 开始音频格式转换: {os.path.basename(mp3_file)} -> {os.path.basename(wav_file)}")
            
            # 使用pydub进行音频格式转换
            try:
                from pydub import AudioSegment
                
                # 读取MP3文件
                audio = AudioSegment.from_mp3(mp3_file)
                
                # 导出为标准WAV格式（16位，单声道或立体声，44.1kHz）
                audio.export(wav_file, format="wav")
                
                print("✅ 音频格式转换成功")
                return True
                
            except ImportError:
                print("⚠️ pydub未安装，尝试使用ffmpeg...")
                # 如果pydub不可用，尝试使用ffmpeg
                result = os.system(f"ffmpeg -i '{mp3_file}' -y '{wav_file}' >/dev/null 2>&1")
                if result == 0:
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
                
                # 重置任务计数
                with self._lock:
                    self._active_tasks = max(0, self._active_tasks - 1)
                    
                if callback:
                    if result == 0:
                        print("✅ 系统播放成功")
                        callback(success=True)
                    else:
                        print("❌ 系统播放失败")
                        callback(success=False, error="系统播放命令执行失败")
                        
            except Exception as e:
                print(f"❌ 系统播放错误: {e}")
                # 重置任务计数
                with self._lock:
                    self._active_tasks = max(0, self._active_tasks - 1)
                if callback:
                    callback(success=False, error=str(e))
        
        # 在新线程中执行系统播放
        thread = threading.Thread(target=_system_play, daemon=True)
        thread.start() 
