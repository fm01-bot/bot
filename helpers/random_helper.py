"""Custom random functions."""

import random


def randbool() -> bool:
	"""
	Random boolean value, using ``random.random``.

	Returns
	-------
	bool
	    True if ``random.random`` is less than 0.5, False otherwise.
	"""
	return random.random() < 0.5


if __name__ == "__main__":
	print(randbool())
