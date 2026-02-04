#!/usr/bin/env python3
"""
音频设备选择工具
"""
from core.audio import AudioProcessor

class DeviceSelector:
    def __init__(self):
        self.audio = AudioProcessor()
        
    def show_devices(self):
        """显示所有可用设备"""
        input_devices, output_devices = self.audio.list_audio_devices()
        
        print("录音设备:")
        for device in input_devices:
            print(f"  {device['index']}: {device['name']}")
            
        print("\n播放设备:")
        for device in output_devices:
            print(f"  {device['index']}: {device['name']}")
            
        return input_devices, output_devices
    
    def test_recording(self, device_index):
        """测试录音设备"""
        if not self.audio.set_input_device(device_index):
            return False
            
        recording_done = False
        def on_record_complete(success, filename=None, error=None):
            nonlocal recording_done
            recording_done = True
        
        self.audio.record_audio("test_recording.wav", on_record_complete)
        
        import time
        while not recording_done:
            time.sleep(0.1)
            
        return recording_done
    
    def test_playback(self, device_index):
        """测试播放设备"""
        if not self.audio.set_output_device(device_index):
            return False
            
        playback_done = False
        def on_play_complete(success, error=None):
            nonlocal playback_done
            playback_done = True
        
        try:
            self.audio.play_audio("test_recording.wav", on_play_complete)
            
            import time
            start_time = time.time()
            while not playback_done and (time.time() - start_time) < 10:
                time.sleep(0.1)
                
        except Exception:
            return False
            
        return playback_done

def main():
    """主函数"""
    selector = DeviceSelector()
    selector.show_devices()

if __name__ == "__main__":
    main() 