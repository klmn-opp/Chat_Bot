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
        command = f"{self.setup_command} && ros2 topic echo {shlex.quote(self.topic)} --once"
        completed = subprocess.run(
            ["bash", "-lc", command],
            capture_output=True,
            text=True,
            timeout=self.timeout_sec,
            check=False,
        )

        raw_text = (completed.stdout or "").strip()
        error_text = (completed.stderr or "").strip()
        summary = self._summarize_raw_output(raw_text)

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

        if detections:
            top_items = []
            for detection in detections[:6]:
                item = detection["class_name"]
                if detection.get("score"):
                    item += f"({detection['score']})"
                top_items.append(item)
            summary_text = (
                f"frame_id={frame_id or 'unknown'}; "
                f"detections={len(detections)}; "
                f"objects={', '.join(top_items)}"
            )
        else:
            summary_text = raw_text[:1200] if raw_text else "未捕获到有效的 /yolo/detections_3d 输出。"

        return {
            "frame_id": frame_id,
            "detections": detections,
            "summary_text": summary_text,
        }