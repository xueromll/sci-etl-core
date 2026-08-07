from __future__ import annotations

import pytest

from sci_etl_core import _atomic_io
from sci_etl_core._atomic_io import atomic_write_text


class TestReplaceRetry:
    def test_transient_permission_error_is_retried(self, tmp_path, mocker):
        real_replace = _atomic_io.os.replace
        attempts = {"n": 0}

        def held_twice(source, target):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise PermissionError("held by another process")
            real_replace(source, target)

        mocker.patch.object(_atomic_io.os, "replace", side_effect=held_twice)
        sleep = mocker.patch.object(_atomic_io.time, "sleep")
        destination = tmp_path / "out.txt"
        atomic_write_text(destination, "payload")
        assert destination.read_text(encoding="utf-8") == "payload"
        assert [call.args[0] for call in sleep.call_args_list] == [0.05, 0.1]

    def test_persistent_permission_error_is_raised_and_temp_file_removed(self, tmp_path, mocker):
        mocker.patch.object(_atomic_io.os, "replace", side_effect=PermissionError("locked"))
        sleep = mocker.patch.object(_atomic_io.time, "sleep")
        with pytest.raises(PermissionError, match="locked"):
            atomic_write_text(tmp_path / "out.txt", "payload")
        assert sleep.call_count == 5
        assert list(tmp_path.iterdir()) == []
