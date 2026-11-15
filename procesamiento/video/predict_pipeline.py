"""Memory-bounded video inference for the drowsiness kinematic model."""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple, TypedDict

import cv2
import mediapipe as mp
import numpy as np
import onnxruntime as ort
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from scipy.signal import savgol_filter
from scipy.spatial.transform import Rotation


TARGET_FPS = 15.0
WINDOW_SIZE = 450
WINDOW_STRIDE = 150
# Covers the 5-second PERCLOS context, smoothing margin, and excluded endpoint.
FEATURE_CONTEXT = 40
CLASS_NAMES = ("Alert", "Low Vigilant", "Drowsy")

LEFT_EYE = (33, 160, 158, 133, 153, 144)
RIGHT_EYE = (362, 385, 387, 263, 373, 380)
LEFT_BROW = (70, 105, 107)
RIGHT_BROW = (300, 334, 336)
LEFT_EYE_TOP = 159
RIGHT_EYE_TOP = 386

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "drowsiness_kinematic_net.onnx"
DEFAULT_LANDMARKER_PATH = Path(__file__).resolve().parent / "face_landmarker.task"


class WindowPrediction(TypedDict):
    window_id: int
    start_seconds: float
    end_seconds: float
    padded: bool
    prediction: str
    probabilities: Dict[str, float]


def _compute_ear(points: np.ndarray, indices: Tuple[int, ...]) -> float:
    p1, p2, p3, p4, p5, p6 = points[list(indices)]
    return float(
        (np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5))
        / (2.0 * np.linalg.norm(p1 - p4) + 1e-6)
    )


def _extract_geometry(
    landmarks: Sequence[Any], transform_matrix: np.ndarray
) -> np.ndarray:
    points = np.asarray(
        [[landmark.x, landmark.y, landmark.z] for landmark in landmarks],
        dtype=np.float32,
    )
    interocular_distance = np.linalg.norm(points[33] - points[263]) + 1e-6

    ear_left = _compute_ear(points, LEFT_EYE)
    ear_right = _compute_ear(points, RIGHT_EYE)
    brow_eye_left = np.mean(
        np.linalg.norm(points[list(LEFT_BROW)] - points[LEFT_EYE_TOP], axis=1)
    ) / interocular_distance
    brow_eye_right = np.mean(
        np.linalg.norm(points[list(RIGHT_BROW)] - points[RIGHT_EYE_TOP], axis=1)
    ) / interocular_distance
    brow_distance = (
        np.linalg.norm(points[107] - points[336]) / interocular_distance
    )

    matrix = np.asarray(transform_matrix, dtype=np.float64)
    pitch, yaw, roll = Rotation.from_matrix(matrix[:3, :3]).as_euler(
        "xyz", degrees=True
    )
    return np.asarray(
        [
            ear_left,
            ear_right,
            brow_eye_left,
            brow_eye_right,
            brow_distance,
            pitch,
            yaw,
            roll,
        ],
        dtype=np.float32,
    )


def _compute_kinematics(geometry: np.ndarray) -> np.ndarray:
    """Reproduce the notebook's 15 Hz smoothing and 18-feature construction."""
    if geometry.ndim != 2 or geometry.shape[1] != 8 or geometry.shape[0] < 2:
        raise ValueError("At least two 8-value facial geometry samples are required.")

    timestamps = np.arange(geometry.shape[0], dtype=np.float64) / TARGET_FPS
    uniform_times = np.arange(timestamps[0], timestamps[-1], 1.0 / TARGET_FPS)
    uniform_geometry = np.column_stack(
        [
            np.interp(uniform_times, timestamps, geometry[:, column])
            for column in range(8)
        ]
    ).astype(np.float32)

    filter_window = min(5, uniform_geometry.shape[0])
    if filter_window % 2 == 0:
        filter_window -= 1
    if filter_window >= 3:
        smoothed = savgol_filter(
            uniform_geometry, window_length=filter_window, polyorder=2, axis=0
        )
    else:
        smoothed = uniform_geometry

    ear_left, ear_right, brow_left, brow_right, brow_distance, pitch, yaw, roll = (
        smoothed.T
    )
    ear_mean = 0.5 * (ear_left + ear_right)
    brow_mean = 0.5 * (brow_left + brow_right)
    dt = 1.0 / TARGET_FPS

    velocity_ear = np.gradient(ear_mean, dt)
    velocity_brow = np.gradient(brow_mean, dt)
    velocity_brow_distance = np.gradient(brow_distance, dt)
    angular_pitch = np.gradient(pitch, dt)
    angular_yaw = np.gradient(yaw, dt)
    angular_roll = np.gradient(roll, dt)
    acceleration_pitch = np.gradient(angular_pitch, dt)
    acceleration_yaw = np.gradient(angular_yaw, dt)

    perclos_window = min(int(5 * TARGET_FPS), len(ear_mean))
    energy_window = min(int(3 * TARGET_FPS), len(ear_mean))
    perclos = np.convolve(
        (ear_mean < 0.21).astype(np.float32),
        np.ones(perclos_window, dtype=np.float32) / perclos_window,
        mode="same",
    )
    head_energy = np.convolve(
        angular_pitch**2 + angular_yaw**2 + angular_roll**2,
        np.ones(energy_window, dtype=np.float32) / energy_window,
        mode="same",
    )

    return np.column_stack(
        [
            ear_left,
            ear_right,
            brow_left,
            brow_right,
            brow_distance,
            pitch,
            yaw,
            roll,
            velocity_ear,
            velocity_brow,
            velocity_brow_distance,
            angular_pitch,
            angular_yaw,
            angular_roll,
            acceleration_pitch,
            acceleration_yaw,
            perclos,
            head_energy,
        ]
    ).astype(np.float32)


def _normalize_window(window: np.ndarray) -> np.ndarray:
    normalized = window.astype(np.float32, copy=True)
    means = normalized.mean(axis=0, keepdims=True)
    standard_deviations = normalized.std(axis=0, keepdims=True) + 1e-6
    means[:, [0, 1, 16]] = 0.0
    standard_deviations[:, [0, 1, 16]] = 1.0
    return (normalized - means) / standard_deviations


def _probabilities(session: ort.InferenceSession, window: np.ndarray) -> np.ndarray:
    model_input = _normalize_window(window)[None, :, :].astype(np.float32)
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    logits = np.asarray(
        session.run([output_name], {input_name: model_input})[0], dtype=np.float32
    ).reshape(-1)
    if logits.size != len(CLASS_NAMES):
        raise RuntimeError(
            "The ONNX model returned "
            f"{logits.size} scores; expected {len(CLASS_NAMES)}."
        )
    shifted = logits - np.max(logits)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum()


class _WindowRunner:
    """Keep only the geometry needed for the current overlapping windows."""

    def __init__(self, session: ort.InferenceSession, first_sample_time: float):
        self.session = session
        self.first_sample_time = first_sample_time
        self.geometry: Deque[np.ndarray] = deque()
        self.buffer_start = 0
        self.sample_count = 0
        self.next_window_start = 0
        self.windows: List[WindowPrediction] = []

    def append(self, geometry: np.ndarray) -> None:
        self.geometry.append(geometry)
        self.sample_count += 1
        self._process_ready_windows()

    def _process_ready_windows(self) -> None:
        while self.sample_count >= (
            self.next_window_start + WINDOW_SIZE + FEATURE_CONTEXT
        ):
            self._predict_window(self.next_window_start, padded=False)
            self.next_window_start += WINDOW_STRIDE
            self._discard_old_geometry()

    def _predict_window(self, start: int, padded: bool) -> None:
        segment_start = max(0, start - FEATURE_CONTEXT)
        segment_end = min(
            self.sample_count, start + WINDOW_SIZE + FEATURE_CONTEXT
        )
        if segment_start < self.buffer_start:
            raise RuntimeError("The required feature context is no longer available.")

        buffer_offset = segment_start - self.buffer_start
        segment_length = segment_end - segment_start
        segment = np.asarray(
            list(self.geometry)[buffer_offset : buffer_offset + segment_length],
            dtype=np.float32,
        )
        features = _compute_kinematics(segment)
        local_start = start - segment_start
        window = features[local_start : local_start + WINDOW_SIZE]
        if window.shape[0] < WINDOW_SIZE:
            if not padded or window.shape[0] == 0:
                raise RuntimeError("A complete inference window could not be built.")
            window = np.pad(
                window,
                ((0, WINDOW_SIZE - window.shape[0]), (0, 0)),
                mode="edge",
            )

        scores = _probabilities(self.session, window)
        start_seconds = self.first_sample_time + start / TARGET_FPS
        self.windows.append(
            {
                "window_id": len(self.windows) + 1,
                "start_seconds": round(start_seconds, 3),
                "end_seconds": round(start_seconds + WINDOW_SIZE / TARGET_FPS, 3),
                "padded": padded,
                "prediction": CLASS_NAMES[int(np.argmax(scores))],
                "probabilities": {
                    name: float(score) for name, score in zip(CLASS_NAMES, scores)
                },
            }
        )

    def _discard_old_geometry(self) -> None:
        keep_from = max(0, self.next_window_start - FEATURE_CONTEXT)
        while self.buffer_start < keep_from and self.geometry:
            self.geometry.popleft()
            self.buffer_start += 1

    def finish(self) -> List[WindowPrediction]:
        if self.sample_count < 5:
            raise ValueError(
                "The video must contain at least five usable facial samples."
            )

        feature_count = self.sample_count - 1
        if feature_count < WINDOW_SIZE:
            self._predict_window(0, padded=True)
            return self.windows

        while self.next_window_start + WINDOW_SIZE <= feature_count:
            self._predict_window(self.next_window_start, padded=False)
            self.next_window_start += WINDOW_STRIDE
            self._discard_old_geometry()
        return self.windows


class VideoPredictionPipeline:
    """Load the ONNX session once and analyze video paths without storing media."""

    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL_PATH,
        landmarker_path: Path = DEFAULT_LANDMARKER_PATH,
        intra_op_threads: int = 1,
    ):
        self.model_path = Path(model_path)
        self.landmarker_path = Path(landmarker_path)
        if not self.model_path.is_file():
            raise FileNotFoundError(f"ONNX model not found: {self.model_path}")
        if not self.landmarker_path.is_file():
            raise FileNotFoundError(
                f"MediaPipe face model not found: {self.landmarker_path}"
            )
        if intra_op_threads < 1:
            raise ValueError("intra_op_threads must be at least 1.")

        options = ort.SessionOptions()
        options.intra_op_num_threads = intra_op_threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.enable_mem_pattern = True
        self.session = ort.InferenceSession(
            str(self.model_path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if len(inputs) != 1 or len(outputs) != 1:
            raise RuntimeError("The ONNX model must have one input and one output.")

    def analyze(self, video_path: Path) -> Dict[str, object]:
        path = Path(video_path)
        if not path.is_file():
            raise FileNotFoundError(f"Video file not found: {path}")

        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            capture.release()
            raise ValueError(f"Could not open video file: {path}")

        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not np.isfinite(fps) or fps <= 0:
            capture.release()
            raise ValueError("The video does not provide a valid frame rate.")

        def frames():
            try:
                while True:
                    success, frame = capture.read()
                    if not success:
                        return
                    yield frame
            finally:
                capture.release()

        return self.analyze_frames(frames(), fps)

    def analyze_bytes(self, data: bytes, fps: float = 15.0) -> Dict[str, object]:
        """Analiza un vídeo que solo existe en memoria (integración Orbivia).

        ffmpeg lo decodifica por tuberías (stdin -> stdout) a fotogramas BGR de
        160x120 a `fps` fotogramas por segundo, sin archivos temporales. El búfer
        decodificado se libera al terminar.
        """
        import subprocess

        width, height = 160, 120
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-protocol_whitelist", "pipe",
            "-i", "pipe:0", "-an",
            "-vf", f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1",
        ]
        result = subprocess.run(command, input=data, capture_output=True, check=False, timeout=60)
        if result.returncode != 0 or not result.stdout:
            raise ValueError("The video could not be decoded.")
        raw = bytearray(result.stdout)
        del result
        frame_bytes = width * height * 3
        count = len(raw) // frame_bytes

        def frames():
            for i in range(count):
                yield np.frombuffer(raw, dtype=np.uint8, count=frame_bytes,
                                    offset=i * frame_bytes).reshape(height, width, 3).copy()

        try:
            return self.analyze_frames(frames(), fps)
        finally:
            raw[:] = b"\x00" * len(raw)
            raw.clear()

    def analyze_frames(self, frames, fps: float) -> Dict[str, object]:
        """Núcleo del análisis sobre un iterable de fotogramas BGR."""
        if not np.isfinite(fps) or fps <= 0:
            raise ValueError("The video does not provide a valid frame rate.")
        frame_index = 0
        next_target_index = 0
        first_sample_time: Optional[float] = None
        previous_raw_time: Optional[float] = None
        previous_raw_geometry: Optional[np.ndarray] = None
        previous_geometry: Optional[np.ndarray] = None
        detected_faces = 0
        runner: Optional[_WindowRunner] = None
        base_options = python.BaseOptions(
            model_asset_path=str(self.landmarker_path),
            delegate=python.BaseOptions.Delegate.CPU,
        )
        landmarker_options = vision.FaceLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            output_facial_transformation_matrixes=True,
            num_faces=1,
        )

        try:
            with vision.FaceLandmarker.create_from_options(
                landmarker_options
            ) as landmarker:
                for frame in frames:
                    frame_time = int((frame_index / fps) * 1000.0) / 1000.0

                    height, width = frame.shape[:2]
                    if width > 160:
                        frame = cv2.resize(
                            frame,
                            (160, max(1, int(height * (160.0 / width)))),
                            interpolation=cv2.INTER_AREA,
                        )
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = mp.Image(
                        image_format=mp.ImageFormat.SRGB, data=rgb_frame
                    )
                    timestamp_ms = int(frame_time * 1000.0)
                    result = landmarker.detect_for_video(image, timestamp_ms)

                    if (
                        result.face_landmarks
                        and result.facial_transformation_matrixes
                    ):
                        previous_geometry = _extract_geometry(
                            result.face_landmarks[0],
                            result.facial_transformation_matrixes[0],
                        )
                        detected_faces += 1

                    if previous_geometry is not None:
                        if runner is None:
                            first_sample_time = frame_time
                            previous_raw_time = frame_time
                            previous_raw_geometry = previous_geometry.copy()
                            runner = _WindowRunner(
                                self.session, first_sample_time
                            )
                            runner.append(previous_raw_geometry)
                            next_target_index = 1
                        else:
                            if (
                                first_sample_time is None
                                or previous_raw_time is None
                                or previous_raw_geometry is None
                            ):
                                raise RuntimeError(
                                    "Video feature interpolation was not initialized."
                                )
                            while (
                                first_sample_time
                                + next_target_index / TARGET_FPS
                                < frame_time
                            ):
                                target_time = (
                                    first_sample_time
                                    + next_target_index / TARGET_FPS
                                )
                                duration = frame_time - previous_raw_time
                                if duration <= 0:
                                    raise RuntimeError(
                                        "Video frame timestamps are not increasing."
                                    )
                                fraction = (target_time - previous_raw_time) / duration
                                interpolated = previous_raw_geometry + fraction * (
                                    previous_geometry - previous_raw_geometry
                                )
                                runner.append(
                                    np.asarray(interpolated, dtype=np.float32)
                                )
                                next_target_index += 1
                            previous_raw_time = frame_time
                            previous_raw_geometry = previous_geometry.copy()
                    frame_index += 1
        finally:
            close = getattr(frames, "close", None)
            if close is not None:
                close()

        if runner is None or first_sample_time is None:
            raise ValueError("No face was detected in the video.")

        windows = runner.finish()
        if not windows:
            raise RuntimeError("The video produced no inference windows.")
        mean_scores = np.mean(
            [
                [window["probabilities"][name] for name in CLASS_NAMES]
                for window in windows
            ],
            axis=0,
        )
        winning_class = int(np.argmax(mean_scores))

        return {
            "schema_version": "1.0",
            "source": "video_drowsiness_inference",
            "model": self.model_path.name,
            "duration_seconds": round(frame_index / fps, 3),
            "detected_face_samples": detected_faces,
            "prediction": CLASS_NAMES[winning_class],
            "class_index": winning_class,
            "probabilities": {
                name: float(score) for name, score in zip(CLASS_NAMES, mean_scores)
            },
            "window_count": len(windows),
            "windows": windows,
        }


def analyze_video(
    video_path: Path,
    model_path: Path = DEFAULT_MODEL_PATH,
    landmarker_path: Path = DEFAULT_LANDMARKER_PATH,
) -> Dict[str, object]:
    """Analyze one local video and return the aggregate and per-window predictions."""
    return VideoPredictionPipeline(model_path, landmarker_path).analyze(video_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Predict alertness from a video using the bundled ONNX model."
    )
    parser.add_argument("video", type=Path, help="Path to the input video.")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--landmarker", type=Path, default=DEFAULT_LANDMARKER_PATH)
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()

    try:
        pipeline = VideoPredictionPipeline(
            args.model, args.landmarker, intra_op_threads=args.threads
        )
        result = pipeline.analyze(args.video)
    except (FileNotFoundError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
