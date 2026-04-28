import sys

import core.stream_controller  # 直接导入，复用其中的状态管理和语言配置
# 彩色日志（复用你原有定义）
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
BLUE = "\033[34m"
PURPLE = "\033[35m"
RESET = "\033[0m"

def main():

    stream_controller = core.stream_controller.StreamController() 
    print(f"{GREEN}直接输入prompt，以触发后续全部流程{RESET}")
    print(f"{YELLOW}输入prompt：{RESET}", end="", flush=True)

    while True:
        try:
            user_input = input().strip()
            
            # 退出逻辑
            if user_input.lower() in ["exit", "quit", "退出", "结束"]:
                print(f"\n{BLUE}👋 程序退出！{RESET}")
                sys.exit(0)
            
            # 空输入跳过
            if not user_input:
                print(f"{YELLOW}输入prompt：{RESET}", end="", flush=True)
                continue

            # 核心：调用AI + 触发匹配（无任何冗余转换）
            print(f"\n{BLUE}你：{user_input}{RESET}")
            print(f"{YELLOW}requiring...{RESET}")
            stream_controller._process_final_text(user_input)  # 直接调用StreamController的文本处理方法，触发完整流程（包括AI调用和后续匹配）
            
        except KeyboardInterrupt:
            print(f"\n{BLUE}👋 程序退出！{RESET}")
            sys.exit(0)
        except Exception as e:
            print(f"\n{RED}❌ 出错：{e}{RESET}")
            print(f"\n{YELLOW}输入prompt：{RESET}", end="", flush=True)

if __name__ == "__main__":
    main()  