import base64
import sys

import pytest

from radio import secret_store


def test_round_trip_or_refusal():
    if sys.platform == "win32":
        sealed = secret_store.seal("my-token")
        assert "my-token" not in sealed
        assert secret_store.unseal(sealed) == "my-token"
    else:
        with pytest.raises(NotImplementedError):
            secret_store.seal("my-token")


def test_unseal_rejects_garbage():
    garbage = base64.b64encode(b"not a dpapi blob").decode()
    expected = OSError if sys.platform == "win32" else NotImplementedError
    with pytest.raises(expected):
        secret_store.unseal(garbage)
