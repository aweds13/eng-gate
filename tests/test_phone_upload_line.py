"""G 批 · T-G15：手机**直接上传**同步包（跨端场景 ① 的"少一步"）。

原来的路：手机导出文件 → 拷到电脑 → 电脑上选文件导入。
现在的路：**手机连着电脑时，直接把包传到电脑**（同一个格式、同一套合并规则）。

口径（没有新增需要拍板的东西）：
- 走的是**同一条合并路径**（`POST /api/sync/import` → `syncpack.plan_merge`）——
  手机依旧**不判谁新谁旧**（那套规则只有一处实现，在电脑上）；
- 手机传的是**包内容**（`pack`），不是路径；`path` 是"在电脑上读一个文件"的便利口子，
  **只留给本机**（否则同一 WiFi 上配对过的设备就能让电脑去读盘上任意路径）；
- 传成功后再问要不要清队列；**传失败绝不清空**；
- 重复传是安全的（电脑那边合并幂等），但每次都会在冲突日志里留一行。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from timeflow.api.app import create_app
from timeflow.core import syncpack
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod

WEB_INDEX = Path(__file__).resolve().parent.parent / "src" / "web" / "index.html"
LAN_DEVICE = ("172.16.0.9", 55123)   # 假装是同一 WiFi 上的手机


def _phone_pack(tmp_path) -> dict:  # type: ignore[no-untyped-def]
    """造一份"另一台设备"的包（用真的 `build_pack` —— 不手搓字段，免得测了个假包）。"""
    other = db_mod.connect(str(tmp_path / "other.db"))
    try:
        tm.create_task(other, "手机上记的", is_myday=True)
        tm.create_task(other, "手机上记的第二件")
        return syncpack.build_pack(other)
    finally:
        other.close()


def _paired_clients(tmp_path):  # type: ignore[no-untyped-def]
    """返回（本机页面、局域网设备）两个客户端 + 配对码 —— 同一个 app、同一个库。

    注意 `TestClient` 默认的来源地址是 `testclient`（**不是回环**），而配对码只发给回环请求，
    所以"本机页面"这个客户端必须显式给一个 `127.0.0.1` 的来源地址。
    """
    app = create_app(str(tmp_path / "upload.db"), allow_lan=True)
    local = TestClient(app, client=("127.0.0.1", 51999))
    code = local.get("/api/settings/lan").json()["code"]
    assert code, "本机页面应该能拿到配对码"
    remote = TestClient(app, client=LAN_DEVICE)
    return local, remote, code


def test_lan_device_can_upload_pack(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """配对过的局域网设备**能把包内容传上来** —— 这就是"手机直接上传"那条路。"""
    local, remote, code = _paired_clients(tmp_path)
    pack = _phone_pack(tmp_path)
    auth = {"X-Timeflow-Pair": code}

    got = remote.post("/api/sync/import", json={"pack": pack}, headers=auth)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["totals"]["inserted"] == 2
    assert body["from_device"] == pack["device_id"]
    assert [t["title"] for t in local.get("/api/tasks").json()] == [
        "手机上记的", "手机上记的第二件",
    ]

    # 再传一次：幂等（同一份包不该重复计数）—— 手机重试/连点都安全
    again = remote.post("/api/sync/import", json={"pack": pack}, headers=auth)
    assert again.status_code == 200
    assert again.json()["totals"]["inserted"] == 0


def test_lan_page_cannot_point_at_a_local_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """★ 边界：**从局域网地址打开的那个页面只能传内容，不能指路径**。

    `path` 是"在电脑上读一个文件"的口子。判据看的是**页面的来源**（Origin），不是 TCP 来源：
    - 本机页面（回环 Origin）与**没有 Origin 的本机脚本/命令行**照旧可以指路径
      （设置页「先预览」就是这条路）；
    - 从局域网地址打开的页面（手机、或别人电脑上的浏览器）不行 —— 配对码证明的是"你是本人"，
      不是"你可以让这台电脑去读盘上任意一个路径"。
    """
    local, remote, code = _paired_clients(tmp_path)
    pack_file = tmp_path / "phone.json"
    pack_file.write_text("{}", encoding="utf-8")
    auth = {"X-Timeflow-Pair": code, "Origin": f"http://{LAN_DEVICE[0]}:8520"}

    denied = remote.post("/api/sync/import", json={"path": str(pack_file)}, headers=auth)
    assert denied.status_code == 403
    assert "文件路径" in denied.json()["detail"]

    # 本机自己指路径：照旧（这是设置页「先预览」与命令行那条路）
    ok = local.post("/api/sync/import", json={"path": str(pack_file)})
    assert ok.status_code == 400    # 空 {} 不是我们的包 → 400（说明**读到了文件**，只是格式不对）
    # 没有 Origin 的本机脚本（curl / 命令行）也照旧
    scripted = remote.post("/api/sync/import", json={"path": str(pack_file)},
                           headers={"X-Timeflow-Pair": code})
    assert scripted.status_code == 400


def test_upload_needs_pairing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """没配对 → 连合并都进不来（那道门照旧管着这条路）。"""
    _local, remote, _code = _paired_clients(tmp_path)
    pack = _phone_pack(tmp_path)
    assert remote.post("/api/sync/import", json={"pack": pack}).status_code == 401


def test_uploaded_pack_is_merged_by_the_desktop_rules(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """上传与"导出文件再导入"走的是**同一套判断**：同一份包，两条路的报告一致。"""
    local, remote, code = _paired_clients(tmp_path)
    pack = _phone_pack(tmp_path)

    over_lan = remote.post("/api/sync/import", json={"pack": pack},
                           headers={"X-Timeflow-Pair": code}).json()
    # 同一份包再从本机走一遍（走的是"内容"这条入口，不是路径）：应当全部已存在
    local_again = local.post("/api/sync/import", json={"pack": pack}).json()
    assert over_lan["totals"]["inserted"] == 2
    assert local_again["totals"]["inserted"] == 0
    assert local_again["totals"]["kept"] == 2          # 一样的内容 → 原样保留、不覆盖
    assert set(local_again["tables"]) == set(over_lan["tables"])

    # **不静默覆盖**：本地改过之后再传同一份包 → 保留本地那份，并逐条记进冲突日志
    first_id = local.get("/api/tasks").json()[0]["id"]
    local.patch(f"/api/tasks/{first_id}", json={"title": "我在电脑上改过的标题"})
    third = local.post("/api/sync/import", json={"pack": pack}).json()
    assert third["totals"]["kept"] >= 1
    assert local.get(f"/api/tasks/{first_id}").json()["title"] == "我在电脑上改过的标题"
    logs = local.get("/api/sync/logs").json()
    assert any("保留本地" in str(row.get("result") or "") for row in logs), (
        "上传过来的包和你本地改过的东西撞上时必须留痕（手机上重复传不会无声无息）"
    )


def test_frontend_uploads_and_only_clears_after_success() -> None:
    """界面口径（护栏）：直接传到电脑那条路上，**失败不清队列**、成功才问要不要清。"""
    html = WEB_INDEX.read_text(encoding="utf-8")
    assert "async function offlineUpload()" in html and "'offline-upload':" in html
    fn = html.split("async function offlineUpload(){", 1)[1].split("\n}", 1)[0]
    assert "/api/sync/import" in fn and "pack:r.pack" in fn, (
        "上传必须走既有的合并接口、发的是包内容"
    )
    # T-G76：拒绝之前必须**真探一次**（`offlineConfirmed()`），而不是拿"上一次请求的结论"
    # （`offlineNow()`）直接挡住 —— 那个结论可能已经过期，会把一个能成的操作挡在门外。
    # 这条断言原来钉的正是后者（"offlineNow() in fn"），是**旧口径**，随 T-G76 一起更正。
    assert "offlineConfirmed()" in fn, "传之前要真探一次（不许拿过期的离线结论挡住）"
    assert "现在连不上电脑" in fn, "探不通时要说清为什么传不了（而不是让请求失败后猜）"
    assert "if(offlineNow()){" not in fn, "不许再拿提示当判据"
    assert "confirmAsk(" in fn, "传之前要说清代价（这条会合并进电脑的库）"
    # 清队列必须在成功之后、并且是**再问一次**：catch 里不许出现清空
    before, after = fn.split("await api('/api/sync/import'", 1)
    assert "clearQueue" not in before, "还没传成功就清队列 = 丢数据"
    assert "clearQueue" in after and "confirmAsk(" in after
    body = html.split("async function offlineUpload(){", 1)[1].split("async function ", 1)[0]
    assert "catch(e){return}" in body, "传失败要直接返回（api() 已经弹过后端原话）"
    # 离线引擎那边：打包函数要把 **pack 对象**一起给出来（不靠界面再反解一遍文本）
    offline_js = (WEB_INDEX.parent / "offline.js").read_text(encoding="utf-8")
    assert "return { pack: pack, text: packText(pack)" in offline_js
