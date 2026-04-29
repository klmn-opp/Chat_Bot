import os
import re
import shlex
import subprocess
from typing import Dict, List, Optional


class VisionCapture:
    """Capture and summarize YOLO ROS2 detections for prompt injection."""

    def __init__(
        self,
        topic: Optional[str] = None,
        setup_command: Optional[str] = None,
        timeout_sec: Optional[float] = None,
    ):
        self.topic = topic or os.getenv("VISION_ROS_TOPIC", "/yolo/detections_3d")
        self.setup_command = setup_command or os.getenv(
            "VISION_ROS_SETUP_COMMAND",
            "source ~/yolo_ws/install/setup.bash",
        )
        self.timeout_sec = float(timeout_sec or os.getenv("VISION_CAPTURE_TIMEOUT_SEC", "8"))

    def capture(self) -> Dict[str, object]:
        print(
            f"[VisionCapture] 1/4 开始采集: topic={self.topic}, timeout={self.timeout_sec}s",
            flush=True,
        )
        command = f"{self.setup_command} && ros2 topic echo {shlex.quote(self.topic)} --once"
        print(f"[VisionCapture] 2/4 即将执行命令: {command}", flush=True)

        try:
            completed = subprocess.run(
                ["bash", "-lc", command],
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "").strip()
            stderr = (exc.stderr or "").strip()
            print(
                f"[VisionCapture] 3/4 采集超时: timeout={self.timeout_sec}s, stdout_len={len(stdout)}, stderr_len={len(stderr)}",
                flush=True,
            )
            return {
                "topic": self.topic,
                "command": command,
                "returncode": None,
                "raw_text": stdout,
                "stderr": stderr or f"Vision capture timed out after {self.timeout_sec}s",
                "frame_id": None,
                "detections": [],
                "summary_text": "视觉采集超时，未获取到结果。",
                "timeout": True,
            }

        raw_text = (completed.stdout or "").strip()
        error_text = (completed.stderr or "").strip()
        summary = self._summarize_raw_output(raw_text)

        print(
            f"[VisionCapture] 3/4 命令返回: returncode={completed.returncode}, stdout_len={len(raw_text)}, stderr_len={len(error_text)}",
            flush=True,
        )
        if error_text:
            preview = error_text[:300].replace("\n", " | ")
            print(f"[VisionCapture] stderr预览: {preview}", flush=True)

        print(f"[VisionCapture] 4/4 解析完成: {summary.get('summary_text')}", flush=True)

        return {
            "topic": self.topic,
            "command": command,
            "returncode": completed.returncode,
            "raw_text": raw_text,
            "stderr": error_text,
            "frame_id": summary.get("frame_id"),
            "detections": summary.get("detections", []),
            "summary_text": summary.get("summary_text", raw_text[:1200]),
        }

    def _summarize_raw_output(self, raw_text: str) -> Dict[str, object]:
        frame_id_match = re.search(r"frame_id:\s*([^\n]+)", raw_text)
        frame_id = frame_id_match.group(1).strip() if frame_id_match else None

        class_names = [match.strip() for match in re.findall(r"class_name:\s*([^\n]+)", raw_text)]
        class_ids = [match.strip() for match in re.findall(r"class_id:\s*([^\n]+)", raw_text)]
        scores = [match.strip() for match in re.findall(r"score:\s*([^\n]+)", raw_text)]

        detections: List[Dict[str, Optional[str]]] = []
        for index, class_name in enumerate(class_names):
            detections.append(
                {
                    "class_name": class_name,
                    "class_id": class_ids[index] if index < len(class_ids) else None,
                    "score": scores[index] if index < len(scores) else None,
                }
            )

        def _extract_position_hint(block_text: str) -> str:
            block_lower = block_text.lower()

            if "left" in block_lower or "左" in block_text:
                return "左侧"
            if "right" in block_lower or "右" in block_text:
                return "右侧"
            if "center" in block_lower or "middle" in block_lower or "中" in block_text:
                return "中间"
            if "front" in block_lower or "前" in block_text:
                return "前方"
            if "back" in block_lower or "behind" in block_lower or "后" in block_text:
                return "后方"

            x_match = re.search(r"x\s*[:=]\s*([-+]?\d+(?:\.\d+)?)", block_text, re.IGNORECASE)
            if x_match:
                try:
                    x_value = float(x_match.group(1))
                    if x_value < -0.2:
                        return "左侧"
                    if x_value > 0.2:
                        return "右侧"
                    return "中间"
                except ValueError:
                    pass

            return "方位未明确"

        if detections:
            # 尽量在原始输出中为每个目标提取一段上下文，帮助判断方位。
            lines = raw_text.splitlines()
            item_lines: List[str] = []
            for detection in detections[:6]:
                class_name = detection["class_name"] or "未知目标"
                related_block = ""
                for idx, line in enumerate(lines):
                    if class_name in line:
                        start = max(0, idx - 2)
                        end = min(len(lines), idx + 8)
                        related_block = "\n".join(lines[start:end])
                        break
                position = _extract_position_hint(related_block or raw_text)
                item = class_name
                if detection.get("score"):
                    item += f"({detection['score']})"
                item_lines.append(f"{item}，{position}")

            summary_text = (
                f"在当前相机画面中检测到 {len(detections)} 个目标："
                + "；".join(item_lines)
                + "。"
            )
        else:
            summary_text = raw_text[:1200] if raw_text else "未捕获到有效的 /yolo/detections_3d 输出。"

        return {
            "frame_id": frame_id,
            "detections": detections,
            "summary_text": summary_text,
        }