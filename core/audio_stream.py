#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
# 关键：强制 PyAudio 使用 PulseAudio 后端，和系统音频管理器兼容
os.environ['PYAUDIO_OUTPUT_DEVICE'] = 'pulse'
os.environ['PYAUDIO_INPUT_DEVICE'] = 'pulse'
# 禁用 ALSA 直接访问，避免状态冲突
os.environ['ALSA_NO_AUTOINCAPTURE'] = '1'

import pyaudio
import numpy as np
import threading
import time
import math
import ctypes
import traceback
from typing import Callable, Optional, Dict, List
import whisper

class AudioStreamProcessor:
    """
    音频流处理器 - 
    """
    def __init__(self, 
                 server_host=None,
                 server_port=None,
                 language="zh",
                 input_device_index=14,  # ✅ 
                 output_device_index=None):
        self.language = language
        self.output_device_index = output_device_index
        
        # 初始化PyAudio
        try:
            self.p = pyaudio.PyAudio()
            self._pyaudio_initialized = True
        except Exception as e:
            print(f"❌ PyAudio初始化失败: {e}")
            self.p = None
            self._pyaudio_initialized = False
            return
        
      
        self.input_device_index = 14
        print(f"\n🔍 强制使用指定设备: {self.input_device_index}")
        #self.input_device_index = input_device_index  # 固定为2
        # 校验设备9是否存在且支持录音
        try:
            device_info = self.p.get_device_info_by_index(self.input_device_index)
            if device_info['maxInputChannels'] == 0:
                print(f"❌ 设备{self.input_device_index}不支持录音！")
                self._pyaudio_initialized = False
                return
            print(f"✅ 设备{self.input_device_index}验证通过: {device_info['name']}")
        except Exception as e:
            print(f"❌ 设备{self.input_device_index}不存在: {e}")
            self._pyaudio_initialized = False
            return
        
        # ✅ 第二步：适配设备9的声道数（不再强制1声道）
        self.CHANNELS = self._get_device_channels(self.input_device_index)
        print(f"✅ 设备{self.input_device_index}声道数: {self.CHANNELS}")
        
        # ✅ 第三步：适配设备9的采样率（用设备默认采样率，不再固定16000）
        self.RATE = int(self._get_device_sample_rate(self.input_device_index))
        print(f"✅ 设备{self.input_device_index}采样率: {self.RATE}")
        
        # 固定参数（仅改采样率/声道数，其他不变）
        self.CHUNK = 1024
        self.FORMAT = pyaudio.paInt16
   
        self.input_device_index = 14
        # 改为通过设备名称匹配 PulseAudio 托管的设备
        #self._set_pulse_device_by_index(2)
        
        # 录音状态
        self.stream = None
        self.is_streaming = True
        self.is_running = True
        self.audio_data = []
        self.complete_text = ""
        
        # 线程锁
        self._lock = threading.Lock()
        self._pause_lock = threading.RLock()
        self._stream_rebuild_lock = threading.Lock()
        self._recording_thread = None
        self._monitor_thread = None
        
        # 原子布尔值
        self._running_flag = ctypes.c_bool(True)
        self._pause_flag = ctypes.c_bool(False)
        
        # 音频流健康状态
        self._stream_health = True
        
        # 【新增】自定义变量标记流是否关闭（替代不存在的 is_closed()）
        self._stream_closed = True  # 初始为关闭状态

        self._should_stop_stream = False
        self._should_start_stream = False


        # Whisper模型
        self.whisper_model = None
        self._load_whisper_model()
        
        # 回调函数
        self.on_transcription = None
        self.on_final_transcription = None
        self.on_error = None

        # 静音检测参数
        self.SILENCE_THRESHOLD = 0.01
        self.SILENCE_DURATION = 2
        self.last_voice_time = time.time()
        self.silent_chunk_count = 0
        self.pause_recognition_flag = False
        self.pause_printed = False
        
        print("✅ 本地Whisper音频流处理器初始化完成")
        self.auto_start()
    
    def _get_device_channels(self, device_index):
        """获取设备支持的输入声道数"""
        try:
            device_info = self.p.get_device_info_by_index(device_index)
            max_input = device_info['maxInputChannels']
            # ✅ 不再强制1声道，用设备最大声道数（设备9是32，实际用2即可）
            return 2 if max_input >= 2 else max_input
        except Exception as e:
            print(f"⚠️ 获取设备声道数失败，默认用2声道: {e}")
            return 2
    
    def _get_device_sample_rate(self, device_index):
        """获取设备默认采样率（解决Invalid sample rate）"""
        try:
            device_info = self.p.get_device_info_by_index(device_index)
            # 返回设备默认采样率（设备9是48000）
            return device_info['defaultSampleRate']
        except Exception as e:
            print(f"⚠️ 获取设备采样率失败，默认用48000: {e}")
            return 48000
    
    # 新增函数：通过设备索引找到 PulseAudio 托管的设备名称
    # def _set_pulse_device_by_index(self, target_index):
    #     """找到 PulseAudio 托管的设备9，避免直接访问 hw 设备"""
    #     if not self._pyaudio_initialized:
    #         return
    #     # 遍历所有设备，找到索引9且名称包含 pulse 的设备
    #     for i in range(self.p.get_device_count()):
    #         try:
    #             dev_info = self.p.get_device_info_by_index(i)
    #             # 匹配条件：设备索引是9，且后端是 pulse
    #             if i == target_index and 'pulse' in dev_info['name'].lower():
    #                 self.input_device_index = i
    #                 print(f"✅ 找到 PulseAudio 托管的设备9: {dev_info['name']}")
    #                 return
    #         except:
    #             continue
    #     # 如果没找到，使用 PulseAudio 默认输入设备
    #     self.input_device_index = self.p.get_default_input_device_info()['index']
    #     print(f"⚠️ 未找到设备9的 PulseAudio 托管版本，使用默认输入设备: {self.input_device_index}")
    def _rebuild_audio_stream(self):
        """音频流崩溃时重建（修复 is_closed() 错误）"""
        with self._stream_rebuild_lock:
            print("🔧 开始重建音频流...")
            try:
                if self.stream:
                    try:
                        if self.stream.is_active():
                            self.stream.stop_stream()
                        self.stream.close()
                        self._stream_closed = True  # 【修改】更新自定义关闭状态
                    except:
                        pass
                    self.stream = None
                
                stream_kwargs = {
                    'format': self.FORMAT,
                    'channels': self.CHANNELS,
                    'rate': self.RATE,
                    'input': True,
                    'frames_per_buffer': self.CHUNK,
                    'input_device_index': self.input_device_index
                }
                self.stream = self.p.open(**stream_kwargs)
                self._stream_closed = False  # 【修改】创建流后标记为未关闭
                self._stream_health = True
                print("✅ 音频流重建成功")
                return True
            except Exception as e:
                print(f"❌ 音频流重建失败: {e}")
                self._stream_closed = True  # 【修改】重建失败标记为关闭
                self._stream_health = False
                return False
            
    def _load_whisper_model(self):
        try:
            print("🔄 加载Whisper模型...")
            self.whisper_model = whisper.load_model("base")
            print("✅ Whisper模型加载完成")
        except Exception as e:
            print(f"❌ Whisper模型加载失败: {e}")
            if self.on_error:
                self.on_error(f"模型加载失败: {e}")
    
    def _calculate_audio_energy(self, audio_chunk):
        try:
            audio_np = np.frombuffer(audio_chunk, dtype=np.int16).astype(np.float32)
            rms = math.sqrt(np.mean(np.square(audio_np)))
            normalized_energy = rms / 32768.0
            return normalized_energy
        except Exception as e:
            print(f"⚠️ 计算音频能量失败: {e}")
            return 0.0
    
    def auto_start(self):
        if self._pyaudio_initialized and self.start_streaming():
            self._monitor_thread = threading.Thread(target=self._audio_monitor_loop, daemon=True)
            self._monitor_thread.start()
            print("🚀 自动录音已启动（无杂音模式）...")
        else:
            print("❌ 自动录音启动失败")
  
    def _strict_crop_audio_to_voice(self, audio_data):
        if not audio_data:
            return []
        
        voice_chunks = []
        total_chunks = len(audio_data)
        
        for idx, chunk in enumerate(audio_data):
            energy = self._calculate_audio_energy(chunk)
            is_voice = energy > 0.008 #   ✅ 裁剪时用的能量阈值，确保只保留明显的语音块
            if is_voice:
                voice_chunks.append(chunk)
        
        min_voice_chunks = max(1, int(0.05 * self.RATE / self.CHUNK))
        if len(voice_chunks) < min_voice_chunks:
            #print(f"❌ 有效语音块不足，返回空（需{min_voice_chunks}块，实际{len(voice_chunks)}块）")
            return []
        
        print(f"✅ 裁剪完成，保留{len(voice_chunks)}个有效语音块")
        return voice_chunks
    
    def pause_recognition(self):
        """暂停语音识别（简化版，避免段错误）"""
        with self._lock:
            # ✅ 只设置标志位，不直接操作流和线程
            self._pause_flag.value = True
            self.pause_recognition_flag = True
            self._should_stop_stream = True  # 请求录音线程停止流
            
            # ✅ 清空缓存（这是安全的）
            self.audio_data = []
            self.silent_chunk_count = 0
            self.pause_printed = False
            
            print("🔇 语音识别暂停请求已发送")

    def resume_recognition(self):
        """恢复语音识别（简化版）"""
        with self._lock:
            self._pause_flag.value = False
            self.pause_recognition_flag = False
            self._should_start_stream = True  # 请求录音线程启动流
            
            # 重置状态
            self.silent_chunk_count = 0
            self.pause_printed = False
            
            print("🔊 语音识别恢复请求已发送")


    def _audio_monitor_loop(self):
        """监控音频（修复静音计时不准确）"""
        CHUNK_DURATION = self.CHUNK / self.RATE  # 单块时长：1024/48000≈0.0213秒
        REQUIRED_SILENT_CHUNKS = int(self.SILENCE_DURATION / CHUNK_DURATION)  # 1.5/0.0213≈70块
        print(f"📌 静音触发配置：需累计{self.SILENCE_DURATION}秒/{REQUIRED_SILENT_CHUNKS}块静音")
        heartbeat_count = 0
        
        while True:
            heartbeat_count += 1
            if heartbeat_count % 80 == 0:
                #print(f"\n[audio_stream] 暂停语音识别: {self.pause_recognition_flag}")
                heartbeat_count = 0
            
            # ✅ 加锁读取暂停状态（避免线程冲突）
            with self._pause_lock:
                pause_flag = self.pause_recognition_flag
                pause_printed = self.pause_printed
            
            if pause_flag:
                if not pause_printed:
                    print("\r[audio_stream] TTS播报中，暂停语音识别检测...", end="", flush=True)
                    with self._pause_lock:
                        self.pause_printed = True
                time.sleep(0.1)
                continue
            
            if pause_printed:
                print("\r" + " " * 80, end="\r")
                with self._pause_lock:
                    self.pause_printed = False

            # ✅ 移除锁外的 time.sleep(0.05)，避免计时漂移
            # time.sleep(0.05) 
            
            energy = 0.0
            # ✅ 缩小锁的粒度，只在取数据时加锁
            with self._lock:
                if len(self.audio_data) > 0 and self.audio_data[-1]:
                    last_chunk = self.audio_data[-1]
                    energy = self._calculate_audio_energy(last_chunk)
            
            # ✅ 核心修改：所有静音计数操作加锁，且仅用块数计算时长
            with self._lock:
                if energy > self.SILENCE_THRESHOLD:
                    self.silent_chunk_count = 0
                    # 🔇 移除 last_voice_time 的更新，不再需要
                    silence_elapsed = 0.0
                    print(f"\r[audio_stream] 检测到语音 | 静音时长: {silence_elapsed:4.1f}秒                ", end="", flush=True)
                else:
                    self.silent_chunk_count += 1
                    # ✅ 仅通过块数计算时长，精准且不会出现负数
                    silence_elapsed = round(self.silent_chunk_count * CHUNK_DURATION, 1)
                    
                    print(f"\r[audio_stream] 已静音时长: {silence_elapsed:4.1f}/{self.SILENCE_DURATION}秒 | 暂停语音识别: {self.pause_recognition_flag}", end="", flush=True)

                # ✅ 触发转录的条件（仅判断块数）
                if self.silent_chunk_count >= REQUIRED_SILENT_CHUNKS and len(self.audio_data) > 0:
                    print("\r" + " " * 120, end="\r", flush=True)
                    print(f"\n[audio_stream] 检测到连续静音，语音长度: {len(self.audio_data)}块，触发转录...")
                    audio_copy = self.audio_data.copy()
                    self.audio_data = []
                    self.silent_chunk_count = 0
                    # 🔇 移除 last_voice_time 的重置
                    
                    final_audio = self._strict_crop_audio_to_voice(audio_copy)
                    print(f"[audio_stream] 裁剪后有效语音块数: {len(final_audio)}")
                    if not final_audio:
                        print("[audio_stream]无有效人声，跳过本次转录，继续监听...")
                        # 直接进入下一轮循环，不执行 _full_transcribe
                        continue
          
                    final_text = ""
                    self.complete_text = ""

                    if final_audio and len(final_audio) > 0:
                        print(f"\n[audio_stream] 检测到连续静音，开始转录（保留{len(final_audio)}块有效语音）...")
                        final_text = self._full_transcribe(final_audio)
                        if final_text and final_text.strip():
                            self.complete_text = final_text.strip()

                    print(f"\n[audio_stream] 转录结果: {self.complete_text if self.complete_text else '无有效语音'}")
                    # print("🎉 检测到连续静音，完成本次转录")
                    # print(f"📜 本次转录结果: {self.complete_text if self.complete_text else '无有效语音'}")

                    if self.on_final_transcription:
                        self.on_final_transcription(self.complete_text)
            
            # ✅ 移到锁外，控制循环频率，避免 CPU 100%
            time.sleep(0.01) 
                
    def _full_transcribe(self, audio_data):
        try:
            audio_bytes = b''.join(audio_data)
            if len(audio_bytes) == 0:
                return ""
            
            # ✅ 适配设备9的采样率（48000转16000，兼容Whisper）
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            # 适配多声道
            if self.CHANNELS == 2:
                audio_np = audio_np.reshape(-1, 2).mean(axis=1)
            # 采样率转换（48000→16000）
            if self.RATE != 16000:
                audio_np = self._resample_audio(audio_np, self.RATE, 16000)
            
            #print(f"🔍 转录前音频时长: {len(audio_np)/16000:.2f}秒，能量: {self._calculate_audio_energy(audio_bytes):.6f}")
            
            options = {
                "language": self._map_language(),
                "task": "transcribe",
                "fp16": False,
                "temperature": 0.0,
                "no_speech_threshold": 0.1,
                "logprob_threshold": -1.0,
                "condition_on_previous_text": False,
            }
            result = self.whisper_model.transcribe(audio_np,** options)
            return result.get("text", "").strip()
            
        except Exception as e:
            print(f"\n⚠️ 完整转录错误: {e}")
            print(traceback.format_exc()[:200])
            return ""
    
    def _resample_audio(self, audio_np, orig_sr, target_sr):
        """音频采样率转换（48000→16000，适配Whisper）"""
        try:
            from scipy.signal import resample
            # 计算重采样后的长度
            num_samples = int(len(audio_np) * target_sr / orig_sr)
            return resample(audio_np, num_samples)
        except ImportError:
            # 如果没有scipy，用简单的降采样（48000→16000是3倍，直接取1/3）
            return audio_np[::3]
        except Exception as e:
            print(f"⚠️ 采样率转换失败，使用原音频: {e}")
            return audio_np

    def _start_recording(self):
        """录音线程（增加流的安全启停逻辑）"""
        try:
            print("🔄 开始录音（全程不停止）...")
            print(f"🎤 录音参数: CHUNK={self.CHUNK}, RATE={self.RATE}, CHANNELS={self.CHANNELS}, 设备={self.input_device_index}")
            
            chunk_count = 0
            while self._running_flag.value:
                try:
                    # ✅ 检查暂停标志
                    if self._pause_flag.value:
                        time.sleep(0.05)
                        continue
                    
                    # ✅ 【新增】安全停止流逻辑
                    if self._should_stop_stream:
                        with self._lock:
                            if self.stream and not self._stream_closed:
                                try:
                                    if self.stream.is_active():
                                        self.stream.stop_stream()
                                    self.stream.close()
                                    self._stream_closed = True
                                    print("🔇 [录音线程] 音频流已安全停止")
                                except Exception as e:
                                    print(f"⚠️ 停止流异常: {e}")
                            self._should_stop_stream = False  # 清除请求
                        continue
                    
                    # ✅ 【新增】安全启动流逻辑
                    if self._should_start_stream:
                        with self._lock:
                            if not self.stream or self._stream_closed:
                                if self._rebuild_audio_stream():
                                    print("🔊 [录音线程] 音频流已安全重启")
                            else:
                                if not self.stream.is_active():
                                    self.stream.start_stream()
                            self._should_start_stream = False  # 清除请求
                        continue

                    # ✅ 原有流健康检查（保留）
                    if not self._stream_health or not self.stream:
                        print("⚠️ 音频流异常，尝试重建...")
                        if not self._rebuild_audio_stream():
                            time.sleep(0.1)
                            continue
                    
                    if not self.stream.is_active():
                        try:
                            self.stream.start_stream()
                        except:
                            time.sleep(0.01)
                            continue
                    
                    try:
                        audio_chunk = self.stream.read(self.CHUNK, exception_on_overflow=False)
                    except Exception as e:
                        print(f"⚠️ 读取音频块失败: {e}")
                        self._stream_health = False
                        time.sleep(0.05)
                        continue
                    
                    with self._lock:
                        if self._running_flag.value and not self._pause_flag.value:
                            self.audio_data.append(audio_chunk)
                            max_cache = int(self.RATE / self.CHUNK * 30)
                            if len(self.audio_data) > max_cache:
                                self.audio_data = self.audio_data[-max_cache:]
                    
                    chunk_count += 1
                    
                except Exception as e:
                    print(f"❌ 录音线程单次循环错误: {e}")
                    print(traceback.format_exc()[:200])
                    time.sleep(0.1)
                    continue
                    
        except Exception as e:
            print(f"❌ 录音线程致命错误: {e}")
            print(traceback.format_exc())
        finally:
            # ✅ 简化清理逻辑
            with self._lock:
                self.audio_data = []
            if self.stream and not self._stream_closed:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except:
                    pass
            print(f"\n🔄 录音线程结束，共录制 {chunk_count} 块（缓存已清空）")

    def set_transcription_callback(self, callback: Callable):
        self.on_transcription = callback
    
    def set_final_callback(self, callback: Callable):
        self.on_final_transcription = callback
    
    def set_error_callback(self, callback: Callable):
        self.on_error = callback
    
    def list_audio_devices(self):
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
                print(f"  - 默认采样率: {device_info['defaultSampleRate']}")
                
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
        if not self._pyaudio_initialized:
            return False
            
        try:
            device_info = self.p.get_device_info_by_index(device_index)
            if device_info['maxInputChannels'] > 0:
                with self._lock:
                    self.input_device_index = device_index
                    self.CHANNELS = self._get_device_channels(device_index)
                    self.RATE = int(self._get_device_sample_rate(device_index))
                print(f"录音设备已设置为: {device_info['name']} (声道数: {self.CHANNELS}, 采样率: {self.RATE})")
                return True
            else:
                print(f"错误: 设备 {device_index} 不支持录音")
                return False
        except Exception as e:
            print(f"设置录音设备失败: {e}")
            return False

    def set_output_device(self, device_index):
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
        self.is_streaming = True
        self.is_running = True
        self._running_flag.value = True
        
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
            stream_kwargs = {
                'format': self.FORMAT,
                'channels': self.CHANNELS,
                'rate': self.RATE,  # 用设备9的采样率（48000）
                'input': True,
                'frames_per_buffer': self.CHUNK,
                'input_device_index': self.input_device_index
            }
            
            print(f"🎤 使用指定设备: {self.input_device_index}")
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
            
            print(f"🔧 音频流参数: {stream_kwargs}")
            self.stream = self.p.open(**stream_kwargs)
            self._stream_closed = False  # 标记为未关闭
            self._stream_health = True
            
            try:
                print("🧪 测试音频流可用性...")
                test_chunk = self.stream.read(self.CHUNK, exception_on_overflow=False)
                print(f"✅ 测试成功，读取到 {len(test_chunk)} 字节数据")
            except Exception as e:
                print(f"❌ 音频流测试失败: {e}")
                self.stream.close()
                self.stream = None
                self._stream_health = False
                if self.on_error:
                    self.on_error(f"音频流测试失败，可能是权限问题: {e}")
                return False
            
            self.audio_data = []
            
            print("🎤 开始实时音频流...")
            
            self._recording_thread = threading.Thread(target=self._start_recording, daemon=True)
            self._recording_thread.start()
            
            return True
            
        except Exception as e:
            print(f"❌ 启动音频流失败: {e}")
            print(f"   - 错误类型: {type(e).__name__}")
            print(f"   - 可能原因: 设备占用、权限不足或参数不兼容")
            self.is_streaming = False
            self._running_flag.value = False
            if self.on_error:
                self.on_error(f"启动失败: {e}")
            return False

    def stop_streaming(self):
        """手动停止录音"""
        self.is_streaming = False
        self.is_running = False
        self._running_flag.value = False
        
        try:
            if self._recording_thread and self._recording_thread.is_alive():
                self._recording_thread.join(timeout=3.0)
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_thread.join(timeout=1.0)
            
            if len(self.audio_data) > 0:
                final_audio = self._strict_crop_audio_to_voice(self.audio_data.copy())
                if final_audio:
                    final_text = self._full_transcribe(final_audio)
                    if final_text and final_text.strip():
                        self.complete_text = final_text.strip()
            
            if self.stream:
                try:
                    self.stream.stop_stream()
                    time.sleep(0.1)
                    self.stream.close()
                    self._stream_closed = True  # 【修改】关闭后更新状态
                except Exception as e:
                    print(f"⚠️ 关闭音频流时出错: {e}")
                finally:
                    self.stream = None
                    self._stream_health = False
            
            with self._lock:
                self.audio_data = []
            
            print(f"\n📜 最终手动停止的转录结果: {self.complete_text if self.complete_text else '未识别到有效语音'}")
            print("✅ 音频流已停止")
            return True
            
        except Exception as e:
            print(f"停止音频流失败: {e}")
            if self.on_error:
                self.on_error(f"停止失败: {e}")
            return False
            
    def _process_audio_data(self, audio_data):
        try:
            audio_bytes = b''.join(audio_data)
            
            if len(audio_bytes) == 0:
                print("⚠️ 音频数据为空")
                if self.on_error:
                    self.on_error("音频数据为空")
                return
            
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            # 适配多声道
            if self.CHANNELS == 2:
                audio_np = audio_np.reshape(-1, 2).mean(axis=1)
            # 采样率转换
            if self.RATE != 16000:
                audio_np = self._resample_audio(audio_np, self.RATE, 16000)
            
            if len(audio_np) < 16000 * 0.5:
                print("⚠️ 音频时长过短")
                if self.on_error:
                    self.on_error("音频时长过短，请说话时间长一些")
                return
            
            print("🔄 正在进行语音识别...")
            
            options = {
                "language": self._map_language(),
                "task": "transcribe"
            }
            
            result = self.whisper_model.transcribe(audio_np,** options)
            
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
            print(traceback.format_exc()[:200])
            if self.on_error:
                self.on_error(f"识别错误: {e}")

    def _map_language(self):
        language_map = {
            "粤语": "zh",
            "普通话": "zh", 
            "英语": "en"
        }
        return language_map.get(self.language, "zh")

    def set_language(self, language):
        with self._lock:
            self.language = language
        print(f"语言已设置为: {language}")

    

    def __del__(self):
        """析构函数（极简版，只做最安全的标志位设置）"""
        try:
            self._running_flag.value = False
            self._pause_flag.value = True
            # 🔇 移除所有 join、close、terminate 操作
            # 这些操作交给显式的 stop_streaming() 或操作系统在进程结束时处理
        except Exception:
            pass


if __name__ == "__main__":
    # ✅ 强制指定设备，不再自动选择
    processor = AudioStreamProcessor(input_device_index=2)
    try:
        while processor.is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n⚠️  检测到手动中断，停止录音...")
        processor.stop_streaming()
        print("👋 程序退出")