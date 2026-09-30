from __future__ import annotations

from unittest.mock import patch

from helpers.random_helper import randbool


def test_randbool():
	with patch("random.random", return_value=0.3):
		assert randbool() is True

	with patch("random.random", return_value=0.7):
		assert randbool() is False

	with patch("random.random", return_value=0.5):
		assert randbool() is False

	# Verify returns a boolean
	assert isinstance(randbool(), bool)
