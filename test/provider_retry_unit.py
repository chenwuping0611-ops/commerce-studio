"""Focused checks for one-operation provider retry semantics."""

from unittest.mock import patch

from applications.studio.provider_client import provider_retry_call


def main():
    calls = []

    def eventually_succeeds():
        calls.append(len(calls) + 1)
        if len(calls) < 4:
            raise RuntimeError("temporary provider failure")
        return "ok"

    with patch(
        "applications.studio.provider_client.time.sleep",
    ) as sleep:
        assert provider_retry_call(
            eventually_succeeds,
            operation_name="retry-unit",
        ) == "ok"
    assert calls == [1, 2, 3, 4]
    assert sleep.call_count == 3

    calls.clear()

    def accepted_then_fails():
        calls.append(1)
        error = RuntimeError("result persistence failed")
        error._upstream_accepted = True
        raise error

    with patch(
        "applications.studio.provider_client.time.sleep",
    ) as sleep:
        try:
            provider_retry_call(
                accepted_then_fails,
                operation_name="accepted-unit",
            )
        except RuntimeError as error:
            assert str(error) == "result persistence failed"
        else:
            raise AssertionError("accepted provider errors must not be retried")
    assert calls == [1]
    assert sleep.call_count == 0

    print("provider retry unit passed")


if __name__ == "__main__":
    main()
