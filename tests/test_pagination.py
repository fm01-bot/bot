from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from helpers.pagination import PaginationView


@pytest.fixture
def mock_embeds():
	return [discord.Embed(title=f"Page {i}") for i in range(1, 4)]


@pytest.mark.asyncio
async def test_pagination_view_navigation(mock_embeds):
	view = PaginationView(pages=mock_embeds, author_id=123)

	assert view.current_page == 0
	assert view.total_pages == 3
	assert view.prev_button.disabled is True
	assert view.next_button.disabled is False
	assert view.indicator_button.label == "1/3"

	# Mock interaction for next button
	interaction = MagicMock()
	interaction.user.id = 123
	interaction.response = MagicMock()
	interaction.response.edit_message = AsyncMock()

	# Click Next
	await view.handle_button_click(interaction, "next")
	assert view.current_page == 1
	assert view.prev_button.disabled is False
	assert view.next_button.disabled is False
	assert view.indicator_button.label == "2/3"
	interaction.response.edit_message.assert_called_once()

	# Click Next again -> Page 3
	interaction.response.edit_message.reset_mock()
	await view.handle_button_click(interaction, "next")
	assert view.current_page == 2
	assert view.prev_button.disabled is False
	assert view.next_button.disabled is True
	assert view.indicator_button.label == "3/3"

	# Click Prev -> Page 2
	interaction.response.edit_message.reset_mock()
	await view.handle_button_click(interaction, "prev")
	assert view.current_page == 1
	assert view.prev_button.disabled is False
	assert view.next_button.disabled is False
	assert view.indicator_button.label == "2/3"


@pytest.mark.asyncio
async def test_pagination_view_unauthorized(mock_embeds):
	view = PaginationView(pages=mock_embeds, author_id=123)

	interaction = MagicMock()
	interaction.user.id = 999  # Unauthorized user
	interaction.response = MagicMock()
	interaction.response.send_message = AsyncMock()

	await view.handle_button_click(interaction, "next")
	# Should not advance page
	assert view.current_page == 0
	interaction.response.send_message.assert_called_once_with(
		"You cannot interact with this pagination menu.", ephemeral=True
	)


@pytest.mark.asyncio
async def test_pagination_view_timeout(mock_embeds):
	view = PaginationView(pages=mock_embeds, author_id=123)
	msg = MagicMock()
	msg.edit = AsyncMock()
	view.message = msg

	await view.on_timeout()
	assert view.prev_button.disabled is True
	assert view.next_button.disabled is True
	msg.edit.assert_called_once_with(view=view)
