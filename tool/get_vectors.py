import numpy as np
import requests
import json

class MotionEmbeddingGenerator:
    def __init__(self):
        # 配置信息
        self.API_KEY = "sk-ofsgyhaxbriaxtphqkwefuwmjqzykxoyvuushjaqhbdluicy"
        self.MODEL = "BAAI/bge-m3"
        
        # 动作列表（和你项目一致）
        self.Bot_motions = [
            "ask"
        ]
        
        # 语义增强字典
        self.motion_enhance = {
            "ask": "ask 询问 提问 请教 请教一下 请问 有什么问题吗"
        }
        
        # 存储向量（动作名: 向量）
        self.motion_embeddings = {}

    def get_embedding(self, text):
        """调用硅基流动API生成Embedding"""
        if not text:
            return np.zeros(1024).tolist()
        
        url = "https://api.siliconflow.cn/v1/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.API_KEY}"
        }
        data = {
            "input": text,
            "model": self.MODEL,
            "encoding_format": "float",
            "normalize": True
        }
        
        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            if response.status_code == 200:
                return response.json()["data"][0]["embedding"]
            else:
                print(f"❌ {text} 生成失败: {response.status_code}")
                return np.zeros(1024).tolist()
        except Exception as e:
            print(f"❌ {text} 生成异常: {e}")
            return np.zeros(1024).tolist()

    def generate_all_embeddings(self):
        """生成所有向量并输出可粘贴的纯文本"""
        print("="*80)
        print("🎯 以下是所有动作的Embedding向量（可直接复制粘贴）")
        print("="*80 + "\n")
        
        for motion in self.Bot_motions:
            # 生成增强文本的向量
            enhance_text = self.motion_enhance.get(motion, motion)
            vec = self.get_embedding(enhance_text)
            
            self.motion_embeddings[motion] = vec
            # 输出格式：动作名 → 向量（纯列表格式，无多余字符）
            print(f"【{motion}】: {vec}")
            print("-"*60)  # 分隔线，方便区分
        
        print("\n" + "="*80)
        print("✅ 所有向量生成完成！")
        print("="*80)

    def run(self):
        """主流程：仅生成+输出向量"""
        self.generate_all_embeddings()

# 运行主程序
if __name__ == "__main__":
    generator = MotionEmbeddingGenerator()
    generator.run()