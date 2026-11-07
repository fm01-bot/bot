from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import discord


class PageButton(discord.ui.Button["PaginationView"]):
	"""Button representing an action on a PaginationView."""

	def __init__(
		self,
		*,
		style: discord.ButtonStyle = discord.ButtonStyle.secondary,
		label: str | None = None,
		emoji: str | None = None,
		custom_id: str | None = None,
		disabled: bool = False,
		action: str,
	):
		super().__init__(style=style, label=label, emoji=emoji, custom_id=custom_id, disabled=disabled)
		self.action = action

	async def callback(self, interaction: discord.Interaction) -> None:
		assert self.view is not None
		await self.view.handle_button_click(interaction, self.action)


class PaginationView(discord.ui.LayoutView):
	"""Reusable Discord Components V2 pagination layout view."""

	message: discord.Message | None = None

	def __init__(
		self,
		pages: Sequence[discord.Embed] | None = None,
		*,
		author_id: int | None = None,
		timeout: float | None = 180.0,
		page_callback: Callable[[int], Awaitable[dict[str, Any] | discord.Embed]] | None = None,
		total_pages: int | None = None,
		start_page: int = 0,
	) -> None:
		super().__init__(timeout=timeout)
		self.pages: Sequence[discord.Embed] = pages or []
		self.page_callback = page_callback
		self.author_id = author_id
		self.total_pages = total_pages if total_pages is not None else len(self.pages)
		self.current_page = max(0, min(start_page, max(0, self.total_pages - 1)))

		self.prev_button = PageButton(
			style=discord.ButtonStyle.secondary,
			emoji="◀",
			custom_id="pagination:prev",
			disabled=(self.current_page == 0),
			action="prev",
		)
		self.indicator_button = PageButton(
			style=discord.ButtonStyle.secondary,
			label=f"{self.current_page + 1}/{max(1, self.total_pages)}",
			custom_id="pagination:indicator",
			disabled=True,
			action="indicator",
		)
		self.next_button = PageButton(
			style=discord.ButtonStyle.secondary,
			emoji="▶",
			custom_id="pagination:next",
			disabled=(self.current_page >= self.total_pages - 1),
			action="next",
		)

		self.action_row = discord.ui.ActionRow(self.prev_button, self.indicator_button, self.next_button)
		self.add_item(self.action_row)

	def update_buttons(self) -> None:
		"""Updates button labels and disabled states according to the current page."""
		self.prev_button.disabled = self.current_page <= 0
		self.next_button.disabled = self.current_page >= self.total_pages - 1
		self.indicator_button.label = f"{self.current_page + 1}/{max(1, self.total_pages)}"

	async def get_page_payload(self, page_index: int) -> dict[str, Any]:
		"""Returns the message kwargs for a given page index."""
		if self.page_callback:
			res = await self.page_callback(page_index)
			if isinstance(res, discord.Embed):
				return {"embeds": [res], "view": self}
			res_dict = dict(res)
			res_dict["view"] = self
			return res_dict
		if self.pages:
			return {"embeds": [self.pages[page_index]], "view": self}
		return {"view": self}

	async def handle_button_click(self, interaction: discord.Interaction, action: str) -> None:
		"""Handles previous / next button interactions."""
		if self.author_id is not None and interaction.user.id != self.author_id:
			return

		if action == "prev" and self.current_page > 0:
			self.current_page -= 1
		elif action == "next" and self.current_page < self.total_pages - 1:
			self.current_page += 1

		self.update_buttons()
		payload = await self.get_page_payload(self.current_page)
		await interaction.response.edit_message(**payload)

	async def on_timeout(self) -> None:
		"""Disables all navigation buttons upon interaction timeout."""
		self.prev_button.disabled = True
		self.next_button.disabled = True
		if self.message:
			try:
				await self.message.edit(view=self)
			except (discord.HTTPException, AttributeError):
				pass
