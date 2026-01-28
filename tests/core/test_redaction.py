from __future__ import annotations

import pytest

from retikon_core.redaction import redact_text


@pytest.mark.core
def test_redact_text_masks_common_pii():
    text = (
        "Email test@example.com or call 415-555-1234. "
        "SSN 123-45-6789 card 4242 4242 4242 4242."
    )
    redacted = redact_text(text, redaction_types=("pii",))
    assert "test@example.com" not in redacted
    assert "415-555-1234" not in redacted
    assert "123-45-6789" not in redacted
    assert "4242 4242 4242 4242" not in redacted
    assert "[REDACTED]" in redacted
