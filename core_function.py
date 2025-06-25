import json
import os
from core.audio import AudioProcessor
from core.chat import ChatBot
from core.tts import TextToSpeech

class MedicalRobotCore:
    def __init__(self, language="zh", api_key=None, api_url=None):
        # 读取语言配置
        with open(os.path.join("configs", "languages.json"), "r", encoding="utf-8") as f:
            self.languages = json.load(f)
        self.language = language
        self.audio = AudioProcessor()
        self.chat = ChatBot(api_key=api_key, api_url=api_url)
        self.tts = TextToSpeech()
        # 读取系统提示词
        with open(os.path.join("configs", "system_prompt.txt"), "r", encoding="utf-8") as f:
            self.system_prompt = f.read()

    def run_full_conversation(self, audio_filename="input.wav"):
        """
        录音->转写->AI对话->TTS 全流程演示
        """
        def after_record(success, filename=None, error=None):
            if not success:
                print(f"录音失败: {error}")
                return
            print(f"录音完成，文件: {filename}")
            self.audio.transcribe_audio(filename, self.languages[self.language]["whisper"], after_transcribe)

        def after_transcribe(success, text=None, error=None):
            if not success:
                print(f"转写失败: {error}")
                return
            print(f"识别文本: {text}")
            self.chat.chat_with_ai(text, self.system_prompt, after_chat)

        def after_chat(success, response=None, error=None):
            if not success:
                print(f"AI对话失败: {error}")
                return
            print(f"AI回复: {response}")
            self.tts.text_to_speech(response, self.languages[self.language]["tts"])

        self.audio.record_audio(audio_filename, after_record)

    def clear_history(self):
        self.chat.clear_history() 