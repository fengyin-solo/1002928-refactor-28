"""运营概览归一：共用口径、首页与明细同数、重算幂等、历史看板留档。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import app
from app.services import metrics

client = TestClient(app)


def test_home_and_detail_share_the_same_numbers() -> None:
    overview = client.get("/api/overview").json()
    assert [card["label"] for card in overview["cards"]] == ["业务模块", "今日新增", "待处理", "异常量"]
    modules = overview["modules"]
    assert modules, "汇总表不应为空"
    for row in modules:
        detail = client.get(f"/api/overview/modules/{row['name']}").json()
        assert detail == row, f"{row['name']} 首页与明细不一致"
    # 卡片由各模块汇总行向上加总，字段名不动
    assert overview["cards"][1]["value"] == sum(row["created"] for row in modules)
    assert overview["cards"][2]["value"] == sum(row["pending"] for row in modules)
    assert overview["cards"][3]["value"] == sum(row["abnormal"] for row in modules)


def test_unknown_module_metrics_returns_404() -> None:
    response = client.get("/api/overview/modules/not-a-module")
    assert response.status_code == 404


def test_repeated_submit_of_same_batch_does_not_double_count() -> None:
    before = client.get("/api/overview").json()
    first = client.post("/api/overview/recompute", json={"batch_id": "batch-dup"}).json()
    assert first["ok"]
    again = client.post("/api/overview/recompute", json={"batch_id": "batch-dup"}).json()
    assert again["ok"]
    assert "未重复" in again["message"]
    after = client.get("/api/overview").json()
    assert after["modules"] == before["modules"], "同一批明细重复提交后台数叠了"
    assert first["entry"]["modules"] == again["entry"]["modules"]


def test_recompute_replaces_instead_of_accumulating() -> None:
    client.post("/api/overview/recompute", json={"batch_id": "batch-r1"})
    client.post("/api/overview/recompute", json={"batch_id": "batch-r2"})
    overview = client.get("/api/overview").json()
    assert overview["cards"][2]["value"] == sum(row["pending"] for row in overview["modules"])
    summary = client.post("/api/overview/recompute", json={"batch_id": "batch-r2"}).json()["entry"]
    assert summary["modules"] == overview["modules"]


def test_history_snapshots_keep_their_own_version() -> None:
    snapshots = client.get("/api/overview/snapshots").json()["items"]
    versions = {item["version"] for item in snapshots}
    assert metrics.LEGACY_METRICS_VERSION in versions, "历史看板应按当时那一版保留"
    assert metrics.METRICS_VERSION in versions
    legacy_before = next(item for item in snapshots if item["version"] == metrics.LEGACY_METRICS_VERSION)
    client.post("/api/overview/recompute", json={"batch_id": "batch-later"})
    snapshots_after = client.get("/api/overview/snapshots").json()["items"]
    legacy_after = next(item for item in snapshots_after if item["version"] == metrics.LEGACY_METRICS_VERSION)
    assert legacy_after == legacy_before, "重算不应改写历史看板"


def test_new_entry_counts_toward_today_and_stays_consistent() -> None:
    before = client.get("/api/overview/modules/boiler").json()
    created = client.post("/api/boiler", json={"values": {
        "锅炉编号": "BOIL-TEST-1",
        "锅炉型号": "测试型号",
        "额定蒸发量": "1t/h",
    }}).json()
    assert created["ok"]
    after = client.get("/api/overview/modules/boiler").json()
    assert after["created"] == before["created"] + 1, "今日新增应按创建日期计入"
    assert after["pending"] == before["pending"] + 1
    overview_row = next(
        row for row in client.get("/api/overview").json()["modules"] if row["name"] == "boiler"
    )
    assert overview_row == after, "新增后首页与明细必须仍是同一个数"
