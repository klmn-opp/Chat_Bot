# 智护夜巡 · 实时语音对话系统（Stream UI）

一个基于本地 Whisper 语音识别、Edge TTS 合成与可视化对话 UI 的桌面应用原型。支持实时录音、语音转文字、调用大模型回复、语音播报与设备选择。

## 功能特性
- 实时录音与设备选择：列出输入/输出音频设备，选择并开始/停止录音与播放
- 本地语音识别（ASR）：集成 OpenAI Whisper（本地推理，无需外网）
- AI 对话：调用可配置的 Chat API（默认 SiliconFlow 兼容接口）
- 文字转语音（TTS）：基于 `edge-tts` 将 AI 回复播报为语音
- 现代化 UI：基于 Tkinter 的流式对话界面，显示实时识别、最终文本与系统状态

## 目录结构
```
configs/                # 配置文件（系统提示词等）
core/                   # 语音流、TTS、聊天逻辑
ui/                     # Tkinter 组件与主界面
main.py                 # 启动入口（桌面 UI）
requirements.txt        # Python 依赖
README.md               # 本文件
```

## 环境要求
- 操作系统：macOS / Linux / Windows（开发主要在 macOS 上验证）
- Python：建议 3.10 ~ 3.12（系统自带 Tk 支持最省心）
- 系统依赖：
  - PortAudio（PyAudio 依赖）
  - FFmpeg（用于音频转换，pydub 将调用）
  - Tk/Tcl（Tkinter 依赖；大多数系统 Python 自带，Homebrew/pyenv Python 可能需要额外配置）

macOS 常用安装命令（可选）：
```
brew install portaudio ffmpeg
```

## 安装
1) 克隆本仓库后，在项目根目录创建并激活虚拟环境：
```
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\\Scripts\\activate
```

2) 安装依赖：
```
pip install -U pip
pip install -r requirements.txt
```

> 说明：`requirements.txt` 中固定了 `numpy<2` 以避免与 Numba 的二进制不兼容（Whisper 依赖 Numba）。如需升级，请确保对应的 Numba/llvmlite 版本也兼容。

## 运行
- 启动桌面 UI：
```
python main.py
```

首次启动：
- 点击“开始对话”进入录音状态，再次点击停止并触发识别与 AI 回复
- 点击“设备设置”可选择输入/输出音频设备
- “语言”按钮可在「粤语 / 普通话 / 英语」间切换（影响 Whisper 识别与 TTS 声音）

## 配置
- 系统提示词：`configs/system_prompt.txt`（可按需修改）
- AI Key：默认从环境变量 `DEEPSEEK_API_KEY` 读取。你可以在运行前设置：
  - macOS/Linux: `export DEEPSEEK_API_KEY=sk-...`
  - Windows(PowerShell): `$env:DEEPSEEK_API_KEY='sk-...'`
- 若希望从 `.env` 加载变量，可在入口处调用 `python-dotenv` 的 `load_dotenv()`（当前代码未默认调用）。

## 已知问题与排查
- Tkinter 报错 `No module named '_tkinter'`：
  - 使用系统自带 Python（通常自带 Tk），或为 Homebrew/pyenv Python 安装/配置 Tk 支持
- Numpy/Numba 不兼容导致 Whisper 导入失败：
  - 已在 `requirements.txt` 固定 `numpy<2`，请在全新虚拟环境中安装
- 无法播放/录制：
  - 请确认系统已安装 PortAudio 与声卡权限允许访问麦克风/扬声器
- MP3 转 WAV 失败：
  - 安装 FFmpeg 或确保 `pydub` 可正常导入并调用系统 FFmpeg

## 开发说明
- 主要模块：
  - `core/audio_stream.py`：本地 Whisper 录音与识别
  - `core/chat.py`：调用外部 Chat API 生成回复
  - `core/tts.py`：Edge TTS 合成与播放（配合 `ui/components/audio_player.py`）
  - `core/stream_controller.py`：贯穿录音→识别→对话→播报状态机
  - `ui/medical_robot_stream_ui.py`：主界面
- 代码风格：尽量保持模块职责单一、线程安全（录音/播放均使用后台线程）

## 开源许可
请根据你的需求选择开源许可证并在仓库根目录添加相应的 `LICENSE` 文件（推荐 MIT 或 Apache-2.0）。

## 致谢
- [openai/whisper](https://github.com/openai/whisper)
- [edge-tts](https://github.com/rany2/edge-tts)
- 以及社区提供的相关依赖与工具

