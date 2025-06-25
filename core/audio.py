import os
import pyaudio
import wave
import threading
from faster_whisper import WhisperModel

class AudioProcessor:
    def __init__(self, model_size="large-v3", device="cpu", compute_type="int8"):
        self.whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self.CHUNK = 2048
        self.FORMAT = pyaudio.paInt16
        self.CHANNELS = 1
        self.RATE = 16000
        self.RECORD_SECONDS = 7
        self.p = pyaudio.PyAudio()

    def record_audio(self, filename, callback=None):
        """录音并保存为wav文件，完成后调用callback"""
        def _record():
            try:
                stream = self.p.open(
                    format=self.FORMAT,
                    channels=self.CHANNELS,
                    rate=self.RATE,
                    input=True,
                    frames_per_buffer=self.CHUNK
                )
                frames = []
                for _ in range(0, int(self.RATE / self.CHUNK * self.RECORD_SECONDS)):
                    data = stream.read(self.CHUNK, exception_on_overflow=False)
                    frames.append(data)
                stream.stop_stream()
                stream.close()
                wf = wave.open(filename, 'wb')
                wf.setnchannels(self.CHANNELS)
                wf.setsampwidth(self.p.get_sample_size(self.FORMAT))
                wf.setframerate(self.RATE)
                wf.writeframes(b''.join(frames))
                wf.close()
                if callback:
                    callback(success=True, filename=filename)
            except Exception as e:
                if callback:
                    callback(success=False, error=str(e))
        threading.Thread(target=_record, daemon=True).start()

    def transcribe_audio(self, wav_path, language, callback=None):
        """语音转文字，完成后调用callback"""
        def _transcribe():
            try:
                segments, _ = self.whisper_model.transcribe(
                    wav_path,
                    language=language
                )
                text = "".join([segment.text for segment in segments])
                if callback:
                    callback(success=True, text=text)
            except Exception as e:
                if callback:
                    callback(success=False, error=str(e))
        threading.Thread(target=_transcribe, daemon=True).start() 