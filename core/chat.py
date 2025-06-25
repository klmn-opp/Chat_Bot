import os
import requests
import threading
import time

class ChatBot:
    def __init__(self, api_key=None, api_url=None, max_history_length=5):

        # ========== 核心修改：替换为新平台的配置 ==========
        # 新平台的API Key
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        #self.api_key = api_key or os.getenv("INFINITEAI_API_KEY")  # 兼容新平台环境变量
        if not self.api_key:
            raise ValueError("请先设置DEEPSEEK_API_KEY环境变量，或在初始化ChatBot时提供api_key参数")
        #if not self.api_key:
            #self.api_key = "sk-sk-7KsSkzOVRrTn4J0cIgAcG7POVzGAJhHI"
        #if not self.api_key:
        #self.api_key = "sk-97pulgUFGcu5pujD2xgqfqn9GBw7BqviFRKFhmpe61Kq77lA"
        # self.api_key = "sk-dKDBH61WOlKzXtkFi73FgkK2Dn9PMFUZghVhXzLvotl8tX7t"
        # self.api_url = api_url or "https://x666.me/v1/chat/completions"
        #self.api_url = api_url or "https://api.openai.com/v1/chat/completions"
        self.api_url = api_url or "https://api.siliconflow.cn/v1/chat/completions"

        # ==================================================

        self.conversation_history = []
        self.max_history_length = max_history_length

    def chat_with_ai(self, text, system_prompt, callback=None):
        """与AI对话，完成后调用callback"""
        def _chat(system_prompt_inner):
            self.conversation_history.append({"role": "user", "content": text})
            # 控制历史对话长度
            if len(self.conversation_history) > self.max_history_length * 2:
                self.conversation_history = self.conversation_history[-self.max_history_length * 2:]
            
            # 拼接历史对话到系统提示词（原有逻辑完全保留）
            history_prompt = "\n# 历史对话\n"
            for msg in self.conversation_history[:-1]:
                role = "用户" if msg["role"] == "user" else "守夜人"
                history_prompt += f"{role}: {msg['content']}\n"
            system_prompt_inner += history_prompt + "\n当前用户问题："

            try:
                # 请求头格式和原有完全兼容，无需修改
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }

                # ========== 核心修改：适配新平台的请求参数 ==========
                # data = {
                #     # 新平台支持的模型，示例用gpt-5.2，也可以换成gpt-5.1
                #     "model": "GPT-5-nano",
                #     # 消息格式和原有完全兼容
                #     "messages": [
                #         {"role": "system", "content": system_prompt_inner},
                #         {"role": "user", "content": text}
                #     ],
                #     # 通用参数保留，移除原DeepSeek平台专属参数
                #     "stream": False,
                #     "max_tokens": 64,
                #     "temperature": 0.7,
                #     "top_p": 0.7,
                #     "top_k": 50,
                #     "frequency_penalty": 0.5,
                #     "n": 1,
                #     "response_format": {"type": "text"}
                # }

                #"model": "deepseek-ai/DeepSeek-V3.2-Exp",
                #"enable_thinking": False,

                data = {
              
                    "model": "Qwen/Qwen2.5-7B-Instruct",
                    "messages": [
                        {"role": "system", "content": system_prompt_inner},
                        {"role": "user", "content": text}
                    ],
                    "stream": False,
                    "max_tokens": 256,
                    
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
                # ======================================================

                print(f"\n[Chat]start requiring..\nmax_tokens: {data['max_tokens']}, temperature: {data['temperature']}, top_p: {data['top_p']}, top_k: {data['top_k']}, frequency_penalty: {data['frequency_penalty']}\n", flush=True)

                ai_request_start = time.time()
                # 发送请求，原有逻辑完全保留
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=data,
                    timeout=30
                )

                ai_request_end = time.time()
                ai_cost = ai_request_end - ai_request_start
                ai_cost_ms = round(ai_cost * 1000, 2)

                # 控制台颜色输出逻辑完全保留
                GREEN = "\033[32m"
                YELLOW = "\033[33m"
                RED = "\033[31m"
                RESET = "\033[0m"
                
                if ai_cost_ms < 1500:
                    colored_num = f"{GREEN}{ai_cost_ms}{RESET}"
                elif 1500 <= ai_cost_ms <= 2500:
                    colored_num = f"{YELLOW}{ai_cost_ms}{RESET}"
                else:
                    colored_num = f"{RED}{ai_cost_ms}{RESET}"

                print(f"[Chat] ⏱️ 获取AI回复耗时: {colored_num} 毫秒 (状态码: {response.status_code})", flush=True)

                # 响应解析逻辑完全兼容，无需修改
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
                    
        # 多线程调用逻辑完全保留
        threading.Thread(target=_chat, args=(system_prompt,), daemon=True).start()

    def clear_history(self):
        self.conversation_history = []
