from __future__ import annotations

import asyncio
import codecs
import json
import os
import re
import sys
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

import httpx


MAX_MESSAGE_BYTES = 4 * 1024 * 1024
MAX_REMOTE_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_CONCURRENT_FORWARDING = 16
MAX_ORDINARY_FORWARDING = MAX_CONCURRENT_FORWARDING - 2
MAX_QUEUED_FORWARDING = 16
PROTOCOL_VERSION_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def _is_valid_protocol_version(value: object) -> bool:
    if not isinstance(value, str) or not PROTOCOL_VERSION_PATTERN.fullmatch(value):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


class ConfigurationError(ValueError):
    """A safe configuration error that never contains credential material."""


@dataclass(frozen=True)
class _ActiveDispatch:
    request_dispatched: asyncio.Event
    finished: asyncio.Event


@dataclass(frozen=True)
class _OrderedCancellation:
    message: dict[str, Any]
    protocol_version: str | None
    request_task: asyncio.Task[None]
    dispatch: _ActiveDispatch


async def _wait_for_request_dispatch(dispatch: _ActiveDispatch) -> bool:
    dispatched = asyncio.create_task(dispatch.request_dispatched.wait())
    finished = asyncio.create_task(dispatch.finished.wait())
    try:
        await asyncio.wait(
            {dispatched, finished},
            return_when=asyncio.FIRST_COMPLETED,
        )
        return (
            dispatch.request_dispatched.is_set()
            and not dispatch.finished.is_set()
        )
    finally:
        dispatched.cancel()
        finished.cancel()
        await asyncio.gather(
            dispatched,
            finished,
            return_exceptions=True,
        )


@dataclass(frozen=True)
class StdioSettings:
    remote_url: str
    token: str = field(repr=False)
    timeout_seconds: float = 30.0
    ca_bundle: str | None = None

    @classmethod
    def from_env(cls) -> "StdioSettings":
        remote_url = os.getenv("NYANKOFACE_MCP_REMOTE_URL", "").strip()
        token_value = os.getenv("NYANKOFACE_MCP_TOKEN")
        token_file = os.getenv("NYANKOFACE_MCP_CLIENT_TOKEN_FILE")
        if bool(token_value) == bool(token_file):
            raise ConfigurationError(
                "Set exactly one of NYANKOFACE_MCP_TOKEN or NYANKOFACE_MCP_CLIENT_TOKEN_FILE"
            )
        if token_file:
            try:
                token_value = Path(token_file).read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ConfigurationError("Unable to read NYANKOFACE_MCP_CLIENT_TOKEN_FILE") from exc
        if not token_value:
            raise ConfigurationError("The NyankoFace MCP client token is empty")
        if not 16 <= len(token_value) <= 4096 or any(
            ord(character) < 0x21 or ord(character) > 0x7E for character in token_value
        ):
            raise ConfigurationError("The NyankoFace MCP client token has an invalid format")

        parsed = urlparse(remote_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigurationError("NYANKOFACE_MCP_REMOTE_URL must be an absolute HTTP(S) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError("NYANKOFACE_MCP_REMOTE_URL must not contain credentials or query data")
        if parsed.path.rstrip("/") != "/mcp":
            raise ConfigurationError("NYANKOFACE_MCP_REMOTE_URL path must be /mcp")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ConfigurationError("NYANKOFACE_MCP_REMOTE_URL must use HTTPS outside loopback")

        try:
            timeout = float(os.getenv("NYANKOFACE_MCP_CLIENT_TIMEOUT_SECONDS", "30"))
        except ValueError as exc:
            raise ConfigurationError("NYANKOFACE_MCP_CLIENT_TIMEOUT_SECONDS must be numeric") from exc
        if not 0 < timeout <= 300:
            raise ConfigurationError("NYANKOFACE_MCP_CLIENT_TIMEOUT_SECONDS must be between 0 and 300")

        ca_bundle = os.getenv("NYANKOFACE_MCP_CA_BUNDLE") or None
        if ca_bundle and not Path(ca_bundle).is_file():
            raise ConfigurationError("NYANKOFACE_MCP_CA_BUNDLE does not identify a readable file")
        return cls(remote_url=remote_url, token=token_value, timeout_seconds=timeout, ca_bundle=ca_bundle)


def _request_id(message: object) -> object | None:
    return message.get("id") if isinstance(message, dict) else None


def _id_key(value: object | None) -> str | None:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def _request_key(message: object) -> str | None:
    if not isinstance(message, dict) or "id" not in message:
        return None
    return _id_key(message["id"])


def _is_terminal_response(message: object, request_key: str | None) -> bool:
    return (
        isinstance(message, dict)
        and message.get("jsonrpc") == "2.0"
        and "method" not in message
        and "id" in message
        and (("result" in message) != ("error" in message))
        and _request_key(message) == request_key
    )


def _protocol_error(message_id: object | None, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _parse_remote_response(response: httpx.Response) -> list[dict[str, Any]]:
    if response.status_code == 202 or not response.content:
        return []
    content_type = response.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        payloads = [response.json()]
    elif "text/event-stream" in content_type:
        payloads = []
        data_lines: list[str] = []
        for line in response.text.splitlines():
            if not line:
                if data_lines:
                    payloads.append(json.loads("\n".join(data_lines)))
                    data_lines = []
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            payloads.append(json.loads("\n".join(data_lines)))
        if not payloads:
            raise ValueError("Remote endpoint returned an empty event stream")
    else:
        raise ValueError("Remote endpoint returned an unsupported content type")
    if not all(isinstance(payload, dict) for payload in payloads):
        raise ValueError("Remote endpoint returned a non-object JSON-RPC message")
    return payloads


def _redact_token(value: Any, token: str) -> Any:
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]")
    if isinstance(value, list):
        return [_redact_token(item, token) for item in value]
    if isinstance(value, dict):
        return {
            _redact_token(key, token) if isinstance(key, str) else key: _redact_token(item, token)
            for key, item in value.items()
        }
    return value


async def _forward(
    client: httpx.AsyncClient,
    settings: StdioSettings,
    message: object,
    protocol_version: str | None = None,
    on_sse_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    on_request_dispatched: Callable[[], None] | None = None,
) -> list[dict[str, Any]]:
    message_id = _request_id(message)
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return [_protocol_error(message_id, -32600, "Invalid JSON-RPC request")]
    expects_response = "method" in message and "id" in message

    def failure(code: int, detail: str) -> list[dict[str, Any]]:
        if not expects_response:
            return []
        return [_protocol_error(message_id, code, detail)]

    try:
        headers = {
            "Authorization": f"Bearer {settings.token}",
            "Accept": "application/json, text/event-stream",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
        }
        if protocol_version:
            headers["MCP-Protocol-Version"] = protocol_version

        request_body = json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        headers["Content-Length"] = str(len(request_body))

        async def dispatch_body():
            yield request_body
            if on_request_dispatched is not None:
                on_request_dispatched()

        async with client.stream(
            "POST",
            settings.remote_url,
            headers=headers,
            content=dispatch_body(),
        ) as response:
            response.raise_for_status()
            content_encoding = response.headers.get("content-encoding", "").lower()
            if content_encoding not in {"", "identity"}:
                raise ValueError("Remote endpoint returned encoded content")
            if response.status_code == 202:
                if expects_response:
                    return failure(
                        -32000,
                        "NyankoFace MCP endpoint returned no response for a request",
                    )
                return []
            if response.status_code != 200:
                raise ValueError("Remote endpoint returned an invalid success status")
            content_type = response.headers.get("content-type", "").lower()
            response_size = 0
            if "text/event-stream" in content_type:
                decoder = codecs.getincrementaldecoder("utf-8")()
                text_buffer = ""
                previous_was_cr = False
                data_lines: list[str] = []
                payloads: list[dict[str, Any]] = []
                event_count = 0
                terminal_payload: dict[str, Any] | None = None
                request_key = _request_key(message)

                async def deliver_event() -> None:
                    nonlocal event_count, terminal_payload
                    if not data_lines:
                        return
                    payload = json.loads("\n".join(data_lines))
                    data_lines.clear()
                    if not isinstance(payload, dict):
                        raise ValueError("Remote endpoint returned a non-object JSON-RPC message")
                    redacted = _redact_token(payload, settings.token)
                    event_count += 1
                    is_terminal = (
                        isinstance(payload, dict)
                        and "method" not in payload
                        and "id" in payload
                        and ("result" in payload or "error" in payload)
                    )
                    if terminal_payload is not None:
                        raise ValueError("Remote endpoint returned data after a terminal response")
                    if is_terminal and expects_response:
                        if not _is_terminal_response(payload, request_key):
                            raise ValueError("Remote endpoint returned a mismatched response ID")
                        terminal_payload = redacted
                        return
                    if on_sse_event is None:
                        payloads.append(redacted)
                    else:
                        await on_sse_event(redacted)

                async def process_line(line: str) -> None:
                    if not line:
                        await deliver_event()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())

                async def process_text(text: str) -> None:
                    nonlocal text_buffer, previous_was_cr
                    for character in text:
                        if previous_was_cr:
                            previous_was_cr = False
                            if character == "\n":
                                continue
                        if character == "\r":
                            await process_line(text_buffer)
                            text_buffer = ""
                            previous_was_cr = True
                        elif character == "\n":
                            await process_line(text_buffer)
                            text_buffer = ""
                        else:
                            text_buffer += character

                async for chunk in response.aiter_bytes():
                    response_size += len(chunk)
                    if response_size > MAX_REMOTE_RESPONSE_BYTES:
                        raise ValueError("Remote endpoint response exceeds the size limit")
                    await process_text(decoder.decode(chunk))
                await process_text(decoder.decode(b"", final=True))
                if text_buffer:
                    await process_line(text_buffer)
                await deliver_event()
                if event_count == 0:
                    raise ValueError("Remote endpoint returned an empty event stream")
                if expects_response:
                    if terminal_payload is None:
                        return failure(
                            -32000,
                            "NyankoFace MCP endpoint returned no terminal response for a request",
                        )
                    if on_sse_event is None:
                        payloads.append(terminal_payload)
                    else:
                        await on_sse_event(terminal_payload)
                return payloads
            if "application/json" not in content_type:
                raise ValueError("Remote endpoint returned an unsupported content type")
            chunks: list[bytes] = []
            async for chunk in response.aiter_bytes():
                response_size += len(chunk)
                if response_size > MAX_REMOTE_RESPONSE_BYTES:
                    raise ValueError("Remote endpoint response exceeds the size limit")
                chunks.append(chunk)
            if not chunks:
                return failure(
                    -32000,
                    "NyankoFace MCP endpoint returned no response for a request",
                )
            buffered_response = httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=b"".join(chunks),
                request=response.request,
            )
        payloads = _parse_remote_response(buffered_response)
        if expects_response and (
            len(payloads) != 1
            or not _is_terminal_response(payloads[0], _request_key(message))
        ):
            return failure(
                -32000,
                "NyankoFace MCP endpoint returned no matching terminal response for a request",
            )
        return [_redact_token(payload, settings.token) for payload in payloads]
    except httpx.HTTPStatusError as exc:
        return failure(
            -32001,
            f"NyankoFace MCP endpoint returned HTTP {exc.response.status_code}",
        )
    except (httpx.HTTPError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return failure(
            -32000,
            "NyankoFace MCP endpoint is unavailable or returned an invalid response",
        )


async def run_stdio(
    settings: StdioSettings,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> None:
    """Bridge newline-delimited stdio JSON-RPC to independent HTTP requests."""
    input_stream = stdin or sys.stdin.buffer
    output_stream = stdout or sys.stdout.buffer
    verify: bool | str = settings.ca_bundle or True
    timeout = httpx.Timeout(settings.timeout_seconds)
    protocol_version: str | None = None
    write_lock = asyncio.Lock()
    forwarding_failed = asyncio.Event()
    response_overloaded = False
    input_queue: asyncio.Queue[bytes] = asyncio.Queue(
        maxsize=MAX_CONCURRENT_FORWARDING + 1
    )
    loop = asyncio.get_running_loop()
    stop_input = threading.Event()

    def pump_input() -> None:
        while not stop_input.is_set():
            line = input_stream.readline(MAX_MESSAGE_BYTES + 3)
            if stop_input.is_set():
                return
            try:
                queued = asyncio.run_coroutine_threadsafe(input_queue.put(line), loop)
                queued.result()
            except Exception:
                return
            if not line:
                return

    input_thread = threading.Thread(
        target=pump_input,
        name="nyankoface-mcp-stdin",
        daemon=True,
    )
    input_thread.start()

    def finish_worker(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and task.exception() is not None:
            forwarding_failed.set()
            print("NyankoFace MCP stdio forwarding worker failed", file=sys.stderr)

    async def emit(
        responses: list[dict[str, Any]],
        guard: Callable[[], bool] | None = None,
    ) -> None:
        if not responses:
            return
        async with write_lock:
            if guard is not None and not guard():
                return
            for response in responses:
                encoded = json.dumps(
                    response, ensure_ascii=False, separators=(",", ":")
                ).encode("utf-8")
                output_stream.write(encoded + b"\n")
            output_stream.flush()

    async def next_input_or_failure() -> bytes | None:
        input_ready = asyncio.create_task(input_queue.get())
        forwarding_failure = asyncio.create_task(forwarding_failed.wait())
        done, _ = await asyncio.wait(
            {input_ready, forwarding_failure},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if forwarding_failure in done and forwarding_failure.result():
            input_ready.cancel()
            await asyncio.gather(input_ready, return_exceptions=True)
            return None
        forwarding_failure.cancel()
        await asyncio.gather(forwarding_failure, return_exceptions=True)
        return input_ready.result()

    async with httpx.AsyncClient(
        timeout=timeout,
        verify=verify,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        async def emit_sse_event(response: dict[str, Any]) -> None:
            await emit([response])

        async def forward_and_emit(message: object, version: str | None) -> None:
            await emit(await _forward(client, settings, message, version, emit_sse_event))

        async def forward_request_and_emit(
            message: object,
            version: str | None,
            request_key: str,
            request_dispatched: asyncio.Event,
            finished: asyncio.Event,
        ) -> None:
            async def emit_if_live(response: dict[str, Any]) -> None:
                await emit(
                    [response],
                    lambda: request_key not in cancelled_active_ids,
                )

            try:
                responses = await _forward(
                    client,
                    settings,
                    message,
                    version,
                    emit_if_live,
                    request_dispatched.set,
                )
                await emit(
                    responses,
                    lambda: request_key not in cancelled_active_ids,
                )
            finally:
                finished.set()

        ordinary_queue: asyncio.Queue[tuple[object, object]] = asyncio.Queue(
            maxsize=MAX_QUEUED_FORWARDING
        )
        control_queue: asyncio.Queue[tuple[object, object]] = asyncio.Queue(
            maxsize=MAX_QUEUED_FORWARDING
        )
        response_queue: asyncio.Queue[tuple[object, object]] = asyncio.Queue(
            maxsize=MAX_QUEUED_FORWARDING
        )
        initialize_done = asyncio.Event()
        initialize_done.set()
        initialize_task: asyncio.Task[None] | None = None
        initialize_succeeded = False
        after_initialize = object()
        queued_request_ids: set[str] = set()
        cancelled_queued_ids: set[str] = set()
        active_request_tasks: dict[str, asyncio.Task[None]] = {}
        active_dispatches: dict[str, _ActiveDispatch] = {}
        cancelled_active_ids: set[str] = set()
        ordered_cancellation_tasks: set[asyncio.Task[None]] = set()
        control_forwarding_slot = asyncio.Semaphore(1)

        async def forward_ordered_cancellation(
            cancellation: _OrderedCancellation,
        ) -> None:
            if not await _wait_for_request_dispatch(cancellation.dispatch):
                return
            async with control_forwarding_slot:
                if (
                    cancellation.dispatch.finished.is_set()
                    or cancellation.request_task.done()
                ):
                    return
                cancellation.request_task.cancel()
                await forward_and_emit(
                    cancellation.message,
                    cancellation.protocol_version,
                )

        def finish_ordered_cancellation(task: asyncio.Task[None]) -> None:
            ordered_cancellation_tasks.discard(task)
            finish_worker(task)

        async def route_cancellation(message: dict[str, Any]) -> None:
            params = message.get("params")
            cancellation_key = (
                _id_key(params["requestId"])
                if isinstance(params, dict) and "requestId" in params
                else None
            )
            if cancellation_key is not None and cancellation_key in queued_request_ids:
                active_task = active_request_tasks.get(cancellation_key)
                if active_task is None:
                    cancelled_queued_ids.add(cancellation_key)
                    return
                else:
                    cancelled_active_ids.add(cancellation_key)
                    dispatch = active_dispatches.get(cancellation_key)
                    if dispatch is not None:
                        if len(ordered_cancellation_tasks) >= MAX_QUEUED_FORWARDING:
                            forwarding_failed.set()
                            print(
                                "NyankoFace MCP stdio cancellation capacity exceeded",
                                file=sys.stderr,
                            )
                            return
                        cancellation_task = asyncio.create_task(
                            forward_ordered_cancellation(
                                _OrderedCancellation(
                                    message=message,
                                    protocol_version=protocol_version,
                                    request_task=active_task,
                                    dispatch=dispatch,
                                )
                            )
                        )
                        ordered_cancellation_tasks.add(cancellation_task)
                        cancellation_task.add_done_callback(
                            finish_ordered_cancellation
                        )
                        return
                    else:
                        active_task.cancel()
            try:
                control_queue.put_nowait((message, protocol_version))
            except asyncio.QueueFull:
                forwarding_failed.set()
                print(
                    "NyankoFace MCP stdio cancellation capacity exceeded",
                    file=sys.stderr,
                )
                return

        async def forwarding_worker(
            work_queue: asyncio.Queue[tuple[object, object]],
        ) -> None:
            while True:
                message, version = await work_queue.get()
                try:
                    if version is after_initialize:
                        await initialize_done.wait()
                        if not initialize_succeeded:
                            request_key = _request_key(message)
                            if request_key is not None:
                                await emit([
                                    _protocol_error(
                                        _request_id(message),
                                        -32000,
                                        "MCP initialization did not complete",
                                    )
                                ])
                                queued_request_ids.discard(request_key)
                            continue
                        version = protocol_version
                    if work_queue is ordinary_queue:
                        request_key = _request_key(message)
                        if request_key is not None:
                            if request_key in cancelled_queued_ids:
                                cancelled_queued_ids.discard(request_key)
                                queued_request_ids.discard(request_key)
                                continue
                            request_dispatched = asyncio.Event()
                            finished = asyncio.Event()
                            forward_task = asyncio.create_task(
                                forward_request_and_emit(
                                    message,
                                    version if isinstance(version, str) else None,
                                    request_key,
                                    request_dispatched,
                                    finished,
                                )
                            )
                            active_request_tasks[request_key] = forward_task
                            active_dispatches[request_key] = _ActiveDispatch(
                                request_dispatched=request_dispatched,
                                finished=finished,
                            )
                            try:
                                await forward_task
                            except asyncio.CancelledError:
                                if request_key not in cancelled_active_ids:
                                    raise
                            finally:
                                finished.set()
                                cancelled_active_ids.discard(request_key)
                                active_dispatches.pop(request_key, None)
                                active_request_tasks.pop(request_key, None)
                                queued_request_ids.discard(request_key)
                            continue
                    if work_queue is control_queue:
                        async with control_forwarding_slot:
                            await forward_and_emit(
                                message,
                                version if isinstance(version, str) else None,
                            )
                    else:
                        await forward_and_emit(
                            message,
                            version if isinstance(version, str) else None,
                        )
                finally:
                    work_queue.task_done()

        async def initialize_and_emit(
            message: dict[str, Any],
            request_dispatched: asyncio.Event,
            finished: asyncio.Event,
        ) -> None:
            nonlocal initialize_succeeded, protocol_version
            initialize_key = _request_key(message)
            streamed_terminal: list[dict[str, Any]] = []

            async def emit_initialize_event(response: dict[str, Any]) -> None:
                if _is_terminal_response(response, _request_key(message)):
                    streamed_terminal.append(response)
                else:
                    await emit([response])

            try:
                responses = await _forward(
                    client,
                    settings,
                    message,
                    protocol_version,
                    emit_initialize_event,
                    request_dispatched.set,
                )
                responses.extend(streamed_terminal)
                result_response = next(
                    (
                        response
                        for response in responses
                        if "result" in response
                    ),
                    None,
                )
                result = (
                    result_response.get("result")
                    if result_response is not None
                    else None
                )
                negotiated = (
                    result.get("protocolVersion")
                    if isinstance(result, dict)
                    else None
                )
                valid_negotiated = _is_valid_protocol_version(negotiated)
                if result_response is not None and not valid_negotiated:
                    responses = [
                        _protocol_error(
                            _request_id(message),
                            -32000,
                            "NyankoFace MCP endpoint returned an invalid initialize response",
                        )
                    ]
                if valid_negotiated:
                    protocol_version = str(negotiated)
                await emit(
                    responses,
                    (
                        (lambda: initialize_key not in cancelled_active_ids)
                        if initialize_key is not None
                        else None
                    ),
                )
                if (
                    valid_negotiated
                    and (
                        initialize_key is None
                        or initialize_key not in cancelled_active_ids
                    )
                ):
                    initialize_succeeded = True
            finally:
                finished.set()
                if initialize_key is not None:
                    active_dispatches.pop(initialize_key, None)
                    active_request_tasks.pop(initialize_key, None)
                    queued_request_ids.discard(initialize_key)
                    cancelled_active_ids.discard(initialize_key)
                initialize_done.set()

        workers = [
            asyncio.create_task(forwarding_worker(ordinary_queue))
            for _ in range(MAX_ORDINARY_FORWARDING)
        ]
        workers.append(asyncio.create_task(forwarding_worker(control_queue)))
        workers.append(asyncio.create_task(forwarding_worker(response_queue)))
        for worker in workers:
            worker.add_done_callback(finish_worker)

        while True:
            line = await next_input_or_failure()
            if line is None:
                break
            if not line:
                break
            record_length = len(line)
            if line.endswith(b"\n"):
                record_length -= 1
                if record_length and line[-2:-1] == b"\r":
                    record_length -= 1
            if record_length > MAX_MESSAGE_BYTES:
                oversized_eof = False
                while line and not line.endswith(b"\n"):
                    remainder = await next_input_or_failure()
                    if remainder is None:
                        break
                    line = remainder
                    if not line:
                        oversized_eof = True
                        break
                if forwarding_failed.is_set():
                    break
                await emit([
                    _protocol_error(None, -32700, "JSON-RPC message exceeds the size limit")
                ])
                if oversized_eof:
                    break
            else:
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    await emit([_protocol_error(None, -32700, "Invalid JSON")])
                else:
                    if isinstance(message, dict) and message.get("method") == "initialize":
                        if initialize_task is not None:
                            await emit([
                                _protocol_error(
                                    _request_id(message),
                                    -32600,
                                    "MCP initialize may only be sent once",
                                )
                            ])
                        else:
                            initialize_done.clear()
                            request_dispatched = asyncio.Event()
                            finished = asyncio.Event()
                            initialize_task = asyncio.create_task(
                                initialize_and_emit(
                                    message,
                                    request_dispatched,
                                    finished,
                                )
                            )
                            initialize_key = _request_key(message)
                            if initialize_key is not None:
                                queued_request_ids.add(initialize_key)
                                active_request_tasks[initialize_key] = initialize_task
                                active_dispatches[initialize_key] = _ActiveDispatch(
                                    request_dispatched=request_dispatched,
                                    finished=finished,
                                )
                            initialize_task.add_done_callback(finish_worker)
                    else:
                        is_cancellation = (
                            isinstance(message, dict)
                            and message.get("method") == "notifications/cancelled"
                        )
                        is_response = (
                            isinstance(message, dict)
                            and "method" not in message
                            and "id" in message
                            and ("result" in message or "error" in message)
                        )
                        if is_cancellation:
                            await route_cancellation(message)
                        else:
                            work_queue = (
                                response_queue
                                if is_response
                                else control_queue
                                if is_cancellation
                                else ordinary_queue
                            )
                            if is_response:
                                try:
                                    response_queue.put_nowait(
                                        (message, protocol_version)
                                    )
                                except asyncio.QueueFull:
                                    response_overloaded = True
                                    break
                                continue
                            try:
                                queued_version: object = (
                                    after_initialize
                                    if work_queue is ordinary_queue
                                    and initialize_task is not None
                                    else protocol_version
                                )
                                work_queue.put_nowait((message, queued_version))
                            except asyncio.QueueFull:
                                overload = (
                                    _protocol_error(
                                        _request_id(message),
                                        -32002,
                                        "NyankoFace MCP stdio forwarding queue is full",
                                    )
                                    if _request_key(message) is not None
                                    else None
                                )
                                if overload is not None:
                                    await emit([overload])
                            else:
                                if not is_response:
                                    request_key = _request_key(message)
                                    if request_key is not None:
                                        queued_request_ids.add(request_key)

        if not forwarding_failed.is_set() and not response_overloaded:
            async def drain_queues() -> None:
                await asyncio.gather(
                    initialize_done.wait(),
                    ordinary_queue.join(),
                    control_queue.join(),
                    response_queue.join(),
                )
                while ordered_cancellation_tasks:
                    await asyncio.gather(*tuple(ordered_cancellation_tasks))

            drain = asyncio.create_task(drain_queues())
            forwarding_failure = asyncio.create_task(forwarding_failed.wait())
            done, _ = await asyncio.wait(
                {drain, forwarding_failure},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if forwarding_failure in done and forwarding_failure.result():
                drain.cancel()
                await asyncio.gather(drain, return_exceptions=True)
            else:
                forwarding_failure.cancel()
                await asyncio.gather(forwarding_failure, return_exceptions=True)
                await drain
        for worker in workers:
            worker.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        for cancellation_task in ordered_cancellation_tasks:
            cancellation_task.cancel()
        await asyncio.gather(
            *ordered_cancellation_tasks,
            return_exceptions=True,
        )
        if initialize_task is not None and not initialize_task.done():
            initialize_task.cancel()
        if initialize_task is not None:
            await asyncio.gather(initialize_task, return_exceptions=True)
        stop_input.set()
        while input_thread.is_alive() and not input_queue.empty():
            input_queue.get_nowait()
            await asyncio.sleep(0)
        input_thread.join(timeout=0.1)
        if response_overloaded:
            raise RuntimeError("NyankoFace MCP stdio response capacity exceeded")
        if forwarding_failed.is_set():
            raise RuntimeError("NyankoFace MCP stdio forwarding failed")
