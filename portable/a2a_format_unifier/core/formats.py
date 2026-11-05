"""Framework-free, non-mutating A2A 0.3 <-> 1.0 wire-format conversions.

The normalized representation uses legacy discriminators/lowercase enums and
camelCase IDs. Unknown fields are preserved. Unknown dialects/content fail closed.
"""
from copy import deepcopy
from datetime import datetime, timezone


class FormatError(ValueError):
    pass


def dialect_from_card(card):
    interfaces = card.get("supportedInterfaces") or []
    if interfaces:
        rpc = [i for i in interfaces if i.get("protocolBinding") == "JSONRPC"]
        if not rpc:
            raise FormatError("Peer does not advertise a supported JSON-RPC binding")
        versions = [str(i.get("protocolVersion", "")) for i in rpc]
    else:
        versions = [str(card.get("protocolVersion", card.get("protocol_version", "0.3")))]
    if any(v == "1.0" or v.startswith("1.0.") for v in versions):
        return "1.0"
    if any(v == "0.3" or v.startswith("0.3.") for v in versions):
        return "0.3"
    if "0.2.5" in versions:
        return "0.2.5"
    raise FormatError("Unsupported advertised A2A version: " + ", ".join(versions))


def _check(dialect):
    if dialect not in ("0.2.5", "0.3", "1.0"):
        raise FormatError("Unsupported A2A dialect")


def normalize_part(part):
    result = deepcopy(part)
    if not isinstance(result, dict):
        raise FormatError("A2A Part must be an object")
    kind = result.get("kind")
    if kind:
        if kind not in ("text", "file", "data"):
            raise FormatError("Unsupported legacy A2A Part kind")
        return result
    fields = [key for key in ("text", "data", "url", "raw") if key in result]
    if len(fields) != 1:
        raise FormatError("A2A Part requires exactly one supported content member")
    field = fields[0]
    if field in ("text", "data"):
        result["kind"] = field
    else:
        file = {"uri" if field == "url" else "bytes": result.pop(field)}
        if "mediaType" in result:
            file["mimeType"] = result.pop("mediaType")
        if "filename" in result:
            file["name"] = result.pop("filename")
        result.update(kind="file", file=file)
    return result


def encode_part(part, dialect):
    _check(dialect)
    result = normalize_part(part)
    if dialect != "1.0":
        if result["kind"] in ("text", "data"):
            expected = "text/plain" if result["kind"] == "text" else "application/json"
            if result.get("mediaType", expected) != expected or "filename" in result:
                raise FormatError("Part media type or filename cannot be represented in legacy A2A")
            result.pop("mediaType", None)
        return result
    kind = result.pop("kind")
    if kind == "file":
        file = result.pop("file")
        # SDK releases have used both direct and fileWith* spellings.
        uri = file.get("uri", file.get("fileWithUri"))
        raw = file.get("bytes", file.get("fileWithBytes"))
        if (uri is None) == (raw is None):
            raise FormatError("File Part requires one URI or byte payload")
        result["url" if uri is not None else "raw"] = uri if uri is not None else raw
        if "mimeType" in file:
            result["mediaType"] = file["mimeType"]
        if "name" in file:
            result["filename"] = file["name"]
        extras = set(file) - {"uri", "bytes", "fileWithUri", "fileWithBytes", "mimeType", "name"}
        if extras:
            raise FormatError("File Part has unmapped fields; refusing a lossy conversion")
    return result


def normalize_message(message):
    result = deepcopy(message)
    result["kind"] = "message"
    role = str(result.get("role", "")).removeprefix("ROLE_").lower()
    if role not in ("user", "agent"):
        raise FormatError("Unsupported A2A Message role")
    result["role"] = role
    for old, new in (("message_id", "messageId"), ("context_id", "contextId"), ("task_id", "taskId")):
        if old in result:
            result.setdefault(new, result.pop(old))
    result["parts"] = [normalize_part(p) for p in result.get("parts", [])]
    return result


def encode_message(message, dialect):
    _check(dialect)
    result = normalize_message(message)
    result["parts"] = [encode_part(p, dialect) for p in result["parts"]]
    if dialect == "1.0":
        result.pop("kind", None)
        result["role"] = "ROLE_" + result["role"].upper()
    return result


def normalize_result(result):
    result = deepcopy(result)
    # v1 SendMessageResponse uses a task/message oneof wrapper.
    if isinstance(result.get("task"), dict):
        if set(result) != {"task"}:
            raise FormatError("Unmapped response-envelope fields; refusing a lossy conversion")
        result = result["task"]
    elif isinstance(result.get("message"), dict) and "status" not in result:
        if set(result) != {"message"}:
            raise FormatError("Unmapped response-envelope fields; refusing a lossy conversion")
        result = result["message"]
    if "role" in result:
        return normalize_message(result)
    result["kind"] = "task"
    if "context_id" in result:
        result.setdefault("contextId", result.pop("context_id"))
    status = result.get("status")
    if isinstance(status, dict):
        status["state"] = str(status.get("state", "")).removeprefix("TASK_STATE_").lower().replace("_", "-")
        if isinstance(status.get("message"), dict):
            status["message"] = normalize_message(status["message"])
    for artifact in result.get("artifacts", []):
        artifact["parts"] = [normalize_part(p) for p in artifact.get("parts", [])]
    result["history"] = [normalize_message(m) for m in result.get("history", [])]
    return result


def encode_result(result, dialect):
    _check(dialect)
    result = normalize_result(result)
    is_message = result.get("kind") == "message"
    if is_message:
        encoded = encode_message(result, dialect)
        return {"message": encoded} if dialect == "1.0" else encoded
    if dialect == "1.0":
        result.pop("kind", None)
        status = result.get("status", {})
        if "state" in status:
            status["state"] = "TASK_STATE_" + status["state"].upper().replace("-", "_")
        if status.get("timestamp"):
            timestamp = datetime.fromisoformat(status["timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise FormatError("A2A timestamp requires a timezone")
            status["timestamp"] = timestamp.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        if isinstance(status.get("message"), dict):
            status["message"] = encode_message(status["message"], dialect)
        result["history"] = [encode_message(m, dialect) for m in result.get("history", [])]
        for artifact in result.get("artifacts", []):
            artifact["parts"] = [encode_part(p, dialect) for p in artifact.get("parts", [])]
        return {"task": result}
    return result
