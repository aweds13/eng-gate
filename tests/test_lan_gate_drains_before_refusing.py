'''配对门拒绝之前先把请求体读完（卡 E141 · T-AG650）。

## 为什么有这张测试

云门禁 v12 那趟 `web_live` 门红在 `[FAIL] 局域网：有一步没等到（POST /api/sync/import）` +
`ConnectionAbortedError: [WinError 10053]`，而同一刻服务端日志写的是 `status 401` ——
服务端**回了 401**，客户端**没读到**。成因是 `lan_gate` 在拒绝分支直接 `return JSONResponse(...)`，
一个字节的 body 都没读；客户端还在发的时候服务端就 close，TCP 栈回 RST，
客户端拿到 10053（RFC 9112「连接管理」那段写的就是这件事）。

卡 E85（`test_web_live_read_failure_is_not_401.py`）只保证「门说的是实话」，明文不许改服务端；
这张文件管的是服务端自己：**拒绝可以，但要有界地把话说完再挂断**。

## 判据的形状

不起真服务也能量：`httpx.ASGITransport` + 生成器 body，把「body 被消费到第几块」记在客户端一侧。
改前 `chunks_eaten == 0`，改后等于总块数（`gates/diag/_tmp/_probe_asgi_drain.py` 的读数）。
最后一条用真 socket + 真端口复核一次；拿不到局域网地址时 skip —— 前三条不依赖网络。
'''

from __future__ import annotations

import asyncio
import contextlib
import socket
import threading
import time
from typing import TYPE_CHECKING

import httpx
import pytest

from timeflow.api.app import create_app
from timeflow.core import lan as lan_mod
from timeflow.core import syncpack
from timeflow.core import tasks as tm
from timeflow.storage import db as db_mod

if TYPE_CHECKING:
    from pathlib import Path

PHONE = ('192.168.1.50', 51234)   # 同一 WiFi 上的手机（与 tests/test_lan_pairing_line.py 同口径）
CHUNKS = 10
CHUNK_BYTES = 300


def _body(eaten: list[int]):
    '''逐块吐的请求体；每吐一块记一笔 —— 这就是「服务端读到第几块」的量尺。'''

    async def gen():
        for i in range(CHUNKS):
            eaten.append(i)
            await asyncio.sleep(0)
            yield b'x' * CHUNK_BYTES

    return gen()


def _app(tmp_path: Path, name: str = 'lan.db'):
    return create_app(str(tmp_path / name), allow_lan=True)


def _post_chunked(app, path: str = '/api/sync/import', headers: dict | None = None):
    '''在 ASGI 层打一次分块 POST，返回 (响应, 被消费的块数)。'''

    async def run():
        eaten: list[int] = []
        transport = httpx.ASGITransport(app=app, client=PHONE)
        async with httpx.AsyncClient(transport=transport, base_url='http://lan') as client:
            got = await client.post(
                path,
                content=_body(eaten),
                headers={'Content-Type': 'application/json', **(headers or {})},
            )
        return got, len(eaten)

    return asyncio.run(run())


async def _post_json(app, payload: dict, headers: dict):
    transport = httpx.ASGITransport(app=app, client=PHONE)
    async with httpx.AsyncClient(transport=transport, base_url='http://lan') as client:
        return await client.post('/api/sync/import', json=payload, headers=headers)


def _phone_pack(tmp_path: Path) -> dict:
    '''造一份真包（用真的 build_pack，不手搓字段）。'''
    other = db_mod.connect(str(tmp_path / 'other.db'))
    try:
        tm.create_task(other, '手机上记的', is_myday=True)
        return syncpack.build_pack(other)
    finally:
        other.close()


@pytest.fixture(autouse=True)
def _clean_throttle():
    '''失败节流是进程级全局状态（lan._fails）：每条用例前后都清干净。'''
    lan_mod.reset_failures()
    yield
    lan_mod.reset_failures()


def test_unpaired_upload_refuses_only_after_the_body_is_read(tmp_path) -> None:  # type: ignore[no-untyped-def]
    '''没配对 ⇒ 仍 401，但**先读完 body 再拒**（改前这里是 0 块）。'''
    got, eaten = _post_chunked(_app(tmp_path))
    assert got.status_code == 401
    assert eaten == CHUNKS, f'拒绝前只读了 {eaten}/{CHUNKS} 块 body —— 客户端可能被 RST'
    assert '配对' in got.json()['detail']


def test_paired_upload_still_receives_the_whole_body(tmp_path) -> None:  # type: ignore[no-untyped-def]
    '''★ 放行分支不许提前 drain：配对过的设备仍能传完整的包（合并结果照旧）。'''
    path = str(tmp_path / 'paired.db')
    app = create_app(path, allow_lan=True)
    code = lan_mod.code(db_mod.thread_local(path))
    pack = _phone_pack(tmp_path)

    got = asyncio.run(_post_json(app, {'pack': pack}, {'X-Timeflow-Pair': code}))
    assert got.status_code == 200, got.text
    assert got.json()['totals']['inserted'] == 1


def test_locked_device_is_still_429_and_still_drained(tmp_path) -> None:  # type: ignore[no-untyped-def]
    '''连错到锁定 ⇒ 仍是 429、detail 仍是原话，且同样先读完 body。'''
    for _ in range(lan_mod.MAX_FAILS):
        lan_mod.note_failure(PHONE[0])
    got, eaten = _post_chunked(_app(tmp_path, 'locked.db'))
    assert got.status_code == 429
    assert eaten == CHUNKS
    assert '秒再试' in got.json()['detail']
    assert set(got.json()) == {'detail'}


def test_a_slow_body_on_the_lan_address_gets_401_not_a_reset(tmp_path) -> None:  # type: ignore[no-untyped-def]
    '''真 socket 复核：慢速分块上传（客户端 bind 到本机局域网地址）读到 401，不是 10053。'''
    import uvicorn

    port = _free_port()
    addresses = [a for a in lan_mod.local_addresses(port) if '127.' not in a]
    if not addresses:
        pytest.skip('这台机器拿不到局域网地址 —— 前三条判据不依赖它')
    host = addresses[0].split('//')[1].split(':')[0]

    app = _app(tmp_path, 'slow.db')
    server = uvicorn.Server(uvicorn.Config(app, host='0.0.0.0', port=port, log_level='warning'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        status_line = _slow_upload(host, port)
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    assert '401' in status_line, status_line


def _free_port() -> int:
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def _slow_upload(host: str, port: int) -> str:
    '''先发头，再每 200 B 一包慢慢把 body 发完，最后读状态行。

    客户端 socket 先 bind 到本机局域网地址：否则来源是回环，is_loopback 会直接放行，
    这条路根本进不到配对门（探针里实测过：回环拿到 422，复现不出 10053）。
    '''
    body = b'x' * 3000
    with contextlib.closing(socket.socket()) as sock:
        sock.bind((host, 0))
        sock.settimeout(20)
        sock.connect((host, port))
        head = (
            f'POST /api/sync/import HTTP/1.1\r\nHost: {host}\r\n'
            'Content-Type: application/json\r\n'
            f'Content-Length: {len(body)}\r\nConnection: close\r\n\r\n'
        )
        sock.sendall(head.encode())
        sent = 0
        while sent < len(body):
            sock.sendall(body[sent:sent + 200])
            sent += 200
            time.sleep(0.002)
        return sock.recv(200).split(b'\r\n')[0].decode('latin1')
