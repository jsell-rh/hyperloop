from __future__ import annotations

from hyperloop.reconciliation.adapters.acpctl_platform_runner import _extract_result


class TestExtractResult:
    def test_extracts_last_text_message(self) -> None:
        events = "\n".join(
            [
                '{"type": "TEXT_MESSAGE_START", "messageId": "1"}',
                '{"type": "TEXT_MESSAGE_CONTENT", "messageId": "1", "delta": "Hello "}',
                '{"type": "TEXT_MESSAGE_CONTENT", "messageId": "1", "delta": "world"}',
                '{"type": "TEXT_MESSAGE_END", "messageId": "1"}',
            ]
        )

        result = _extract_result(events)

        assert result == "Hello world"

    def test_returns_last_message_when_multiple(self) -> None:
        events = "\n".join(
            [
                '{"type": "TEXT_MESSAGE_START", "messageId": "1"}',
                '{"type": "TEXT_MESSAGE_CONTENT", "messageId": "1", "delta": "first"}',
                '{"type": "TEXT_MESSAGE_END", "messageId": "1"}',
                '{"type": "TEXT_MESSAGE_START", "messageId": "2"}',
                '{"type": "TEXT_MESSAGE_CONTENT", "messageId": "2", "delta": "second"}',
                '{"type": "TEXT_MESSAGE_END", "messageId": "2"}',
            ]
        )

        result = _extract_result(events)

        assert result == "second"

    def test_returns_empty_string_when_no_events(self) -> None:
        assert _extract_result("") == ""

    def test_skips_non_json_lines(self) -> None:
        events = "\n".join(
            [
                "not json",
                '{"type": "TEXT_MESSAGE_START", "messageId": "1"}',
                '{"type": "TEXT_MESSAGE_CONTENT", "messageId": "1", "delta": "ok"}',
                '{"type": "TEXT_MESSAGE_END", "messageId": "1"}',
            ]
        )

        result = _extract_result(events)

        assert result == "ok"

    def test_handles_json_result_in_delta(self) -> None:
        events = "\n".join(
            [
                '{"type": "TEXT_MESSAGE_START", "messageId": "1"}',
                '{"type": "TEXT_MESSAGE_CONTENT", "messageId": "1", "delta": "[{\\"name\\": \\"Task 1\\"}]"}',
                '{"type": "TEXT_MESSAGE_END", "messageId": "1"}',
            ]
        )

        result = _extract_result(events)

        assert result == '[{"name": "Task 1"}]'
