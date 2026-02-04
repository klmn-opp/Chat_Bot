import pyaudio

def list_input_devices():
    p = pyaudio.PyAudio()
    input_devices = []
    print("=== PyAudio 可用输入设备（麦克风）列表 ===")
    for i in range(p.get_device_count()):
        dev_info = p.get_device_info_by_index(i)
        # 只筛选有输入声道的设备（麦克风）
        if dev_info['maxInputChannels'] > 0:
            input_devices.append({
                'index': i,
                'name': dev_info['name'],
                'sample_rate': dev_info['defaultSampleRate']
            })
            print(f"设备索引: {i} | 设备名称: {dev_info['name']} | 默认采样率: {dev_info['defaultSampleRate']}")
    p.terminate()
    return input_devices

if __name__ == "__main__":
    list_input_devices()
