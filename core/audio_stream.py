#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
基于本地Whisper的音频流处理器
使用本地Whisper模型进行语音识别，避免网络依赖
"""

import pyaudio
import numpy as np
import threading
import time
import tempfile
import os
import wave
from typing import Callable, Optional, Dict, List
import whisper

class AudioStreamProcessor:
    """
    音频流处理器 - 基于本地Whisper
    提供实时音频捕获、本地语音识别和设备管理功能
    """
    
    def __init__(self, 
                 server_host=None,  # 保留兼容性，但不使用
                 server_port=None,  # 保留兼容性，但不使用
                 language="zh",
                 input_device_index=9,
                 output_device_index=None):
        """
        初始化音频流处理器
        
        Args:
            server_host: 保留兼容性（不使用）
            server_port: 保留兼容性（不使用）
            language: 识别语言
            input_device_index: 录音设备索引
            output_device_index: 播放设备索引（保留兼容性）
        """
        self.language = language
        self.input_device_index = 9
        self.output_device_index = output_device_index
        
        # 音频参数
        self.CHUNK = 2048
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 16000
        
        # 初始化PyAudio (添加错误处理)
        try:
            self.p = pyaudio.PyAudio()
            self._pyaudio_initialized = True
        except Exception as e:
            print(f"❌ PyAudio初始化失败: {e}")
            self.p = None
            self._pyaudio_initialized = False
        
        # 录音状态
        self.stream = None
        self.is_streaming = False
        self.audio_data = []
        
        # 添加线程锁
        self._lock = threading.Lock()
        self._recording_thread = None
        
        # Whisper模型
        self.whisper_model = None
        self._load_whisper_model()
        
        # 回调函数
        self.on_transcription = None
        self.on_final_transcription = None
        self.on_error = None
        
        print("✅ 本地Whisper音频流处理器初始化完成")
    
    def _load_whisper_model(self):
        """加载Whisper模型"""
        try:
            print("🔄 加载Whisper模型...")
            # 使用较小的模型以获得更快的响应速度
            self.whisper_model = whisper.load_model("base")
            print("✅ Whisper模型加载完成")
        except Exception as e:
            print(f"❌ Whisper模型加载失败: {e}")
            if self.on_error:
                self.on_error(f"模型加载失败: {e}")
    
    def set_transcription_callback(self, callback: Callable):
        """设置实时转录回调"""
        self.on_transcription = callback
    
    def set_final_callback(self, callback: Callable):
        """设置最终结果回调"""  
        self.on_final_transcription = callback
    
    def set_error_callback(self, callback: Callable):
        """设置错误回调"""
        self.on_error = callback
    
    def list_audio_devices(self):
        """列出可用的音频设备"""
        if not self._pyaudio_initialized:
            print("❌ PyAudio未初始化")
            return [], []
            
        device_count = self.p.get_device_count()
        input_devices = []
        output_devices = []
        
        for i in range(device_count):
            try:
                device_info = self.p.get_device_info_by_index(i)
                device_name = device_info['name']
                max_input_channels = device_info['maxInputChannels']
                max_output_channels = device_info['maxOutputChannels']
                
                print(f"设备 {i}: {device_name}")
                print(f"  - 最大输入声道: {max_input_channels}")
                print(f"  - 最大输出声道: {max_output_channels}")
                
                if max_input_channels > 0:
                    input_devices.append({'index': i, 'name': device_name})
                    print(f"  - [可用于录音]")
                
                if max_output_channels > 0:
                    output_devices.append({'index': i, 'name': device_name})
                    print(f"  - [可用于播放]")
                print()
            except Exception as e:
                print(f"⚠️ 获取设备{i}信息失败: {e}")
        
        return input_devices, output_devices

    def set_input_device(self, device_index):
        """设置录音设备"""
        if not self._pyaudio_initialized:
            return False
            
        try:
            device_info = self.p.get_device_info_by_index(device_index)
            if device_info['maxInputChannels'] > 0:
                with self._lock:
                    self.input_device_index = device_index
                print(f"录音设备已设置为: {device_info['name']}")
                return True
            else:
                print(f"错误: 设备 {device_index} 不支持录音")
                return False
        except Exception as e:
            print(f"设置录音设备失败: {e}")
            return False

    def set_output_device(self, device_index):
        """设置播放设备（保留兼容性）"""
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

    def start_streaming(self):
        """开始音频流式传输"""
        with self._lock:
            if self.is_streaming:
                print("音频流已经在运行中")
                return False
            
            if not self._pyaudio_initialized:
                print("❌ PyAudio未初始化")
                if self.on_error:
                    self.on_error("PyAudio未初始化")
                return False
        
            if not self.whisper_model:
                print("❌ Whisper模型未加载")
                if self.on_error:
                    self.on_error("Whisper模型未加载")
                return False
        
            try:
                # 配置音频流
                stream_kwargs = {
                    'format': self.FORMAT,
                    'channels': self.CHANNELS,
                    'rate': self.RATE,
                    'input': True,
                    'frames_per_buffer': self.CHUNK
                }
                
                if self.input_device_index is not None:
                    stream_kwargs['input_device_index'] = self.input_device_index
                    print(f"🎤 使用指定设备: {self.input_device_index}")
                    
                    # 验证设备是否可用
                    try:
                        device_info = self.p.get_device_info_by_index(self.input_device_index)
                        print(f"📱 设备信息: {device_info['name']}")
                        print(f"   - 最大输入声道: {device_info['maxInputChannels']}")
                        print(f"   - 默认采样率: {device_info['defaultSampleRate']}")
                        
                        if device_info['maxInputChannels'] == 0:
                            print("❌ 选择的设备不支持录音")
                            if self.on_error:
                                self.on_error("选择的设备不支持录音")
                            return False
                    except Exception as e:
                        print(f"❌ 无法获取设备信息: {e}")
                        if self.on_error:
                            self.on_error(f"设备信息获取失败: {e}")
                        return False
                else:
                    self.input_device_index = 7
                    stream_kwargs['input_device_index'] = 7
                    print(f"🎤 系统默认设备不可用，强制使用设备: {self.input_device_index}")
                   # print("🎤 使用系统默认录音设备")
                
                print(f"🔧 音频流参数: {stream_kwargs}")
                self.stream = self.p.open(**stream_kwargs)
                
                # 测试音频流是否正常工作
                try:
                    print("🧪 测试音频流可用性...")
                    test_chunk = self.stream.read(self.CHUNK, exception_on_overflow=False)
                    print(f"✅ 测试成功，读取到 {len(test_chunk)} 字节数据")
                except Exception as e:
                    print(f"❌ 音频流测试失败: {e}")
                    self.stream.close()
                    self.stream = None
                    if self.on_error:
                        self.on_error(f"音频流测试失败，可能是权限问题: {e}")
                    return False
                
                self.is_streaming = True
                self.audio_data = []
                
                print("🎤 开始实时音频流...")
                
                # 在新线程中开始录音
                self._recording_thread = threading.Thread(target=self._start_recording, daemon=True)
                self._recording_thread.start()
                
                return True
                
            except Exception as e:
                print(f"❌ 启动音频流失败: {e}")
                print(f"   - 错误类型: {type(e).__name__}")
                print(f"   - 可能原因: 设备占用、权限不足或参数不兼容")
                self.is_streaming = False
                if self.on_error:
                    self.on_error(f"启动失败: {e}")
                return False

    def _start_recording(self):
        """开始录音（在后台线程中运行）"""
        try:
            print("🔄 开始录音...")
            print(f"🎤 录音参数: CHUNK={self.CHUNK}, RATE={self.RATE}, 设备={self.input_device_index}")
            
            if not self.stream:
                print("❌ 音频流未创建")
                if self.on_error:
                    self.on_error("音频流未创建")
                return
            
            chunk_count = 0
            while self.is_streaming and self.stream:
                try:
                    # 读取音频数据
                    audio_chunk = self.stream.read(self.CHUNK, exception_on_overflow=False)
                    chunk_count += 1
                    
                    # 检查读取的数据
                    if len(audio_chunk) == 0:
                        print("⚠️ 读取到空音频数据")
                        continue
                    
                    with self._lock:
                        if self.is_streaming:  # 双重检查
                            self.audio_data.append(audio_chunk)
                    
                    # 每50个chunk输出一次状态
                    if chunk_count % 50 == 0:
                        print(f"📊 已录制 {chunk_count} 个音频块，总数据: {len(self.audio_data)}")
                    
                    # 实时反馈（可选，显示录音进度）
                    if self.on_transcription:
                        # 可以显示录音状态或者进行实时处理
                        self.on_transcription("正在录音...", False)
                    
                except Exception as e:
                    print(f"❌ 录音数据读取错误: {e}")
                    print(f"   - 错误类型: {type(e).__name__}")
                    print(f"   - 已读取块数: {chunk_count}")
                    if self.on_error:
                        self.on_error(f"录音读取错误: {e}")
                    break
                    
        except Exception as e:
            print(f"❌ 录音过程错误: {e}")
            print(f"   - 错误类型: {type(e).__name__}")
            if self.on_error:
                self.on_error(f"录音错误: {e}")
        finally:
            print(f"🔄 录音线程结束，共录制 {len(self.audio_data) if hasattr(self, 'audio_data') else 0} 个音频块")

    def stop_streaming(self):
        """停止音频流传输并进行语音识别"""
        with self._lock:
            if not self.is_streaming:
                print("音频流未在运行")
                return True
            
            print("🛑 停止音频流...")
            self.is_streaming = False
        
        try:
            # 等待录音线程结束
            if self._recording_thread and self._recording_thread.is_alive():
                self._recording_thread.join(timeout=2.0)
            
            # 安全关闭音频流
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except Exception as e:
                    print(f"⚠️ 关闭音频流时出错: {e}")
                finally:
                    self.stream = None
            
            # 处理录音数据
            with self._lock:
                audio_data_copy = self.audio_data.copy()
                self.audio_data = []
            
            if audio_data_copy:
                print("🔄 开始语音识别...")
                # 在新线程中进行识别，避免阻塞UI
                threading.Thread(target=self._process_audio_data, args=(audio_data_copy,), daemon=True).start()
            else:
                print("⚠️ 未检测到录音数据")
                if self.on_error:
                    self.on_error("未检测到录音数据")
            
            print("音频流已停止")
            return True
            
        except Exception as e:
            print(f"停止音频流失败: {e}")
            if self.on_error:
                self.on_error(f"停止失败: {e}")
            return False

    def _process_audio_data(self, audio_data):
        """处理录音数据并进行语音识别"""
        try:
            # 合并音频数据
            audio_bytes = b''.join(audio_data)
            
            if len(audio_bytes) == 0:
                print("⚠️ 音频数据为空")
                if self.on_error:
                    self.on_error("音频数据为空")
                return
            
            # 转换为numpy数组
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            
            # 检查音频长度
            if len(audio_np) < self.RATE * 0.5:  # 少于0.5秒
                print("⚠️ 音频时长过短")
                if self.on_error:
                    self.on_error("音频时长过短，请说话时间长一些")
                return
            
            # 进行语音识别
            print("🔄 正在进行语音识别...")
            
            # 设置识别选项
            options = {
                "language": self._map_language(),
                "task": "transcribe"
            }
            
            # 调用Whisper进行识别
            result = self.whisper_model.transcribe(audio_np, **options)
            
            # 提取识别文本
            text = result.get("text", "").strip()
            
            if text:
                print(f"📝 识别结果: {text}")
                if self.on_final_transcription:
                    self.on_final_transcription(text)
            else:
                print("⚠️ 未识别到有效语音")
                if self.on_error:
                    self.on_error("未识别到有效语音")
                    
        except Exception as e:
            print(f"语音识别错误: {e}")
            if self.on_error:
                self.on_error(f"识别错误: {e}")

    def _map_language(self):
        """映射语言代码"""
        language_map = {
            "粤语": "zh",
            "普通话": "zh", 
            "英语": "en"
        }
        return language_map.get(self.language, "zh")

    def set_language(self, language):
        """设置识别语言"""
        with self._lock:
            self.language = language
        print(f"语言已设置为: {language}")

    def __del__(self):
        """析构函数"""
        try:
            self.stop_streaming()
            if hasattr(self, '_pyaudio_initialized') and self._pyaudio_initialized:
                if hasattr(self, 'p') and self.p:
                    self.p.terminate()
                    self._pyaudio_initialized = False
        except Exception as e:
            print(f"⚠️ 清理资源时出错: {e}") 
