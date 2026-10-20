"""拆书的名单：每次从已读的逐章记录重算，不另外存状态。"""

from collections import Counter


class Roster:
    def __init__(self) -> None:
        self.people: list[dict] = []

    def shared(self) -> set[str]:
        seen = Counter(alias for person in self.people for alias in set(person["aliases"]))
        names = {person["name"] for person in self.people}
        return {alias for alias, count in seen.items() if count > 1 or alias in names}

    def find(self, name: str) -> dict | None:
        if not name:
            return None
        # 正式名字优先；共用叫法不能把两个人误并成一个。
        for person in self.people:
            if name == person["name"]:
                return person
        shared = self.shared()
        return next((p for p in self.people if name in p["aliases"] and name not in shared), None)

    def add(self, chapters: list[dict]) -> None:
        for chapter in sorted(chapters, key=lambda c: c["index"]):
            for person in chapter.get("people", []):
                name, was = person["name"].strip(), person.get("was", "").strip()
                if not name:
                    continue
                hit, old = self.find(name), self.find(was)
                if old is not None and old is not hit:
                    if hit is not None:
                        self.people.remove(old)
                        hit["aliases"] += [
                            n for n in [old["name"], *old["aliases"]] if n != hit["name"] and n not in hit["aliases"]
                        ]
                        hit["chapters"] |= old["chapters"]
                        if (old["first"], old["order"]) < (hit["first"], hit["order"]):
                            hit["first"], hit["order"], hit["note"] = old["first"], old["order"], old["note"]
                    else:
                        old["aliases"].append(old["name"])
                        old["name"] = name
                        hit = old
                if hit is None:
                    hit = {
                        "name": name,
                        "aliases": [],
                        "note": person["shown"][:50],
                        "first": chapter["index"],
                        "order": len(self.people),
                        "chapters": set(),
                    }
                    self.people.append(hit)
                hit["chapters"].add(chapter["index"])
                for alias in person.get("also_called", []):
                    alias = alias.strip()
                    if alias and alias != hit["name"] and alias not in hit["aliases"]:
                        hit["aliases"].append(alias)
            self.people.sort(key=lambda p: (p["first"], p["order"]))

    def text(self, source: str | None = None) -> str:
        shared = self.shared()
        people = self.people
        if source is not None:
            main = sorted(people, key=lambda p: (-len(p["chapters"]), p["first"], p["order"]))[:12]
            people = [
                p
                for p in people
                if p in main or any(n in source for n in [p["name"], *(a for a in p["aliases"] if a not in shared)])
            ]
        return (
            "\n".join(
                f"- {p['name']}｜别称：{'、'.join(a for a in p['aliases'] if a not in shared) or '无'}｜{p['note']}"
                for p in people
            )
            or "（还没有）"
        )
