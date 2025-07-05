import pyaudio
import threading
import struct  # Python标准库，处理二进制数据
import time
class AudioPlayer:
    """
    独立音频播放器（纯Python实现，无C扩展依赖）
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
        """设置播放设备（功能不变）"""
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

    def _read_wav_header(self, file_path):
        """纯Python解析WAV文件头（不依赖任何C扩展）"""
        with open(file_path, 'rb') as f:
            # 解析WAV文件头（标准RIFF格式）
            riff = f.read(4)
            if riff != b'RIFF':
                raise ValueError("不是有效的WAV文件（RIFF标识缺失）")
            
            f.read(4)  # 文件大小
            wave = f.read(4)
            if wave != b'WAVE':
                raise ValueError("不是有效的WAV文件（WAVE标识缺失）")
            
            fmt = f.read(4)
            if fmt != b'fmt ':
                raise ValueError("WAV文件格式块缺失")
            
            # 读取格式块参数
            fmt_size = struct.unpack('<I', f.read(4))[0]
            audio_format = struct.unpack('<H', f.read(2))[0]
            channels = struct.unpack('<H', f.read(2))[0]
            sample_rate = struct.unpack('<I', f.read(4))[0]
            f.read(4)  # 字节率
            f.read(2)  # 块对齐
            bits_per_sample = struct.unpack('<H', f.read(2))[0]
            
            # 跳过额外的格式数据（如果有）
            if fmt_size > 16:
                f.read(fmt_size - 16)
            
            # 找到数据块
            while True:
                chunk_id = f.read(4)
                if not chunk_id:
                    raise ValueError("WAV文件数据块缺失")
                if chunk_id == b'data':
                    data_size = struct.unpack('<I', f.read(4))[0]
                    break
                else:
                    # 跳过非数据块
                    chunk_size = struct.unpack('<I', f.read(4))[0]
                    f.read(chunk_size)
        
        return {
            'channels': channels,
            'sample_rate': sample_rate,
            'bits_per_sample': bits_per_sample,
            'sample_width': bits_per_sample // 8,
            'data_start': f.tell()  # 数据块起始位置
        }

    def play_audio(self, audio_file, callback=None):
        if not self._pyaudio_initialized:
            print("❌ PyAudio未初始化，无法播放音频")
            if callback:
                callback(False, "PyAudio未初始化")
            return
        
        # ✅ 修复1：先把音频文件读入内存，避免文件被提前删除
        try:
            with open(audio_file, 'rb') as f:
                audio_data = f.read()  # 读入内存
            # 解析WAV头（用之前的纯Python解析逻辑）
            wav_info = self._read_wav_header_from_bytes(audio_data)
        except Exception as e:
            print(f"❌ 读取音频文件失败: {e}")
            if callback:
                callback(False, f"读取文件失败: {e}")
            return
        
        def _play():
            stream = None
            try:
                # ✅ 从内存解析参数，不再读文件
                sample_width = wav_info['sample_width']
                channels = wav_info['channels']
                rate = wav_info['sample_rate']
                data_start = wav_info['data_start']
                audio_bytes = audio_data[data_start:]  # 只取数据部分

                # 配置流
                format = self.p.get_format_from_width(sample_width)
                stream = self.p.open(
                    format=format,
                    channels=channels,
                    rate=rate,
                    output=True,
                    output_device_index=self.output_device_index
                )

                # ✅ 分块播放内存中的数据，不碰原文件
                chunk_size = self.CHUNK * sample_width * channels
                for i in range(0, len(audio_bytes), chunk_size):
                    chunk = audio_bytes[i:i+chunk_size]
                    if not chunk:
                        break
                    stream.write(chunk)
                
                # ✅ 确保流播放完成后再关闭
                time.sleep(0.1)
                if callback:
                    callback(True, None)
                    
            except Exception as e:
                print(f"播放音频时出错: {e}")
                if callback:
                    callback(False, str(e))
            finally:
                if stream:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception as e:
                        print(f"⚠️ 关闭播放流时出错: {e}")
        
        thread = threading.Thread(target=_play, daemon=True)
        thread.start()

# ✅ 新增：从字节数据解析WAV头（不用读文件）
    def _read_wav_header_from_bytes(self, audio_bytes):
        import io
        f = io.BytesIO(audio_bytes)
        # 复用之前的_read_wav_header逻辑，只是把文件句柄换成BytesIO
        riff = f.read(4)
        if riff != b'RIFF':
            raise ValueError("不是有效的WAV文件（RIFF标识缺失）")
        f.read(4)
        wave = f.read(4)
        if wave != b'WAVE':
            raise ValueError("不是有效的WAV文件（WAVE标识缺失）")
        fmt = f.read(4)
        if fmt != b'fmt ':
            raise ValueError("WAV文件格式块缺失")
        fmt_size = struct.unpack('<I', f.read(4))[0]
        audio_format = struct.unpack('<H', f.read(2))[0]
        channels = struct.unpack('<H', f.read(2))[0]
        sample_rate = struct.unpack('<I', f.read(4))[0]
        f.read(4)
        f.read(2)
        bits_per_sample = struct.unpack('<H', f.read(2))[0]
        if fmt_size > 16:
            f.read(fmt_size - 16)
        while True:
            chunk_id = f.read(4)
            if not chunk_id:
                raise ValueError("WAV文件数据块缺失")
            if chunk_id == b'data':
                data_size = struct.unpack('<I', f.read(4))[0]
                break
            else:
                chunk_size = struct.unpack('<I', f.read(4))[0]
                f.read(chunk_size)
        return {
            'channels': channels,
            'sample_rate': sample_rate,
            'bits_per_sample': bits_per_sample,
            'sample_width': bits_per_sample // 8,
            'data_start': f.tell()
        }

    def list_output_devices(self):
        """列出可用的输出设备（功能不变）"""
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
        """析构函数，清理PyAudio资源（功能不变）"""
        try:
            if hasattr(self, '_pyaudio_initialized') and self._pyaudio_initialized:
                if hasattr(self, 'p') and self.p:
                    self.p.terminate()
                    self._pyaudio_initialized = False
        except Exception as e:
            print(f"⚠️ AudioPlayer清理资源时出错: {e}")
