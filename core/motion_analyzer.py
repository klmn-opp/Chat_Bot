import numpy as np
import requests
import json
from translate import Translator
class MotionAnalyzer:
    def __init__(self):
        # 1. API 配置
        self.API_KEY = " "
        
        # 2. 定义预设动作列表
        self.Bot_motions = [
            "nodding",
            "shaking head",
            "waving hand",
            "happy smile",
            "sad frown",
            "surprised look"
        ]
        
        # 3. 用于存储动作对应的向量
        self.motion_vectors = [] 
        
        # 4. 初始化时，预先计算好所有动作的 embedding
        print("正在初始化动作库 Embedding...")
        try:
            self._pre_calculate_motion_embeddings()
            print("动作库初始化完成。")
        except Exception as e:
            print(f"动作库初始化失败: {e}")

    def get_openai_embedding(self, text, model="text-embedding-3-small"):
        """
        [关键修改] 使用 requests 直接调用 API
        完全绕过已损坏的 openai 和 pydantic 库
        """
        if not text:
            return None
        
        print(f"getting origin ai response: {text}")
        translator_zh2en = Translator(from_lang="zh", to_lang="en")
        text = translator_zh2en.translate(text)
        print(f"translated text: {text}")
        text = text.replace("\n", " ")
        url = "https://api.openai.com/v1/embeddings"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.API_KEY}"
        }
        
        data = {
            "input": text,
            "model": model
        }
        
        try:
            # 发送 HTTP POST 请求，不依赖任何复杂的 Python 库
            response = requests.post(url, headers=headers, json=data, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                # 手动提取 embedding 数据
                return result['data'][0]['embedding']
            else:
                print(f"OpenAI API 错误: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"MotionAnalyzer: 获取 OpenAI embedding 时出错: {e}")
            return None

    def _pre_calculate_motion_embeddings(self):
        """内部方法：预计算动作向量"""
        self.motion_vectors = []
        for motion_text in self.Bot_motions:
            vec = self.get_openai_embedding(motion_text)
            if vec:
                self.motion_vectors.append(vec)
            else:
                self.motion_vectors.append(None) 
                print(f"警告: 动作 '{motion_text}' Embedding 生成失败")

    def cosine_similarity(self, vec1, vec2):
        """计算两个向量的余弦相似度"""
        if vec1 is None or vec2 is None:
            return 0
            
        vec1 = np.array(vec1)
        vec2 = np.array(vec2)
        
        dot_product = np.dot(vec1, vec2)
        norm_vec1 = np.linalg.norm(vec1)
        norm_vec2 = np.linalg.norm(vec2)
        
        if norm_vec1 == 0 or norm_vec2 == 0:
            return 0
        return dot_product / (norm_vec1 * norm_vec2)

    def analyze_text(self, text):
        """主功能：接收 AI 回复的文本，计算动作"""
        if not text:
            return

        print(f"\n[MotionAnalyzer] 正在分析文本语义: {text[:15]}...")
        
        target_embedding = self.get_openai_embedding(text)
        
        if not target_embedding:
            print("[MotionAnalyzer] 目标文本 Embedding 失败")
            return

        print(f"\n=== 动作匹配结果 ===")
        
        best_motion = None
        highest_score = -1

        for i in range(len(self.Bot_motions)):
            motion_text = self.Bot_motions[i]
            motion_vec = self.motion_vectors[i]
            
            similarity = self.cosine_similarity(target_embedding, motion_vec)
            print(f"动作: {motion_text} 相似度: {similarity:.4f}")

            if similarity > highest_score:
                highest_score = similarity
                best_motion = motion_text

        if best_motion:
            print(f"🔥 最匹配动作: 【{best_motion}】 (相似度: {highest_score:.4f})")
            # if highest_score > 0.4:
            #     print(f"✅ 执行动作指令: {best_motion}")
            # else:
            #     print("❌ 没有足够相似的动作")
        print("=" * 60 + "\n")




        