"""F7 · silent failure 三族判据 + 反例钉子（卡 185 / T-G285）。

依据 [arXiv:2509.14347]：失败主题 = 制品操作错误 28% · 缓存错误 23% · 被忽略的退出码 18%。
三族各有判据 + 反例钉子（故意造坏 ⇒ 必须抛 SilentFailureError）。
"""

from __future__ import annotations

import pytest

from framework.selection import (
    SilentFailureError,
    check_artifact_op,
    check_cache_stale,
    check_ignored_exit_code,
)


# -- 族一 · 被忽略的退出码 --------------------------------------------------
def test_f7_ignored_exit_code_pass_is_red():
    """★ 反例钉子：exit_code=3 不在 exit_ok 却判 pass ⇒ 红。"""
    with pytest.raises(SilentFailureError, match="被忽略的退出码"):
        check_ignored_exit_code(exit_code=3, exit_ok=(0,), verdict="pass")


def test_f7_ignored_exit_code_ok_when_fail():
    """正向：退出码不在 exit_ok 且判 fail ⇒ 不抛（fail 是诚实的）。"""
    check_ignored_exit_code(exit_code=3, exit_ok=(0,), verdict="fail")


def test_f7_ignored_exit_code_ok_when_in_exit_ok():
    check_ignored_exit_code(exit_code=0, exit_ok=(0,), verdict="pass")


# -- 族二 · 缓存错误（stale）------------------------------------------------
def test_f7_cache_stale_is_red():
    """★ 反例钉子：reused=True 但 input_hash ≠ prev_hash ⇒ 红。"""
    with pytest.raises(SilentFailureError, match="缓存 stale"):
        check_cache_stale(reused=True, input_hash="aaa", prev_hash="bbb")


def test_f7_cache_ok_when_hash_matches():
    check_cache_stale(reused=True, input_hash="aaa", prev_hash="aaa")


def test_f7_cache_ok_when_not_reused():
    check_cache_stale(reused=False, input_hash="aaa", prev_hash="bbb")


# -- 族三 · 制品（派生物）操作 ----------------------------------------------
def test_f7_artifact_not_committed_is_red():
    """★ 反例钉子：声明的制品没进提交/输入表 ⇒ 红。"""
    with pytest.raises(SilentFailureError, match="制品未登记"):
        check_artifact_op(
            emits=("sarif",),
            committed_files=["src/a.py"],
            artifact_path="reports/scan.sarif",
        )


def test_f7_artifact_ok_when_committed():
    check_artifact_op(
        emits=("sarif",),
        committed_files=["reports/scan.sarif"],
        artifact_path="reports/scan.sarif",
    )


def test_f7_artifact_noop_when_no_emits():
    check_artifact_op(emits=(), committed_files=[], artifact_path="x")
