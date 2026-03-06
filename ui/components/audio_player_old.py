import pyaudio
import wave
import threading

class AudioPlayer:
    """
    独立音频播放器
    从传统AudioProcessor中提取播放功能，专门负责TTS音频播放
    """
    
    def __init__(self, output_device_index=None):
        try:
            self.p = pyaudio.PyAudio()
            self._pyaudio_initialized = True
        except Exception as e:
            print(f"❌ AudioPlayer PyAudio初始化失败: {e}")
            self.p = None
            self._pyaudio_initialized = False
            
        self.output_device_index = output_device_index
        self.CHUNK = 2048
        self._lock = threading.Lock()
        
    def set_output_device(self, device_index):
        """设置播放设备"""
        if not self._pyaudio_initialized:
            return False
            
        try:
            device_info = self.p.get_device_info_by_index(device_index)
            if device_info['maxOutputChannels'] > 0:
                with self._lock:
                    self.output_device_index = device_index
                print(f"播放设备已设置为: {device_info['name']}")
                return True
            else:
                print(f"错误: 设备 {device_index} 不支持播放")
                return False
        except Exception as e:
            print(f"设置播放设备失败: {e}")
            return False

    def play_audio(self, audio_file, callback=None):
        """播放音频文件"""
        if not self._pyaudio_initialized:
            print("❌ PyAudio未初始化，无法播放音频")
            if callback:
                callback(False, "PyAudio未初始化")
            return
            
        def _play():
            stream = None
            try:
                # 使用wave库读取WAV文件
                with wave.open(audio_file, 'rb') as wf:
                    # 获取音频参数
                    sample_width = wf.getsampwidth()
                    channels = wf.getnchannels()
                    rate = wf.getframerate()

                    # 配置PyAudio流
                    stream = self.p.open(
                        format=self.p.get_format_from_width(sample_width),
                        channels=channels,
                        rate=rate,
                        output=True,
                        output_device_index=self.output_device_index
                    )

                    # 分块读取并播放音频
                    data = wf.readframes(self.CHUNK)
                    while data:
                        stream.write(data)
                        data = wf.readframes(self.CHUNK)
                
                if callback:
                    callback(True)
                    
            except Exception as e:
                print(f"播放音频时出错: {e}")
                if callback:
                    callback(False, str(e))
            finally:
                # 确保关闭音频流
                if stream:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception as e:
                        print(f"⚠️ 关闭播放流时出错: {e}")
        
        # 在新线程中播放以避免阻塞
        thread = threading.Thread(target=_play, daemon=True)
        thread.start()

    def list_output_devices(self):
        """列出可用的输出设备"""
        if not self._pyaudio_initialized:
            return []
            
        output_devices = []
        device_count = self.p.get_device_count()
        
        for i in range(device_count):
            try:
                device_info = self.p.get_device_info_by_index(i)
                if device_info['maxOutputChannels'] > 0:
                    output_devices.append({
                        'index': i, 
                        'name': device_info['name']
                    })
            except Exception as e:
                print(f"⚠️ 获取播放设备{i}信息失败: {e}")
        
        return output_devices

    def __del__(self):
        """析构函数，清理PyAudio资源"""
        try:
            if hasattr(self, '_pyaudio_initialized') and self._pyaudio_initialized:
                if hasattr(self, 'p') and self.p:
                    self.p.terminate()
                    self._pyaudio_initialized = False
        except Exception as e:
            print(f"⚠️ AudioPlayer清理资源时出错: {e}") 