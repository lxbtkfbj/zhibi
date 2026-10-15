"""点名插话仍由原有流程处理，只保留会话归属与面向模型的称呼。"""

from app.services.meeting import SPEAKER_NAMES

NOTE_ROLES = ("chief", "lorekeeper", "writer", "reviewer")


def note_thread(payload: dict | None) -> str | None:
    thread = (payload or {}).get("thread")
    return thread if thread in NOTE_ROLES else None


def note_prompt(content: str, payload: dict | None) -> str:
    thread = note_thread(payload)
    return f"（作者对{SPEAKER_NAMES[thread]}说）{content}" if thread else content


def note_requirement(content: str, payload: dict | None) -> str:
    thread = note_thread(payload)
    return f"对{SPEAKER_NAMES[thread]}：{content}" if thread else content
