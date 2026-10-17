"""保留旧书写作继续使用的秘密、分卷和揭晓引用规则。"""

from copy import deepcopy

import pytest

from app.agents.setup_puzzle import clean_reveals, normalize_secrets, normalize_volumes


@pytest.fixture(autouse=True)
def glossary_names(monkeypatch):
    monkeypatch.setattr(
        "app.agents.glossary.terms", lambda: [(name, "解释") for name in ("欲扬先抑", "打脸三拍", "信息差", "伏笔回收")]
    )


def node(id_, kind="milestone", status="pencil", volume=1):
    return {
        "id": id_,
        "kind": kind,
        "title": str(id_ or "新增"),
        "event": "原事件",
        "prerequisite": "原前提",
        "consequence": "原后果",
        "volume": volume,
        "status": status,
        "origin": "author",
        "editor_note": "作者批注",
        "techniques": ["欲扬先抑"],
    }


def test_lore_validates_names_nodes_and_preserves_secret_number():
    raw = {
        "characters": [{"name": "林岚"}],
        "anchors": [
            {"character": "林岚", "node": 2, "kind": "高光"},
            {"character": "路人", "node": 1},
            {"character": "林岚", "node": 99},
        ],
        "secrets": [
            {"title": "身份", "truth": "皇族", "knowers": ["林岚", "不存在", "林岚"], "node": 2},
            {"title": "往事", "truth": "逃亡", "knowers": [], "node": 99},
        ],
    }
    original = deepcopy(raw)
    nodes = [node("开篇", "opening"), node("高光")]
    secrets, dropped = normalize_secrets(
        raw["secrets"], raw["characters"], nodes, [{"seq": 7, "title": "身份", "status": "public"}]
    )
    volumes, _, notes = normalize_volumes({"anchors": raw["anchors"]}, {"nodes": nodes}, raw["characters"], 1)
    assert raw == original
    assert dropped == 1
    assert notes == [{"question": "cast", "text": "已丢弃 2 条不合法的人物锚点。"}]
    assert volumes["anchors"] == [{"character": "林岚", "node": 2, "kind": "高光", "node_title": "高光"}]
    assert [item["seq"] for item in secrets] == [7, 8]
    assert secrets[0]["knowers"] == [{"name": "林岚", "since_chapter": None, "how": "开书设定"}]
    assert secrets[0]["status"] == "public" and secrets[1]["node"] == 0


def test_volumes_normalization_never_changes_pin():
    nodes = [node("a", "opening"), node("b", status="pinned", volume=2), node("c", "ending", volume=5)]
    segment = {"nodes": nodes, "expectations": [{"node": 2, "plant_volume": 99, "payoff_volume": 99}]}
    part = {
        "volumes": [
            {"index": 4, "target_node": 3, "chapter_count": -1},
            {"index": 1, "target_node": 99},
            {"index": 3, "target_node": 2},
        ]
    }
    before = deepcopy(segment)
    cleaned, changed, notes = normalize_volumes(part, segment, [], 1)
    assert segment == before and changed["nodes"][1] == before["nodes"][1]
    assert changed["nodes"][2]["volume"] == 5
    assert [v["index"] for v in cleaned["volumes"]] == [1, 2, 3]
    assert [v["target_node"] for v in cleaned["volumes"]] == [2, 2, 2]
    assert [v["reaches_node"] for v in cleaned["volumes"]] == [False, False, True]
    assert all(v["chapter_count"] == 0 for v in cleaned["volumes"])
    assert any("铁钉" in item["text"] for item in notes)
    assert changed["expectations"][0]["plant_volume"] == changed["expectations"][0]["payoff_volume"] == 3


def test_reveals_are_filtered_against_actual_secret_codes():
    units = [
        {
            "index": 1,
            "techniques": ["表外", "信息差"],
            "reveals": [
                {"ref": "S1", "to": "读者", "how": "揭晓"},
                {"ref": "s2", "to": "林岚"},
                {"ref": "S9", "to": "众人"},
                {"ref": "F1"},
                {"ref": "前文S1"},
            ],
        }
    ]
    original = deepcopy(units)
    clean = clean_reveals(units, [{"seq": 1}, {"seq": 2}])
    assert units == original
    assert [item["ref"] for item in clean[0]["reveals"]] == ["S1", "S2"]
    assert clean[0]["techniques"] == ["信息差"]
    assert clean_reveals([{"index": 1}], []) == [{"index": 1}]
