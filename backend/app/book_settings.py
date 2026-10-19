"""Book-local writing preferences and their exact, author-visible prompt text."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BookSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setup_mode: Literal["puzzle", "oneshot"] = "puzzle"
    title_style: Literal["short", "tomato", "chief", "custom"] = "short"
    title_custom: str = Field("", max_length=5000)
    person: Literal["first", "second", "third"] = "third"
    intimacy: Literal["heart", "fade", "custom"] = "fade"
    intimacy_custom: str = Field("", max_length=5000)
    chapter_words: int | None = Field(None, ge=1, le=100000)
    other_rules: str = Field("", max_length=20000)
    playbook: Literal["auto", "harem_xuanhuan", "general"] = "auto"
    effort_preset: Literal["quick", "balanced", "premium", "custom"] = "balanced"
    max_rewrites: int = Field(2, ge=0, le=5)
    pitches: int = Field(2, ge=1, le=4)
    review_strictness: Literal["lenient", "standard", "strict"] = "standard"
    volume_audit: bool = True
    volume_approval: bool = True
    chapters_approval: bool = False
    # 每一篇开写前先给我确认；不参与力度预设和提示词规矩
    segment_approval: bool = True
    trial_read: bool = True


PRESETS = {
    "quick": dict(max_rewrites=1, pitches=1, volume_audit=False, review_strictness="lenient"),
    "balanced": dict(max_rewrites=2, pitches=2, volume_audit=True, review_strictness="standard"),
    "premium": dict(max_rewrites=3, pitches=3, volume_audit=True, review_strictness="strict"),
}


def default_settings() -> dict:
    return BookSettings().model_dump()


def settings_of(book) -> dict:
    # 缺少模式的历史书沿用旧流程；新默认只在创建新书时复制。
    return {**default_settings(), "setup_mode": "oneshot", **(book.settings or {})}


def merge_settings(current: dict | None, changes: dict) -> dict:
    merged = {**default_settings(), **(current or {}), **changes}
    merged = BookSettings.model_validate(merged).model_dump()
    preset = changes.get("effort_preset")
    if isinstance(preset, str) and preset in PRESETS:
        merged.update(PRESETS[preset])
    elif any(k in changes for k in PRESETS["balanced"]):
        merged["effort_preset"] = "custom"
    return BookSettings.model_validate(merged).model_dump()


def compile_rules(settings: dict | BookSettings | None, *, title: bool = False) -> str:
    """Compile only present values; do not inject defaults into an empty input.

    书名规矩只在要起书名时带（新建页起草、以前的开书流程）：书有了名字以后写正文、审稿、排大纲都用不上。"""
    s = settings.model_dump() if isinstance(settings, BookSettings) else settings or {}
    lines = []
    title_rule = {
        "short": "2-6 个字的经典短书名，像《逆天邪神》《斗破苍穹》，不要用「主标题：副标题」的长书名。",
        "tomato": "番茄式长书名，「主题：一句话卖点」的格式，例如《苟道邪尊：平时低调发育，战时越境秒杀》。",
        "custom": s.get("title_custom", "").strip(),
    }.get(s.get("title_style"), "")
    if title and title_rule:
        lines.append(f"书名：{title_rule}")
    person = {
        "first": "全书用第一人称（「我」）叙述。",
        "second": "全书用第二人称（「你」）叙述。",
        "third": "全书用第三人称叙述。",
    }.get(s.get("person"), "")
    if person:
        lines.append(f"人称：{person}")
    intimacy = {
        "heart": "只写心动、暧昧和情感拉扯，不写亲吻以上的身体接触。",
        "fade": "可以写亲吻和拥抱，再进一步就一笔带过，不写露骨描写。",
        "custom": s.get("intimacy_custom", "").strip(),
    }.get(s.get("intimacy"), "")
    if intimacy:
        lines.append(f"亲密戏：{intimacy}")
    if s.get("chapter_words"):
        lines.append(f"每章约 {s['chapter_words']} 字。")
    other = s.get("other_rules") or ""
    lines.extend(line for line in other.splitlines() if line.strip())
    return "【这本书的写作规矩】\n" + "\n".join(f"- {line}" for line in lines) if lines else ""


def strictness_text(value: str) -> str:
    return {
        "lenient": "审稿尺度：宽松。只有章纲关键内容缺失、人物严重崩坏、逻辑硬伤才判退，其余问题记下即可。",
        "strict": "审稿尺度：严格。出现一条中等问题就判退，文字层面的明显毛病也要指出。",
    }.get(value, "")
