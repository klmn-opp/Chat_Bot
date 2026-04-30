import os
import re
import shlex
import subprocess
import itertools
import math
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

        detections = self._parse_detections(raw_text)

        if detections:
            min_score = float(os.getenv("VISION_MIN_SCORE", "0.5"))
            accepted = [d for d in detections if (d.get("score_value") or 0.0) >= min_score]
            rejected = [d for d in detections if d not in accepted]

            semantic_lines: List[str] = []
            for det in accepted[:6]:
                class_name = det.get("class_name") or "未知目标"
                score_value = det.get("score_value")
                if score_value is None:
                    semantic_lines.append(f"系统检测到 {class_name}，置信度未知。")
                    continue
                percent = int(round(score_value * 100))
                confidence_tag = self._confidence_tag(score_value)
                semantic_lines.append(
                    f"系统 {percent}% 确定检测到 {class_name}（{confidence_tag}）。"
                )

            spatial_lines: List[str] = []
            physical_lines: List[str] = []
            for det in accepted[:6]:
                class_name = det.get("class_name") or "未知目标"
                position = det.get("position") or {}
                size = det.get("size") or {}
                x = position.get("x")
                y = position.get("y")
                z = position.get("z")

                if None not in (x, y, z):
                    spatial_lines.append(
                        f"{class_name}: x={x:.3f}m（前方约 {abs(x):.2f}m），"
                        f"y={y:.3f}m（{self._describe_lateral(y)}，约 {abs(y) * 100:.1f}cm），"
                        f"z={z:.3f}m（{self._describe_vertical(z)}）。"
                    )

                    distance_m = math.sqrt((x * x) + (y * y) + (z * z))
                    det["distance_m"] = round(distance_m, 4)
                else:
                    spatial_lines.append(f"{class_name}: 缺少完整 bbox3d 坐标，无法判断精确空间位置。")

                sx = size.get("x") if isinstance(size, dict) else None
                sy = size.get("y") if isinstance(size, dict) else None
                sz = size.get("z") if isinstance(size, dict) else None
                distance_text = (
                    f"直线距离约 {det['distance_m']:.3f}m"
                    if det.get("distance_m") is not None
                    else "直线距离未知"
                )
                if None not in (sx, sy, sz):
                    physical_lines.append(
                        f"{class_name}: {distance_text}，尺寸约 {sx * 100:.1f}cm x {sy * 100:.1f}cm x {sz * 100:.1f}cm。"
                    )
                else:
                    physical_lines.append(f"{class_name}: {distance_text}，尺寸信息不完整。")

            topology_line = ""
            pair_candidates: List[tuple] = []
            for first, second in itertools.combinations(accepted[:6], 2):
                p1 = first.get("position") or {}
                p2 = second.get("position") or {}
                if None in (p1.get("x"), p1.get("y"), p1.get("z"), p2.get("x"), p2.get("y"), p2.get("z")):
                    continue
                dx = p1["x"] - p2["x"]
                dy = p1["y"] - p2["y"]
                dz = p1["z"] - p2["z"]
                pair_dist = math.sqrt((dx * dx) + (dy * dy) + (dz * dz))
                pair_candidates.append((pair_dist, first, second))

            if pair_candidates:
                pair_candidates.sort(key=lambda item: item[0])
                nearest_dist, nearest_a, nearest_b = pair_candidates[0]
                topology_line = (
                    f"目标间关系：{nearest_a.get('class_name', '目标A')} 与 "
                    f"{nearest_b.get('class_name', '目标B')} 的中心间距约 {nearest_dist:.3f}m。"
                )

            filtered_text = ""
            if rejected:
                ignored_names = [item.get("class_name") or "未知目标" for item in rejected[:4]]
                filtered_text = (
                    f"低于阈值 {min_score:.2f} 的目标已忽略：" + "、".join(ignored_names) + "。"
                )

            summary_parts = [f"视觉检测到 {len(detections)} 个目标，其中有效目标 {len(accepted)} 个。"]
            if semantic_lines:
                summary_parts.append("1) 语义信息：" + " ".join(semantic_lines))
            if spatial_lines:
                summary_parts.append("2) 空间定位：" + " ".join(spatial_lines))
            if physical_lines:
                summary_parts.append("3) 距离与尺寸：" + " ".join(physical_lines))
            if topology_line:
                summary_parts.append("4) 拓扑关系：" + topology_line)
            if filtered_text:
                summary_parts.append(filtered_text)

            summary_text = "\n".join(summary_parts)
        else:
            summary_text = raw_text[:1200] if raw_text else "未捕获到有效的 /yolo/detections_3d 输出。"

        return {
            "frame_id": frame_id,
            "detections": detections,
            "summary_text": summary_text,
        }

    def _parse_detections(self, raw_text: str) -> List[Dict[str, object]]:
        detections: List[Dict[str, object]] = []

        block_pattern = re.compile(
            r"(?ms)^- class_id:\s*(?P<class_id>[^\n]+)\n(?P<body>.*?)(?=^- class_id:|\n---|\Z)"
        )
        for match in block_pattern.finditer(raw_text):
            class_id = (match.group("class_id") or "").strip()
            body = match.group("body") or ""

            class_name_match = re.search(r"^\s*class_name:\s*([^\n]+)", body, re.MULTILINE)
            score_match = re.search(r"^\s*score:\s*([^\n]+)", body, re.MULTILINE)
            class_name = class_name_match.group(1).strip() if class_name_match else None
            score = score_match.group(1).strip() if score_match else None
            score_value = self._safe_float(score)

            bbox3d_section_match = re.search(r"bbox3d:\s*\n(?P<section>.*?)(?:\n\s*mask:|\Z)", body, re.S)
            bbox3d_section = bbox3d_section_match.group("section") if bbox3d_section_match else ""

            position_match = re.search(
                r"position:\s*\n\s*x:\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\n"
                r"\s*y:\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\n"
                r"\s*z:\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)",
                bbox3d_section,
            )
            size_match = re.search(
                r"size:\s*\n\s*x:\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\n"
                r"\s*y:\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\n"
                r"\s*z:\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)",
                bbox3d_section,
            )

            position = {
                "x": self._safe_float(position_match.group(1)) if position_match else None,
                "y": self._safe_float(position_match.group(2)) if position_match else None,
                "z": self._safe_float(position_match.group(3)) if position_match else None,
            }
            size = {
                "x": self._safe_float(size_match.group(1)) if size_match else None,
                "y": self._safe_float(size_match.group(2)) if size_match else None,
                "z": self._safe_float(size_match.group(3)) if size_match else None,
            }

            detections.append(
                {
                    "class_name": class_name,
                    "class_id": class_id or None,
                    "score": score,
                    "score_value": score_value,
                    "position": position,
                    "size": size,
                }
            )

        return detections

    @staticmethod
    def _safe_float(value: Optional[str]) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _confidence_tag(score_value: float) -> str:
        if score_value >= 0.9:
            return "高置信"
        if score_value >= 0.75:
            return "较高置信"
        if score_value >= 0.5:
            return "中等置信"
        return "低置信"

    @staticmethod
    def _describe_lateral(y_value: float) -> str:
        if y_value > 0.08:
            return "偏左"
        if y_value < -0.08:
            return "偏右"
        return "基本居中"

    @staticmethod
    def _describe_vertical(z_value: float) -> str:
        if z_value > 0.08:
            return "高于相机"
        if z_value < -0.08:
            return "低于相机"
        return "与相机高度接近"