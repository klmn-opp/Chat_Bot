#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
智护夜巡 - 流式对话版启动脚本
"""

import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def main():
    """主函数"""
    from ui.medical_robot_stream_ui import MedicalRobotStreamUI
    import tkinter as tk
    
    # 创建主窗口并启动应用
    root = tk.Tk()
    app = MedicalRobotStreamUI(root)
    root.mainloop()

if __name__ == "__main__":
    main() 