import os
import requests
import threading

class ChatBot:
    def __init__(self, api_key=None, api_url=None, max_history_length=5):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            self.api_key = "sk-ofsgyhaxbriaxtphqkwefuwmjqzykxoyvuushjaqhbdluicy"
        self.api_url = api_url or "https://api.siliconflow.cn/v1/chat/completions"
        self.conversation_history = []
        self.max_history_length = max_history_length

    def chat_with_ai(self, text, system_prompt, callback=None):
        """与AI对话，完成后调用callback"""
        def _chat(system_prompt_inner):
            self.conversation_history.append({"role": "user", "content": text})
            if len(self.conversation_history) > self.max_history_length * 2:
                self.conversation_history = self.conversation_history[-self.max_history_length * 2:]
            history_prompt = "\n# 历史对话\n"
            for msg in self.conversation_history[:-1]:
                role = "用户" if msg["role"] == "user" else "守夜人"
                history_prompt += f"{role}: {msg['content']}\n"
            system_prompt_inner += history_prompt + "\n当前用户问题："
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                data = {
                    "model": "deepseek-ai/DeepSeek-V3.2-Exp",
                    "messages": [
                        {"role": "system", "content": system_prompt_inner},
                        {"role": "user", "content": text}
                    ],
                    "stream": False,
                    "max_tokens": 512,
                    "enable_thinking": False,
                    "thinking_budget": 4096,
                    "min_p": 0.05,
                    "stop": None,
                    "temperature": 0.7,
                    "top_p": 0.7,
                    "top_k": 50,
                    "frequency_penalty": 0.5,
                    "n": 1,
                    "response_format": {"type": "text"}
                }
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=data,
                    timeout=30
                )
                if response.status_code == 200:
                    response_data = response.json()
                    if "choices" in response_data and len(response_data["choices"]) > 0:
                        full_response = response_data["choices"][0]["message"]["content"]
                        self.conversation_history.append({"role": "assistant", "content": full_response})
                        if callback:
                            callback(success=True, response=full_response)
                    else:
                        if callback:
                            callback(success=False, error=f"API响应格式错误: {response_data}")
                else:
                    if callback:
                        callback(success=False, error=f"API调用失败: {response.status_code} - {response.text}")
            except Exception as e:
                if callback:
                    callback(success=False, error=str(e))
        threading.Thread(target=_chat, args=(system_prompt,), daemon=True).start()

    def clear_history(self):
        self.conversation_history = [] 
