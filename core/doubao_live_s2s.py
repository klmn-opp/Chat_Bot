import asyncio
import audioop
import json
import struct
import threading
import uuid
import zlib
from typing import Callable, Optional

import pyaudio
import websockets


class DoubaoLiveS2SBridge:
	"""Doubao realtime S2S bridge: mic -> websocket -> speaker, with text callbacks."""

	WS_URL = "wss://openspeech.bytedance.com/api/v3/realtime/dialogue"
	API_RESOURCE_ID = "volc.speech.dialog"
	API_APP_KEY = "PlgvMymc7f3tQnJ6"

	# Message types
	_MSG_FULL_CLIENT = 0x1
	_MSG_AUDIO_CLIENT = 0x2
	_MSG_FULL_SERVER = 0x9
	_MSG_AUDIO_SERVER = 0xB
	_MSG_ERROR = 0xF

	# Message flags
	_FLAG_NO_SEQ = 0x0
	_FLAG_SEQ_POS = 0x1
	_FLAG_SEQ_NEG_LAST = 0x3
	_FLAG_EVENT = 0x4

	# Serialization
	_SER_RAW = 0x0
	_SER_JSON = 0x1

	# Compression
	_COMP_NONE = 0x0

	# Event IDs
	_EV_START_CONNECTION = 1
	_EV_FINISH_CONNECTION = 2
	_EV_START_SESSION = 100
	_EV_FINISH_SESSION = 102
	_EV_TASK_REQUEST = 200

	# Server event IDs
	_EV_ASR_RESPONSE = 451
	_EV_CHAT_RESPONSE = 550
	_EV_TTS_RESPONSE = 352
	_EV_CHAT_ENDED = 559
	_EV_DIALOG_COMMON_ERROR = 599

	_ERROR_HINTS = {
		45000003: "Abnormal silence audio: long silence caused server-side timeout.",
		42000020: "Invalid StartSession payload (often asr.extra or tts.extra is null).",
		52000042: "DialogAudioIdleTimeoutError: consider input_mod=keep_alive for silence periods.",
	}

	def __init__(
		self,
		app_id: str,
		access_key: str,
		model: str,
		system_prompt: str,
		input_device_index: Optional[int] = None,
		output_device_index: Optional[int] = None,
		on_user_partial: Optional[Callable[[str], None]] = None,
		on_user_final: Optional[Callable[[str], None]] = None,
		on_ai_partial: Optional[Callable[[str], None]] = None,
		on_ai_final: Optional[Callable[[str], None]] = None,
		on_error: Optional[Callable[[str], None]] = None,
	):
		self.app_id = app_id
		self.access_key = access_key
		self.model = model
		self.system_prompt = system_prompt

		self.input_device_index = input_device_index
		self.output_device_index = output_device_index

		self.on_user_partial = on_user_partial
		self.on_user_final = on_user_final
		self.on_ai_partial = on_ai_partial
		self.on_ai_final = on_ai_final
		self.on_error = on_error

		self._thread: Optional[threading.Thread] = None
		self._loop: Optional[asyncio.AbstractEventLoop] = None
		self._main_task: Optional[asyncio.Task] = None
		self._stop_event = threading.Event()
		self._started = False

		self._in_sample_rate = 16000
		self._out_sample_rate = 24000
		self._channels = 1
		self._sample_width = 2
		self._chunk = 1024
		self._source_rate = 16000
		self._source_channels = 1

		self._audio_out_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=120)
		# Doubao server auto-assigns sequence for StartConnection(1) and StartSession(2),
		# so first audio frame should start at sequence=3.
		self._seq = 3
		self._session_id = str(uuid.uuid4())
		self._connect_id = str(uuid.uuid4())

		self._current_user_partial = ""
		self._current_ai_partial = ""

	def start(self) -> bool:
		if self._started:
			return True

		self._stop_event.clear()
		self._thread = threading.Thread(target=self._run_in_thread, daemon=True, name="DoubaoLiveS2S")
		self._thread.start()
		self._started = True
		return True

	def stop(self) -> None:
		self._stop_event.set()
		if self._loop and self._loop.is_running():
			self._loop.call_soon_threadsafe(lambda: None)
		if self._thread and self._thread.is_alive():
			self._thread.join(timeout=20.0)
		self._started = False

	@staticmethod
	def _is_input_device_valid(pya: pyaudio.PyAudio, device_index: Optional[int]) -> bool:
		if device_index is None:
			return False
		try:
			info = pya.get_device_info_by_index(device_index)
			return int(info.get("maxInputChannels", 0)) > 0
		except Exception:
			return False

	@staticmethod
	def _is_output_device_valid(pya: pyaudio.PyAudio, device_index: Optional[int]) -> bool:
		if device_index is None:
			return True
		try:
			info = pya.get_device_info_by_index(device_index)
			return int(info.get("maxOutputChannels", 0)) > 0
		except Exception:
			return False

	def _resolve_input_device(self, pya: pyaudio.PyAudio) -> Optional[int]:
		if self._is_input_device_valid(pya, self.input_device_index):
			return self.input_device_index

		try:
			default_info = pya.get_default_input_device_info()
			default_index = int(default_info.get("index"))
			if self._is_input_device_valid(pya, default_index):
				return default_index
		except Exception:
			pass

		for idx in range(pya.get_device_count()):
			if self._is_input_device_valid(pya, idx):
				return idx
		return None

	def _resolve_output_device(self, pya: pyaudio.PyAudio) -> Optional[int]:
		if self._is_output_device_valid(pya, self.output_device_index):
			return self.output_device_index
		return None

	@staticmethod
	def _supports_input_format(
		pya: pyaudio.PyAudio,
		device_index: Optional[int],
		channels: int,
		sample_rate: int,
	) -> bool:
		try:
			kwargs = {
				"rate": sample_rate,
				"input_channels": channels,
				"input_format": pyaudio.paInt16,
			}
			if device_index is not None:
				kwargs["input_device"] = device_index
			pya.is_format_supported(**kwargs)
			return True
		except Exception:
			return False

	@staticmethod
	def _supports_output_format(
		pya: pyaudio.PyAudio,
		device_index: Optional[int],
		channels: int,
		sample_rate: int,
	) -> bool:
		try:
			kwargs = {
				"rate": sample_rate,
				"output_channels": channels,
				"output_format": pyaudio.paInt16,
			}
			if device_index is not None:
				kwargs["output_device"] = device_index
			pya.is_format_supported(**kwargs)
			return True
		except Exception:
			return False

	def _pick_input_format(self, pya: pyaudio.PyAudio, device_index: int) -> tuple[int, int]:
		candidate_rates = [16000, 48000, 44100, 32000, 24000, 22050, 8000]
		try:
			info = pya.get_device_info_by_index(device_index)
			default_rate = int(info.get("defaultSampleRate", 0))
			max_channels = int(info.get("maxInputChannels", 1))
		except Exception:
			default_rate = 0
			max_channels = 1

		if default_rate > 0 and default_rate not in candidate_rates:
			candidate_rates.insert(1, default_rate)

		candidate_channels = [1]
		if max_channels >= 2:
			candidate_channels.append(2)

		for channels in candidate_channels:
			for rate in candidate_rates:
				if self._supports_input_format(pya, device_index, channels, rate):
					return rate, channels

		raise RuntimeError(f"Input device {device_index} does not support an available 16-bit format")

	def _pick_output_format(self, pya: pyaudio.PyAudio, device_index: Optional[int]) -> tuple[int, int]:
		candidate_rates = [24000, 48000, 44100, 32000, 22050, 16000]
		channels = 1
		for rate in candidate_rates:
			if self._supports_output_format(pya, device_index, channels, rate):
				return rate, channels
		return 48000, 1

	def _run_in_thread(self) -> None:
		try:
			self._loop = asyncio.new_event_loop()
			asyncio.set_event_loop(self._loop)
			self._main_task = self._loop.create_task(self._run_session())
			self._loop.run_until_complete(self._main_task)
		except asyncio.CancelledError:
			pass
		except Exception as exc:
			if self.on_error:
				self.on_error(f"Doubao Live session failed: {exc}")
		finally:
			self._main_task = None
			if self._loop and not self._loop.is_closed():
				pending = [task for task in asyncio.all_tasks(self._loop) if not task.done()]
				for task in pending:
					task.cancel()
				if pending:
					try:
						self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
					except Exception:
						pass
				self._loop.close()

	def _build_headers(self) -> dict:
		return {
			"X-Api-App-ID": self.app_id,
			"X-Api-Access-Key": self.access_key,
			"X-Api-Resource-Id": self.API_RESOURCE_ID,
			"X-Api-App-Key": self.API_APP_KEY,
			"X-Api-Connect-Id": self._connect_id,
		}

	def _next_seq(self) -> int:
		seq = self._seq
		self._seq += 1
		return seq

	@classmethod
	def _build_header(cls, message_type: int, flags: int, serialization: int, compression: int) -> bytes:
		b0 = (0x1 << 4) | 0x1
		b1 = ((message_type & 0xF) << 4) | (flags & 0xF)
		b2 = ((serialization & 0xF) << 4) | (compression & 0xF)
		b3 = 0x00
		return bytes([b0, b1, b2, b3])

	@staticmethod
	def _pack_i32(v: int) -> bytes:
		return struct.pack(">i", int(v))

	@staticmethod
	def _pack_u32(v: int) -> bytes:
		return struct.pack(">I", int(v))

	def _build_event_frame(
		self,
		event_id: int,
		payload: bytes,
		include_session_id: bool,
		include_connect_id: bool,
	) -> bytes:
		frame = bytearray()
		frame.extend(
			self._build_header(
				self._MSG_FULL_CLIENT,
				self._FLAG_EVENT,
				self._SER_JSON,
				self._COMP_NONE,
			)
		)
		frame.extend(self._pack_i32(event_id))

		if include_connect_id:
			connect_bytes = self._connect_id.encode("utf-8")
			frame.extend(self._pack_u32(len(connect_bytes)))
			frame.extend(connect_bytes)

		if include_session_id:
			session_bytes = self._session_id.encode("utf-8")
			frame.extend(self._pack_u32(len(session_bytes)))
			frame.extend(session_bytes)

		frame.extend(self._pack_u32(len(payload)))
		frame.extend(payload)
		return bytes(frame)

	def _build_audio_frame(self, audio_payload: bytes, is_last: bool = False) -> bytes:
		frame = bytearray()
		flags = self._FLAG_SEQ_NEG_LAST if is_last else self._FLAG_SEQ_POS
		frame.extend(self._build_header(self._MSG_AUDIO_CLIENT, flags, self._SER_RAW, self._COMP_NONE))
		seq = -1 if is_last else self._next_seq()
		frame.extend(self._pack_i32(seq))
		frame.extend(self._pack_u32(len(audio_payload)))
		frame.extend(audio_payload)
		return bytes(frame)

	@staticmethod
	def _read_i32(data: bytes, offset: int) -> tuple[int, int]:
		if len(data) < offset + 4:
			raise ValueError("Not enough bytes for i32")
		return struct.unpack(">i", data[offset : offset + 4])[0], offset + 4

	@staticmethod
	def _read_u32(data: bytes, offset: int) -> tuple[int, int]:
		if len(data) < offset + 4:
			raise ValueError("Not enough bytes for u32")
		return struct.unpack(">I", data[offset : offset + 4])[0], offset + 4

	def _parse_frame(self, data: bytes) -> dict:
		if len(data) < 4:
			raise ValueError("Invalid frame: header too short")

		b0, b1, b2, _ = data[0], data[1], data[2], data[3]
		_version = (b0 >> 4) & 0xF
		header_words = b0 & 0xF
		header_len = header_words * 4
		if len(data) < header_len:
			raise ValueError("Invalid frame: truncated header")

		message_type = (b1 >> 4) & 0xF
		flags = b1 & 0xF
		serialization = (b2 >> 4) & 0xF
		compression = b2 & 0xF

		offset = header_len
		event_id = None
		seq = None
		error_code = None
		session_id = None
		connect_id = None

		if flags == self._FLAG_EVENT:
			event_id, offset = self._read_i32(data, offset)

			# Optional fields vary by event type. Parse heuristically by trying
			# session/connect IDs first if buffer shape matches.
			if len(data) >= offset + 4:
				candidate_len = struct.unpack(">I", data[offset : offset + 4])[0]
				# candidate_len is plausible if we still have at least
				# [candidate bytes] + [payload_size(4)] following.
				if candidate_len <= len(data) - (offset + 4 + 4):
					offset += 4
					if candidate_len > 0:
						session_id = data[offset : offset + candidate_len].decode("utf-8", errors="ignore")
						offset += candidate_len

					# Some frames can carry both connect_id and session_id.
					if len(data) >= offset + 4:
						second_len = struct.unpack(">I", data[offset : offset + 4])[0]
						if second_len <= len(data) - (offset + 4 + 4):
							offset += 4
							if second_len > 0:
								connect_id = data[offset : offset + second_len].decode("utf-8", errors="ignore")
								offset += second_len
		elif message_type == self._MSG_ERROR:
			error_code, offset = self._read_i32(data, offset)
		elif flags in {self._FLAG_SEQ_POS, self._FLAG_SEQ_NEG_LAST}:
			seq, offset = self._read_i32(data, offset)

		payload_len, offset = self._read_u32(data, offset)
		if len(data) < offset + payload_len:
			raise ValueError("Invalid frame: payload truncated")
		payload = data[offset : offset + payload_len]

		if compression == 0x1 and payload:
			payload = zlib.decompress(payload, zlib.MAX_WBITS | 16)

		payload_json = None
		if serialization == self._SER_JSON and payload:
			payload_json = json.loads(payload.decode("utf-8", errors="ignore"))

		return {
			"message_type": message_type,
			"flags": flags,
			"event_id": event_id,
			"seq": seq,
			"error_code": error_code,
			"session_id": session_id,
			"connect_id": connect_id,
			"payload": payload,
			"payload_json": payload_json,
		}

	def _build_start_connection(self) -> bytes:
		payload = b"{}"
		return self._build_event_frame(
			event_id=self._EV_START_CONNECTION,
			payload=payload,
			include_session_id=False,
			include_connect_id=False,
		)

	def _build_finish_connection(self) -> bytes:
		payload = b"{}"
		return self._build_event_frame(
			event_id=self._EV_FINISH_CONNECTION,
			payload=payload,
			include_session_id=False,
			include_connect_id=False,
		)

	def _build_start_session(self) -> bytes:
		body = {
			"dialog": {
				"system_role": self.system_prompt,
				"extra": {
					"model": self.model,
				},
			}
		}
		payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
		return self._build_event_frame(
			event_id=self._EV_START_SESSION,
			payload=payload,
			include_session_id=True,
			include_connect_id=False,
		)

	def _build_finish_session(self) -> bytes:
		payload = b"{}"
		return self._build_event_frame(
			event_id=self._EV_FINISH_SESSION,
			payload=payload,
			include_session_id=True,
			include_connect_id=False,
		)

	def _handle_asr_response(self, payload_json: dict) -> None:
		results = payload_json.get("results") or []
		if not results:
			return

		first = results[0]
		text = (first.get("text") or "").strip()
		if not text:
			return

		is_interim = bool(first.get("is_interim", False))
		self._current_user_partial = text

		if is_interim:
			if self.on_user_partial:
				self.on_user_partial(text)
		else:
			if self.on_user_final:
				self.on_user_final(text)
			self._current_user_partial = ""

	def _handle_chat_response(self, payload_json: dict) -> None:
		text = (payload_json.get("content") or "").strip()
		if not text:
			return

		self._current_ai_partial = text
		if self.on_ai_partial:
			self.on_ai_partial(text)

	def _handle_chat_ended(self, payload_json: dict) -> None:
		if self._current_ai_partial and self.on_ai_final:
			self.on_ai_final(self._current_ai_partial)
		self._current_ai_partial = ""

	def _handle_error_payload(self, payload_json: dict) -> None:
		if not self.on_error:
			return
		status_code = payload_json.get("status_code")
		message = payload_json.get("message") or payload_json.get("error") or "unknown error"
		if status_code:
			self.on_error(f"Doubao error {status_code}: {message}")
		else:
			self.on_error(f"Doubao error: {message}")

	def _format_binary_error(self, parsed: dict) -> str:
		code = parsed.get("error_code")
		payload_json = parsed.get("payload_json")
		payload = parsed.get("payload") or b""

		status_code = None
		message = None
		if isinstance(payload_json, dict):
			status_code = payload_json.get("status_code")
			message = payload_json.get("message") or payload_json.get("error")
		elif payload:
			try:
				text = payload.decode("utf-8", errors="ignore").strip()
				if text:
					message = text
			except Exception:
				pass

		hint = self._ERROR_HINTS.get(code)
		parts = [f"Doubao binary error code: {code}"]
		if status_code is not None:
			parts.append(f"status_code={status_code}")
		if message:
			parts.append(f"message={message}")
		if hint:
			parts.append(f"hint={hint}")
		return " | ".join(parts)

	async def _recv_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
		while not self._stop_event.is_set():
			raw = await ws.recv()
			if not isinstance(raw, (bytes, bytearray)):
				continue

			try:
				parsed = self._parse_frame(bytes(raw))
			except Exception as exc:
				if self.on_error:
					self.on_error(f"Doubao frame parse failed: {exc}")
				continue

			mt = parsed["message_type"]
			event_id = parsed["event_id"]
			payload_json = parsed["payload_json"]

			if mt == self._MSG_AUDIO_SERVER:
				audio_bytes = parsed["payload"]
				if audio_bytes:
					try:
						self._audio_out_queue.put_nowait(audio_bytes)
					except asyncio.QueueFull:
						# Drop old chunks when rendering lags to keep realtime feel.
						try:
							_ = self._audio_out_queue.get_nowait()
						except asyncio.QueueEmpty:
							pass
						try:
							self._audio_out_queue.put_nowait(audio_bytes)
						except asyncio.QueueFull:
							pass
				continue

			if mt == self._MSG_ERROR:
				if self.on_error:
					self.on_error(self._format_binary_error(parsed))
				continue

			if mt != self._MSG_FULL_SERVER or not isinstance(payload_json, dict):
				continue

			if event_id == self._EV_ASR_RESPONSE:
				self._handle_asr_response(payload_json)
			elif event_id == self._EV_CHAT_RESPONSE:
				self._handle_chat_response(payload_json)
			elif event_id == self._EV_CHAT_ENDED:
				self._handle_chat_ended(payload_json)
			elif event_id == self._EV_DIALOG_COMMON_ERROR:
				self._handle_error_payload(payload_json)

	async def _send_audio_loop(self, ws: websockets.WebSocketClientProtocol, input_stream: pyaudio.Stream) -> None:
		while not self._stop_event.is_set():
			pcm = await asyncio.to_thread(input_stream.read, self._chunk, False)
			normalized = self._ensure_mono_16k(pcm, self._source_rate, self._source_channels)
			if normalized:
				await ws.send(self._build_audio_frame(normalized, is_last=False))

	async def _play_audio_loop(self, output_stream: pyaudio.Stream) -> None:
		while not self._stop_event.is_set():
			try:
				pcm = await asyncio.wait_for(self._audio_out_queue.get(), timeout=0.25)
			except asyncio.TimeoutError:
				continue

			if self._out_sample_rate != 24000:
				pcm, _ = audioop.ratecv(pcm, self._sample_width, 1, 24000, self._out_sample_rate, None)

			await asyncio.to_thread(output_stream.write, pcm)

	async def _run_session(self) -> None:
		pya = pyaudio.PyAudio()
		input_stream = None
		output_stream = None

		# Reset identifiers and sequence on each new live session.
		self._session_id = str(uuid.uuid4())
		self._connect_id = str(uuid.uuid4())
		self._seq = 3

		try:
			resolved_input_index = self._resolve_input_device(pya)
			if resolved_input_index is None:
				raise RuntimeError("No available input device")

			resolved_output_index = self._resolve_output_device(pya)

			self._source_rate, self._source_channels = self._pick_input_format(pya, resolved_input_index)
			self._out_sample_rate, self._channels = self._pick_output_format(pya, resolved_output_index)

			input_stream = await asyncio.to_thread(
				pya.open,
				format=pyaudio.paInt16,
				channels=self._source_channels,
				rate=self._source_rate,
				input=True,
				input_device_index=resolved_input_index,
				frames_per_buffer=self._chunk,
			)

			output_stream = await asyncio.to_thread(
				pya.open,
				format=pyaudio.paInt16,
				channels=self._channels,
				rate=self._out_sample_rate,
				output=True,
				output_device_index=resolved_output_index,
				frames_per_buffer=self._chunk,
			)

			async with websockets.connect(
				self.WS_URL,
				additional_headers=self._build_headers(),
				max_size=None,
				ping_interval=20,
				ping_timeout=20,
				close_timeout=5,
			) as ws:
				await ws.send(self._build_start_connection())
				await ws.send(self._build_start_session())

				recv_task = asyncio.create_task(self._recv_loop(ws))
				send_task = asyncio.create_task(self._send_audio_loop(ws, input_stream))
				play_task = asyncio.create_task(self._play_audio_loop(output_stream))

				try:
					while not self._stop_event.is_set():
						await asyncio.sleep(0.1)
				finally:
					send_task.cancel()
					play_task.cancel()
					recv_task.cancel()
					await asyncio.gather(send_task, play_task, recv_task, return_exceptions=True)

					# End current session and close websocket gracefully.
					try:
						await ws.send(self._build_finish_session())
						await ws.send(self._build_finish_connection())
					except Exception:
						pass

		except Exception as exc:
			if self.on_error:
				self.on_error(f"Doubao realtime failed: {exc}")
		finally:
			try:
				while not self._audio_out_queue.empty():
					_ = self._audio_out_queue.get_nowait()
			except Exception:
				pass

			try:
				if input_stream is not None:
					if input_stream.is_active():
						await asyncio.to_thread(input_stream.stop_stream)
					await asyncio.to_thread(input_stream.close)
			except Exception:
				pass

			try:
				if output_stream is not None:
					if output_stream.is_active():
						await asyncio.to_thread(output_stream.stop_stream)
					await asyncio.to_thread(output_stream.close)
			except Exception:
				pass

			await asyncio.to_thread(pya.terminate)

	def _ensure_mono_16k(self, pcm16: bytes, source_rate: int, source_channels: int) -> bytes:
		data = pcm16
		if source_channels > 1:
			data = audioop.tomono(data, self._sample_width, 0.5, 0.5)
		if source_rate != 16000:
			data, _ = audioop.ratecv(data, self._sample_width, 1, source_rate, 16000, None)
		return data
