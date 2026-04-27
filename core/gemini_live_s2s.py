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
            self._thread.join(timeout=2.0)
        self._started = False

    def _run_in_thread(self) -> None:
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run_session())
        except Exception as exc:
            if self.on_error:
                self.on_error(f"Gemini Live会话失败: {exc}")
        finally:
            if self._loop and not self._loop.is_closed():
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
            try:
                input_stream = await asyncio.to_thread(
                    pya.open,
                    format=pyaudio.paInt16,
                    channels=self._channels,
                    rate=self._in_sample_rate,
                    input=True,
                    input_device_index=self.input_device_index,
                    frames_per_buffer=self._chunk,
                )
                self._source_rate = self._in_sample_rate
                self._source_channels = self._channels
            except Exception:
                # Fallback: some devices do not accept 16k directly.
                device_info = (
                    pya.get_device_info_by_index(self.input_device_index)
                    if self.input_device_index is not None
                    else pya.get_default_input_device_info()
                )
                self._source_rate = int(device_info.get("defaultSampleRate", 48000))
                max_channels = int(device_info.get("maxInputChannels", 1))
                self._source_channels = 2 if max_channels >= 2 else 1

                input_stream = await asyncio.to_thread(
                    pya.open,
                    format=pyaudio.paInt16,
                    channels=self._source_channels,
                    rate=self._source_rate,
                    input=True,
                    input_device_index=self.input_device_index,
                    frames_per_buffer=self._chunk,
                )

            try:
                output_stream = await asyncio.to_thread(
                    pya.open,
                    format=pyaudio.paInt16,
                    channels=self._channels,
                    rate=self._out_sample_rate,
                    output=True,
                    output_device_index=self.output_device_index,
                )
            except Exception:
                output_stream = await asyncio.to_thread(
                    pya.open,
                    format=pyaudio.paInt16,
                    channels=self._channels,
                    rate=48000,
                    output=True,
                    output_device_index=self.output_device_index,
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

        except Exception as exc:
            if self.on_error:
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

    def _ensure_mono_16k(self, pcm16: bytes, source_rate: int, source_channels: int) -> bytes:
        """Normalize input audio to mono 16k PCM16 LE."""
        data = pcm16
        if source_channels > 1:
            data = audioop.tomono(data, self._sample_width, 0.5, 0.5)
        if source_rate != 16000:
            data, _ = audioop.ratecv(data, self._sample_width, 1, source_rate, 16000, None)
        return data
