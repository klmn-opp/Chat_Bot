import asyncio
import audioop
import threading
from typing import Callable, Optional

import pyaudio
from google import genai
from google.genai import types


class GeminiLiveS2SBridge:
    """Gemini Live S2S bridge: mic -> Live API -> speaker, with text callbacks."""

    def __init__(
        self,
        api_key: str,
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
        self.api_key = api_key
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

        self._audio_out_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=50)

    def start(self) -> bool:
        if self._started:
            return True

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_in_thread, daemon=True, name="GeminiLiveS2S")
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

        # `None` means use system default output device.
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
        # Prioritize the API target (16k mono), then common hardware rates.
        candidate_rates = [16000, 48000, 44100, 32000, 24000, 22050, 8000]
        try:
            device_info = pya.get_device_info_by_index(device_index)
            default_rate = int(device_info.get("defaultSampleRate", 0))
            max_channels = int(device_info.get("maxInputChannels", 1))
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

        raise RuntimeError(f"设备{device_index}没有可用的16-bit输入采样率/声道组合")

    def _pick_output_format(self, pya: pyaudio.PyAudio, device_index: Optional[int]) -> tuple[int, int]:
        candidate_rates = [24000, 48000, 44100, 32000, 22050, 16000]
        channels = 1
        for rate in candidate_rates:
            if self._supports_output_format(pya, device_index, channels, rate):
                return rate, channels
        # Keep previous fallback behavior if capability probing is inconclusive.
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
                self.on_error(f"Gemini Live会话失败: {exc}")
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

    async def _run_session(self) -> None:
        client = genai.Client(api_key=self.api_key)
        pya = pyaudio.PyAudio()

        input_stream = None
        output_stream = None

        user_partial = ""
        ai_partial = ""

        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            system_instruction=types.Content(parts=[types.Part(text=self.system_prompt)]),
        )

        try:
            resolved_input_index = self._resolve_input_device(pya)
            if resolved_input_index is None:
                raise RuntimeError("未找到可用的录音设备")

            resolved_output_index = self._resolve_output_device(pya)

            self._source_rate, self._source_channels = self._pick_input_format(
                pya,
                resolved_input_index,
            )
            self._out_sample_rate, self._channels = self._pick_output_format(
                pya,
                resolved_output_index,
            )

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
            )

            async with client.aio.live.connect(model=self.model, config=config) as session:
                async def send_audio() -> None:
                    kwargs = {"exception_on_overflow": False}
                    while not self._stop_event.is_set():
                        chunk = await asyncio.to_thread(input_stream.read, self._chunk, **kwargs)
                        chunk = self._ensure_mono_16k(chunk, self._source_rate, self._source_channels)
                        await session.send_realtime_input(
                            audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
                        )

                async def receive_loop() -> None:
                    nonlocal user_partial, ai_partial
                    async for response in session.receive():
                        if self._stop_event.is_set():
                            break

                        server_content = getattr(response, "server_content", None)
                        if not server_content:
                            continue

                        model_turn = getattr(server_content, "model_turn", None)
                        if model_turn and getattr(model_turn, "parts", None):
                            for part in model_turn.parts:
                                inline_data = getattr(part, "inline_data", None)
                                if inline_data and isinstance(getattr(inline_data, "data", None), bytes):
                                    try:
                                        self._audio_out_queue.put_nowait(inline_data.data)
                                    except asyncio.QueueFull:
                                        _ = self._audio_out_queue.get_nowait()
                                        self._audio_out_queue.put_nowait(inline_data.data)

                        in_tx = getattr(server_content, "input_transcription", None)
                        if in_tx and getattr(in_tx, "text", None):
                            user_partial = in_tx.text
                            if self.on_user_partial:
                                self.on_user_partial(user_partial)

                        out_tx = getattr(server_content, "output_transcription", None)
                        if out_tx and getattr(out_tx, "text", None):
                            ai_partial = out_tx.text
                            if self.on_ai_partial:
                                self.on_ai_partial(ai_partial)

                        if getattr(server_content, "turn_complete", False):
                            if user_partial and self.on_user_final:
                                self.on_user_final(user_partial.strip())
                            if ai_partial and self.on_ai_final:
                                self.on_ai_final(ai_partial.strip())
                            user_partial = ""
                            ai_partial = ""

                async def play_audio() -> None:
                    while not self._stop_event.is_set():
                        try:
                            chunk = await asyncio.wait_for(self._audio_out_queue.get(), timeout=0.3)
                        except asyncio.TimeoutError:
                            continue
                        await asyncio.to_thread(output_stream.write, chunk)

                tasks = [
                    asyncio.create_task(send_audio()),
                    asyncio.create_task(receive_loop()),
                    asyncio.create_task(play_audio()),
                ]

                while not self._stop_event.is_set():
                    await asyncio.sleep(0.1)

                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            if self.on_error:
                msg = str(exc)
                if "opening handshake" in msg:
                    self.on_error(
                        "Gemini Live运行错误: 与Gemini Live握手超时，请检查网络、代理/防火墙与GEMINI_API_KEY。"
                    )
                else:
                    self.on_error(f"Gemini Live运行错误: {exc}")
        finally:
            try:
                if input_stream:
                    await asyncio.to_thread(input_stream.stop_stream)
                    await asyncio.to_thread(input_stream.close)
            except Exception:
                pass
            try:
                if output_stream:
                    await asyncio.to_thread(output_stream.stop_stream)
                    await asyncio.to_thread(output_stream.close)
            except Exception:
                pass
            await asyncio.to_thread(pya.terminate)
            try:
                await client.aio.aclose()
            except Exception:
                pass

    def _ensure_mono_16k(self, pcm16: bytes, source_rate: int, source_channels: int) -> bytes:
        """Normalize input audio to mono 16k PCM16 LE."""
        data = pcm16
        if source_channels > 1:
            data = audioop.tomono(data, self._sample_width, 0.5, 0.5)
        if source_rate != 16000:
            data, _ = audioop.ratecv(data, self._sample_width, 1, source_rate, 16000, None)
        return data
