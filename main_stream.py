#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
智护夜巡 - 流式对话版启动脚本
Stream v2.0 - 本地Whisper版本

使用本地Whisper进行语音识别，无需Docker依赖
"""

import sys
import os
import subprocess
import time
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def check_environment():
    """检查运行环境"""
    print("🔍 检查运行环境...")
    
    # 检查Python版本
    if sys.version_info < (3, 8):
        print("❌ Python版本过低，需要Python 3.8+")
        return False
    
    # 检查必要的依赖
    try:
        import tkinter
        import pyaudio
        import whisper
        import numpy
        import requests
        import edge_tts
        print("✅ 核心依赖检查通过")
    except ImportError as e:
        print(f"❌ 依赖缺失: {e}")
        print("请运行: pip install -r requirements.txt")
        return False
    
    return True

def main():
    """主函数"""
    print("=" * 50)
    print("🤖 智护夜巡 - 流式对话版")
    print("Stream v2.0 - 本地Whisper版本")
    print("=" * 50)
    
    # 检查环境
    if not check_environment():
        print("\n❌ 环境检查失败，程序退出")
        sys.exit(1)
    
    print("✅ 运行环境检查通过")
    
    try:
        # 导入并启动流式UI
        from ui.medical_robot_stream_ui import MedicalRobotStreamUI
        import tkinter as tk
        
        print("🚀 启动流式对话系统...")
        
        # 创建主窗口
        root = tk.Tk()
        app = MedicalRobotStreamUI(root)
        
        print("✅ 系统已启动，打开UI界面")
        print("💡 使用说明:")
        print("   1. 点击 '🎤 开始对话' 开始录音")
        print("   2. 对着麦克风说话")
        print("   3. 点击 '🛑 停止对话' 完成录音并进行AI对话")
        print("   4. 等待AI回复和语音播报")
        print("\n" + "=" * 50)
        
        # 启动GUI主循环
        root.mainloop()
        
    except KeyboardInterrupt:
        print("\n👋 用户中断，程序退出")
    except Exception as e:
        print(f"\n❌ 程序运行错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main() 