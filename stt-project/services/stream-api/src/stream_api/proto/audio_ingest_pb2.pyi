from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class AudioChunk(_message.Message):
    __slots__ = ("audio", "session_id", "channels", "sample_width", "sample_rate")
    AUDIO_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    CHANNELS_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_WIDTH_FIELD_NUMBER: _ClassVar[int]
    SAMPLE_RATE_FIELD_NUMBER: _ClassVar[int]
    audio: bytes
    session_id: str
    channels: int
    sample_width: int
    sample_rate: int
    def __init__(self, audio: _Optional[bytes] = ..., session_id: _Optional[str] = ..., channels: _Optional[int] = ..., sample_width: _Optional[int] = ..., sample_rate: _Optional[int] = ...) -> None: ...

class ServerEvent(_message.Message):
    __slots__ = ("ack", "error", "result")
    ACK_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    RESULT_FIELD_NUMBER: _ClassVar[int]
    ack: StreamAck
    error: StreamError
    result: ConsumerResultEvent
    def __init__(self, ack: _Optional[_Union[StreamAck, _Mapping]] = ..., error: _Optional[_Union[StreamError, _Mapping]] = ..., result: _Optional[_Union[ConsumerResultEvent, _Mapping]] = ...) -> None: ...

class StreamAck(_message.Message):
    __slots__ = ("session_id", "status")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    status: str
    def __init__(self, session_id: _Optional[str] = ..., status: _Optional[str] = ...) -> None: ...

class StreamError(_message.Message):
    __slots__ = ("code", "message")
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    code: str
    message: str
    def __init__(self, code: _Optional[str] = ..., message: _Optional[str] = ...) -> None: ...

class ConsumerResultEvent(_message.Message):
    __slots__ = ("session_id", "partial_text", "is_final")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PARTIAL_TEXT_FIELD_NUMBER: _ClassVar[int]
    IS_FINAL_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    partial_text: str
    is_final: bool
    def __init__(self, session_id: _Optional[str] = ..., partial_text: _Optional[str] = ..., is_final: _Optional[bool] = ...) -> None: ...

class TranscriptionResultEvent(_message.Message):
    __slots__ = ("session_id", "partial_text", "is_final")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    PARTIAL_TEXT_FIELD_NUMBER: _ClassVar[int]
    IS_FINAL_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    partial_text: str
    is_final: bool
    def __init__(self, session_id: _Optional[str] = ..., partial_text: _Optional[str] = ..., is_final: _Optional[bool] = ...) -> None: ...

class ResultIngressSummary(_message.Message):
    __slots__ = ("accepted", "dropped")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    DROPPED_FIELD_NUMBER: _ClassVar[int]
    accepted: int
    dropped: int
    def __init__(self, accepted: _Optional[int] = ..., dropped: _Optional[int] = ...) -> None: ...
