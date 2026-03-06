#!/usr/bin/env python3
import pyaudio

p = pyaudio.PyAudio()
print("===== 所有音频设备列表（可录音设备标⭐️）=====")
for i in range(p.get_device_count()):
    dev_info = p.get_device_info_by_index(i)
    name = dev_info['name']
    max_input = dev_info['maxInputChannels']
    max_output = dev_info['maxOutputChannels']
    sample_rate = dev_info['defaultSampleRate']
    # 关键：maxInputChannels > 0 表示可录音
    is_recordable = "⭐️ 可录音" if max_input > 0 else "❌ 不可录音"
    print(f"设备 {i}: {name}")
    print(f"  - 输入声道: {max_input} | 输出声道: {max_output} | {is_recordable}")
    print(f"  - 默认采样率: {sample_rate}")
    print()
p.terminate()