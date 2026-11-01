from __future__ import annotations

from unittest.mock import MagicMock

import discord
import pytest
from args.guild import Guild
from args.member import Member
from args.user import User
from discord.ext import commands
from helpers.custom_response import KWARG_MAPPING, CustomResponse


@pytest.fixture
def mock_bot():
	bot = MagicMock()
	bot.debug = False
	bot.config.emojis = {"check": "✅", "x": "❌"}
	return bot


class TestCustomResponseEmbeds:
	def test_convert_embeds_single_embed(self, mock_bot):
		cr = CustomResponse(mock_bot)
		data = {
			"embed": {
				"title": "Test Title",
				"description": "Test Desc",
				"fields": [
					{"name": "Status", "value": "True"},
					{"name": "Failed", "value": "False"},
					{"name": "Ignored", "value": "None"},
					{"name": "Zero", "value": "0"},
					{"name": "Empty", "value": ""},
					{"name": "Valid", "value": "Regular value"},
				],
			}
		}

		result = cr.convert_embeds(data)
		assert "embed" not in result
		assert "embeds" in result
		assert len(result["embeds"]) == 1

		embed = result["embeds"][0]
		assert isinstance(embed, discord.Embed)
		assert embed.title == "Test Title"
		assert embed.description == "Test Desc"
		assert len(embed.fields) == 3
		assert embed.fields[0].value == "✅"
		assert embed.fields[1].value == "❌"
		assert embed.fields[2].value == "Regular value"

	def test_convert_embeds_too_many_embeds_raises(self, mock_bot):
		cr = CustomResponse(mock_bot)
		data = {"embeds": [{"title": f"Embed {i}"} for i in range(11)]}
		with pytest.raises(ValueError, match="The maximum number of embeds is 10"):
			cr.convert_embeds(data)

	def test_convert_embeds_non_dict_passthrough(self, mock_bot):
		cr = CustomResponse(mock_bot)
		assert cr.convert_embeds("just a string") == "just a string"
		assert cr.convert_embeds(123) == 123


class TestKwagMapping:
	def test_kwag_mapping_converters(self):
		assert discord.Guild in KWARG_MAPPING
		assert discord.Member in KWARG_MAPPING
		assert discord.User in KWARG_MAPPING
		assert KWARG_MAPPING[discord.Guild] == Guild.from_guild
		assert KWARG_MAPPING[discord.Member] == Member.from_member
		assert KWARG_MAPPING[discord.User] == User.from_user


class TestCustomResponseGetMessage:
	@pytest.mark.asyncio
	async def test_get_message_with_dictionary_localization(self, mock_bot):
		cr = CustomResponse(mock_bot)
		cr.update_localizations({"en": {"test": {"key": "Hello {author.name} in {guild.name}! Now: {now}"}}})

		guild = MagicMock(spec=discord.Guild)
		guild.id = 123
		guild.name = "My Guild"
		guild.member_count = 10
		guild.preferred_locale = "en"
		guild.roles = []
		guild.channels = []
		guild.emojis = ()
		guild.stickers = ()
		guild.icon = None
		guild.banner = None
		guild.splash = None
		guild.discovery_splash = None
		guild.description = None
		guild.owner = None
		guild.premium_subscription_count = 0
		guild.created_at = None
		guild.verification_level = discord.VerificationLevel.none
		guild.default_notifications = discord.NotificationLevel.all_messages
		guild.explicit_content_filter = discord.ContentFilter.disabled
		guild.mfa_level = discord.MFALevel.disabled
		guild.system_channel = None
		guild.rules_channel = None
		guild.public_updates_channel = None
		guild.afk_channel = None
		guild.afk_timeout = 300
		guild.vanity_url = None
		guild.premium_tier = 0
		guild.premium_subscribers = []
		guild.premium_subscriber_role = None
		guild.nsfw_level = discord.NSFWLevel.default
		guild.voice_channels = []
		guild.stage_channels = []
		guild.text_channels = []
		guild.categories = []
		guild.forums = []
		guild.threads = []
		guild.bitrate_limit = 96000.0
		guild.filesize_limit = 8388608
		guild.scheduled_events = []
		guild.shard_id = 0

		author = MagicMock(spec=discord.Member)
		author.guild = guild
		author.id = 456
		author.name = "bob"
		author.discriminator = "0"
		author.global_name = "bob"
		author.display_name = "Bob"
		author.nick = None
		author.bot = False
		author.color = discord.Color.default()
		author.accent_color = None
		author.display_avatar.url = "https://cdn.example.com/avatar.png"
		author.avatar_decoration = None
		author.banner = None
		author.created_at = None
		author.joined_at = None
		author.roles = []
		author.mention = "<@456>"

		ctx = MagicMock(spec=commands.Context)
		ctx.guild = guild
		ctx.author = author

		res = await cr.get_message("test.key", ctx)
		assert "Hello bob in My Guild!" in str(res)

		# Explicit author in kwargs overriding default context_formatting
		other_author = MagicMock(spec=discord.Member)
		other_author.name = "Alice"
		other_author.discriminator = "0"
		other_author.id = 789
		res_override = await cr.get_message("test.key", ctx, author=other_author)
		assert "Hello Alice in My Guild!" in str(res_override)

	@pytest.mark.asyncio
	async def test_get_message_allowed_mentions(self, mock_bot):
		cr = CustomResponse(mock_bot)
		cr.update_localizations(
			{"en": {"mention": {"all": {"content": "Ping all", "allowed_mentions": {"all": True}}}}}
		)

		res = await cr.get_message("mention.all", "en")
		assert isinstance(res, dict)
		mentions = res["allowed_mentions"]
		assert isinstance(mentions, discord.AllowedMentions)
		assert mentions.everyone is True
		assert mentions.users is True
		assert mentions.roles is True
		assert mentions.replied_user is True

	@pytest.mark.asyncio
	async def test_get_message_reply_with_message(self, mock_bot):
		cr = CustomResponse(mock_bot)
		cr.update_localizations({"en": {"test": {"reply_msg": {"content": "Reply test", "reply": True}}}})

		msg = MagicMock(spec=discord.Message)
		msg.guild = MagicMock(spec=discord.Guild)
		msg.guild.preferred_locale = "en"

		res = await cr.get_message("test.reply_msg", msg)
		assert isinstance(res, dict)
		assert res.get("reference") == msg


class TestCustomResponseComponentsV2:
	def test_convert_components_container(self, mock_bot):
		cr = CustomResponse(mock_bot)
		data = {
			"components": [
				{
					"type": "container",
					"accent_color": "#659273",
					"spoiler": False,
					"components": [
						{"type": "text_display", "content": "Container text"},
						{"type": "separator", "visible": True, "spacing": "large"},
					],
				}
			]
		}
		res = cr.convert_components(data)
		assert "view" in res
		view = res["view"]
		assert isinstance(view, discord.ui.LayoutView)
		assert view.has_components_v2() is True
		assert len(view.children) == 1
		container = view.children[0]
		assert isinstance(container, discord.ui.Container)
		assert container.accent_color == discord.Color(int("659273", 16))
		assert len(container.children) == 2
		assert isinstance(container.children[0], discord.ui.TextDisplay)
		assert container.children[0].content == "Container text"
		assert isinstance(container.children[1], discord.ui.Separator)
		assert container.children[1].spacing == discord.SeparatorSpacing.large

	def test_convert_components_section_with_accessory(self, mock_bot):
		cr = CustomResponse(mock_bot)
		data = {
			"components": [
				{
					"type": "section",
					"components": [{"type": "text_display", "content": "Section text"}],
					"accessory": {
						"type": "button",
						"label": "Click Me",
						"style": "primary",
						"custom_id": "btn:click",
					},
				}
			]
		}
		res = cr.convert_components(data)
		view = res["view"]
		assert isinstance(view, discord.ui.LayoutView)
		section = view.children[0]
		assert isinstance(section, discord.ui.Section)
		assert isinstance(section.accessory, discord.ui.Button)
		assert section.accessory.label == "Click Me"
		assert section.accessory.style == discord.ButtonStyle.primary

	def test_convert_components_button_grouping_in_container(self, mock_bot):
		cr = CustomResponse(mock_bot)
		data = {
			"components": [
				{
					"type": "container",
					"components": [
						{"type": "text_display", "content": "Before buttons"},
						{"type": "button", "label": "Btn 1", "custom_id": "b1"},
						{"type": "button", "label": "Btn 2", "custom_id": "b2"},
					],
				}
			]
		}
		res = cr.convert_components(data)
		container = res["view"].children[0]
		assert len(container.children) == 2
		assert isinstance(container.children[0], discord.ui.TextDisplay)
		assert isinstance(container.children[1], discord.ui.ActionRow)
		assert len(container.children[1].children) == 2

	def test_convert_components_layout_alias(self, mock_bot):
		cr = CustomResponse(mock_bot)
		data = {
			"layout": [
				{"type": "text_display", "content": "Text via layout key"},
			]
		}
		res = cr.convert_components(data)
		assert "view" in res
		assert isinstance(res["view"], discord.ui.LayoutView)

	def test_convert_components_non_dict_passthrough(self, mock_bot):
		cr = CustomResponse(mock_bot)
		assert cr.convert_components("simple string") == "simple string"
		assert cr.convert_components(42) == 42

	def test_merge_views(self, mock_bot):
		cr = CustomResponse(mock_bot)
		layout = discord.ui.LayoutView()
		container = discord.ui.Container(discord.ui.TextDisplay("Ticket"))
		layout.add_item(container)

		view = discord.ui.View()
		btn = discord.ui.Button(label="Open", custom_id="open:id")
		view.add_item(btn)

		merged = cr.merge_views(layout, view)
		assert isinstance(merged, discord.ui.LayoutView)
		assert len(container.children) == 2
		assert isinstance(container.children[1], discord.ui.ActionRow)
		assert container.children[1].children[0] == btn

	@pytest.mark.asyncio
	async def test_get_message_components_v2(self, mock_bot):
		cr = CustomResponse(mock_bot)
		cr.update_localizations(
			{
				"en": {
					"ticket": {
						"card": {
							"components": [
								{
									"type": "container",
									"accent_color": 6656243,
									"components": [
										{
											"type": "text_display",
											"content": "# Ticket #{ticket_id}\nUser: {author.name}",
										}
									],
								}
							]
						}
					}
				}
			}
		)

		author = MagicMock(spec=discord.Member)
		author.name = "Alice"
		author.guild = None

		ctx = MagicMock(spec=commands.Context)
		ctx.guild = MagicMock(spec=discord.Guild)
		ctx.guild.preferred_locale = "en"
		ctx.author = author

		res = await cr.get_message("ticket.card", ctx, ticket_id=99)
		assert isinstance(res, dict)
		assert "view" in res
		view = res["view"]
		assert isinstance(view, discord.ui.LayoutView)
		container = view.children[0]
		text_item = container.children[0]
		assert isinstance(text_item, discord.ui.TextDisplay)
		assert "# Ticket #99" in text_item.content
		assert "User: Alice" in text_item.content
