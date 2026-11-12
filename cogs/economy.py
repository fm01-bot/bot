import logging
import random
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

import asyncpg
import discord
from args import Role, User
from core import Bot, Context, command, group
from discord import app_commands
from discord.ext import commands
from discord.ext.localization import Localization
from helpers import custom_response, random_helper

logger = logging.getLogger(__name__)


class ShopItem:
	def __init__(self, name: str, price: int, description: str, role: discord.Role | None):
		"""Create a new shop item.

		Args:
			name: The name of the item.
			price: The price of the item.
			description: The description of the item.
			role: The role that is given to the user when they buy the item.

		"""
		self._name = name
		self._price = price
		self._description = description
		self._raw_role: discord.Role | None = role
		self._role: Role | None = Role.from_role(role) if role else None

	@property
	def name(self) -> str:
		"""The name of the item."""
		return self._name

	@property
	def price(self) -> int:
		"""The price of the item."""
		return self._price

	@property
	def description(self) -> str:
		"""The description of the item."""
		return self._description

	@property
	def role(self) -> Role | None:
		"""The role that is given to the user when they buy the item."""
		return self._role

	@property
	def raw_role(self) -> discord.Role | None:
		"""The discord.Role object associated with the item."""
		return self._raw_role

	def __str__(self) -> str:
		return self.name

	def __int__(self) -> int:
		return self.price


type Wallet = Literal["cash", "bank"]


class InsufficientFunds(Exception):
	"""The wallet doesn't hold enough money for the operation."""


@dataclass(frozen=True, slots=True)
class Balance:
	"""A member's money in one guild. ``bank`` is negative while the member is in debt."""

	cash: int = 0
	bank: int = 0

	@property
	def in_debt(self) -> bool:
		return self.bank < 0

	def __getitem__(self, wallet: Wallet) -> int:
		return self.cash if wallet == "cash" else self.bank


class Ledger:
	"""Every change to ``economy`` balances. Each operation is one transaction over row-locked accounts.

	Rules:
		- Cash never goes negative; spending more cash than you have raises `InsufficientFunds`.
		- The bank may be negative (debt) only through `debit(..., wallet="bank")`, which admins use.
		- Money credited while in debt pays the debt off first.
	"""

	def __init__(self, db: asyncpg.Pool) -> None:
		self._db = db

	async def balance(self, guild_id: int, user_id: int) -> Balance:
		"""The member's balance; members without an account have nothing."""
		row = await self._db.fetchrow(
			"SELECT cash, bank FROM economy WHERE guild_id = $1 AND user_id = $2", guild_id, user_id
		)
		return Balance(int(row["cash"]), int(row["bank"])) if row else Balance()

	async def credit(self, guild_id: int, user_id: int, amount: int, wallet: Wallet = "cash") -> Balance:
		"""Add money; it pays off any debt before reaching the wallet."""
		async with self._accounts(guild_id, user_id) as (conn, (bal,)):
			return await self._write(conn, guild_id, user_id, _credited(bal, amount, wallet))

	async def debit(self, guild_id: int, user_id: int, amount: int, wallet: Wallet = "cash") -> Balance:
		"""Remove money. Cash can't go negative (`InsufficientFunds`); the bank can, which records debt."""
		async with self._accounts(guild_id, user_id) as (conn, (bal,)):
			if wallet == "cash" and bal.cash < amount:
				raise InsufficientFunds
			return await self._write(conn, guild_id, user_id, _debited(bal, amount, wallet))

	async def move(self, guild_id: int, user_id: int, amount: int, source: Wallet, target: Wallet) -> Balance:
		"""Move money between the member's own wallets (deposit/withdraw). The source must hold ``amount``."""
		async with self._accounts(guild_id, user_id) as (conn, (bal,)):
			if bal[source] < amount:
				raise InsufficientFunds
			return await self._write(conn, guild_id, user_id, _credited(_debited(bal, amount, source), amount, target))

	async def transfer(self, guild_id: int, sender_id: int, recipient_id: int, amount: int) -> None:
		"""Move cash from one member to another, all or nothing."""
		if sender_id == recipient_id:
			raise ValueError("cannot transfer to the same account")
		async with self._accounts(guild_id, sender_id, recipient_id) as (conn, (sender, recipient)):
			if sender.cash < amount:
				raise InsufficientFunds
			await self._write(conn, guild_id, sender_id, _debited(sender, amount, "cash"))
			await self._write(conn, guild_id, recipient_id, _credited(recipient, amount, "cash"))

	@asynccontextmanager
	async def _accounts(
		self, guild_id: int, *user_ids: int
	) -> AsyncGenerator[tuple[asyncpg.Connection, list[Balance]], None]:
		"""Open a transaction with the members' accounts created and locked (in ID order, to avoid deadlocks)."""
		async with self._db.acquire() as conn, conn.transaction():
			for user_id in sorted(user_ids):
				await conn.execute(
					"INSERT INTO economy (guild_id, user_id) VALUES ($1, $2) ON CONFLICT (guild_id, user_id) DO NOTHING",
					guild_id,
					user_id,
				)
			rows = await conn.fetch(
				"SELECT user_id, cash, bank FROM economy WHERE guild_id = $1 AND user_id = ANY($2::numeric[]) "
				"ORDER BY user_id FOR UPDATE",
				guild_id,
				list(user_ids),
			)
			by_user = {int(r["user_id"]): Balance(int(r["cash"]), int(r["bank"])) for r in rows}
			yield conn, [by_user[user_id] for user_id in user_ids]

	@staticmethod
	async def _write(conn: asyncpg.Connection, guild_id: int, user_id: int, bal: Balance) -> Balance:
		await conn.execute(
			"UPDATE economy SET cash = $1, bank = $2 WHERE guild_id = $3 AND user_id = $4",
			bal.cash,
			bal.bank,
			guild_id,
			user_id,
		)
		return bal


def _credited(bal: Balance, amount: int, wallet: Wallet) -> Balance:
	repaid = min(amount, -bal.bank) if bal.in_debt else 0
	bank, rest = bal.bank + repaid, amount - repaid
	return Balance(bal.cash + rest, bank) if wallet == "cash" else Balance(bal.cash, bank + rest)


def _debited(bal: Balance, amount: int, wallet: Wallet) -> Balance:
	return Balance(bal.cash - amount, bal.bank) if wallet == "cash" else Balance(bal.cash, bal.bank - amount)


@app_commands.guild_only()
@commands.guild_only()
class Economy(commands.GroupCog, name="Economy", group_name="economy"):
	def __init__(self, client: Bot):
		self.client = client
		self.ledger = Ledger(client.db)
		self.custom_response = client.custom_response

	@command(user=False)
	async def leaderboard(self, ctx: commands.Context):
		assert ctx.guild is not None
		rows = await self.client.db.fetch(
			"SELECT * FROM economy WHERE guild_id = $1 ORDER BY cash+bank DESC LIMIT 10",
			ctx.guild.id,  # user = False on this command, so ctx.guild is always available
		)
		message = await self.custom_response("leaderboard", ctx)

		if not isinstance(message, dict):
			raise TypeError("leaderboard response is not a dict")

		embeds: list[discord.Embed] = message.get("embeds", [])
		if not rows:
			if embeds:
				embeds[0].remove_field(0)
			await ctx.send(**message)
			return

		if embeds:
			template = embeds[0].to_dict().get("fields", [None])[0]
			if not template:
				await ctx.send(**message)
				return
			embeds[0].clear_fields()
			for number, row in enumerate(rows, start=1):
				cached_user = self.client.get_user(int(row["user_id"]))
				user = User.from_user(cached_user) if cached_user else None
				cash, bank = int(row["cash"]), int(row["bank"])
				formatted = Localization.format_strings(template, user=user, number=number, cash=cash, bank=bank)
				embeds[0].add_field(**formatted)
			message["embeds"] = self.client.custom_response.convert_embeds(embeds)

		await ctx.send(**message)

	@command(user=False)
	@commands.cooldown(1, 3600, commands.BucketType.user)
	async def work(self, ctx: Context):
		assert ctx.guild is not None
		amount: int = random.randint(300, 1500)
		await self.ledger.credit(ctx.guild.id, ctx.author.id, amount)

		await ctx.send("work", amount=amount)

	@command(user=False)
	async def crime(self, ctx: Context):
		assert ctx.guild is not None
		amount = random.randint(500, 2000)
		await self.ledger.credit(ctx.guild.id, ctx.author.id, amount)

		await ctx.send("crime", amount=amount)

	@command(user=False)
	@commands.cooldown(1, 86400, commands.BucketType.user)
	async def daily(self, ctx: Context):
		assert ctx.guild is not None
		amount = 5000
		await self.ledger.credit(ctx.guild.id, ctx.author.id, amount)

		await ctx.send("allowance", amount=amount)

	@command(user=False)
	@app_commands.choices(
		account=[
			app_commands.Choice(name="global-cash", value="cash"),
			app_commands.Choice(name="global-bank", value="bank"),
		]
	)
	@app_commands.checks.has_permissions(administrator=True)
	@commands.has_permissions(administrator=True)
	async def addmoney(
		self,
		ctx: Context,
		member: discord.Member,
		amount: commands.Range[int, 1],
		account: Literal["cash", "bank"] = "cash",
	):
		assert ctx.guild is not None
		await self.ledger.credit(ctx.guild.id, member.id, amount, account)
		await ctx.send("addmoney.success", amount=amount, member=member)

	@command(user=False)
	@app_commands.choices(
		account=[
			app_commands.Choice(name="global-cash", value="cash"),
			app_commands.Choice(name="global-bank", value="bank"),
		]
	)
	@app_commands.checks.has_permissions(administrator=True)
	@commands.has_permissions(administrator=True)
	async def removemoney(
		self,
		ctx: Context,
		member: discord.Member,
		amount: discord.app_commands.Range[int, 1],
		account: Literal["cash", "bank"] = "cash",
	):
		assert ctx.guild is not None
		try:
			await self.ledger.debit(ctx.guild.id, member.id, amount, account)
		except InsufficientFunds:
			await ctx.send("removemoney.errors.balance")
			return
		await ctx.send("removemoney.success", amount=amount, member=member)

	@command(user=False)
	@commands.cooldown(1, 3600, commands.BucketType.user)
	async def luck(self, ctx: Context):
		assert ctx.guild is not None
		minimum_balance = 1000
		if (await self.ledger.balance(ctx.guild.id, ctx.author.id)).cash < minimum_balance:
			await ctx.send("luck.errors.balance", amount=minimum_balance)
			return

		amount = random.randint(200, 1000)
		if random_helper.randbool():
			await self.ledger.credit(ctx.guild.id, ctx.author.id, amount)
			await ctx.send("luck.win", amount=amount)
			return
		try:
			await self.ledger.debit(ctx.guild.id, ctx.author.id, amount)
		except InsufficientFunds:
			await ctx.send("luck.errors.balance", amount=minimum_balance)
			return
		await ctx.send("luck.lose", amount=amount)

	@command(user=False)
	async def pay(self, ctx: Context, member: discord.Member, amount: discord.app_commands.Range[int, 1]):
		assert ctx.guild is not None
		if member == ctx.author:
			await ctx.send("pay.errors.self")
			return
		try:
			await self.ledger.transfer(ctx.guild.id, ctx.author.id, member.id, amount)
		except InsufficientFunds:
			await ctx.send("pay.errors.balance")
			return

		await ctx.send("pay.success", amount=amount, member=member)

	@command(user=False, aliases=["bal"])
	async def balance(self, ctx: Context, member: discord.Member | None):
		assert ctx.guild is not None
		target_member = member or (ctx.author if isinstance(ctx.author, discord.Member) else None)
		if not target_member:
			raise commands.BadArgument
		bal = await self.ledger.balance(ctx.guild.id, target_member.id)

		message: dict = await self.custom_response("balance", ctx, member=target_member, cash=bal.cash, bank=bal.bank)

		if not bal.in_debt and message.get("embeds"):  # remove the debt alert embed field
			for index, embed in enumerate(message["embeds"]):
				if len(embed.fields) > 2:
					message["embeds"][index].remove_field(2)

		await ctx.send(**message)

	@command(user=False)
	@commands.cooldown(1, 3600, commands.BucketType.user)
	async def slots(self, ctx: Context, bet: int):
		assert ctx.guild is not None
		if bet <= 0:
			await ctx.send("slots.errors.balance")
			return

		try:
			await self.ledger.debit(ctx.guild.id, ctx.author.id, bet)
		except InsufficientFunds:
			await ctx.send("slots.errors.balance")
			return

		slots_choices = ["🍇", "🍉", "🍊", "🍋"]
		results = [random.choice(slots_choices) for _ in range(3)]

		if results.count(results[0]) == len(results):
			payout = bet * 2
			await self.ledger.credit(ctx.guild.id, ctx.author.id, payout)
			await ctx.send("slots.win", results=" ".join(results), amount=payout)
		else:
			in_debt = (await self.ledger.balance(ctx.guild.id, ctx.author.id)).in_debt
			message: dict = await self.custom_response(
				"slots.lose", ctx, convert_embeds=False, results=" ".join(results), amount=bet
			)

			if not in_debt and message.get("embeds"):
				for index, embed in enumerate(message["embeds"]):
					if len(embed.fields) > 2:
						message["embeds"][index].remove_field(2)

			await ctx.send(**message)

	@command(user=False)
	async def deposit(self, ctx: Context, amount: discord.app_commands.Range[int, 1] | None = None):
		assert ctx.guild is not None
		if amount is None:  # everything in the cash wallet
			amount = (await self.ledger.balance(ctx.guild.id, ctx.author.id))["cash"]
		if amount < 1:
			await ctx.send("deposit.errors.invalid_amount")
			return
		try:
			await self.ledger.move(ctx.guild.id, ctx.author.id, amount, "cash", "bank")
		except InsufficientFunds:
			await ctx.send("deposit.errors.balance")
			return

		await ctx.send("deposit.success", amount=amount)

	@command(user=False)
	async def withdraw(self, ctx: Context, amount: discord.app_commands.Range[int, 1] | None = None):
		assert ctx.guild is not None
		if amount is None:  # everything in the bank wallet
			amount = (await self.ledger.balance(ctx.guild.id, ctx.author.id))["bank"]
		if amount < 1:
			await ctx.send("withdraw.errors.invalid_amount")
			return
		try:
			await self.ledger.move(ctx.guild.id, ctx.author.id, amount, "bank", "cash")
		except InsufficientFunds:
			await ctx.send("withdraw.errors.balance")
			return

		await ctx.send("withdraw.success", amount=amount)


class Shop(commands.Cog, name="Shop"):
	def __init__(self, client):
		self.client: Bot = client
		self.ledger = Ledger(client.db)
		self.custom_response = custom_response.CustomResponse(client, name="shop")

	@group(user=False)
	async def shop(self, ctx: Context):
		assert ctx.guild is not None
		row = await self.client.db.fetch("SELECT * FROM shop WHERE guild_id = $1", ctx.guild.id)
		if not row:
			await ctx.send("shop.list.empty")
			return

		message: dict = await self.custom_response.get_message("shop.list.show", ctx)
		embeds: list[discord.Embed] = message.get("embeds", [])
		if message.get("embeds"):
			template = embeds[0].to_dict().get("fields", [None])[0]
			if not template:
				await ctx.send(**message)
				return
			embeds[0].clear_fields()
			for i in row:
				role = ctx.guild.get_role(i["role"])
				if not role:
					continue
				item = ShopItem(i["item_name"], i["item_price"], i["item_description"], role)
				formatted = Localization.format_strings(template, item=item)
				embeds[0].add_field(**formatted)
			message["embeds"] = self.client.custom_response.convert_embeds(embeds)

		await ctx.send(**message)

	@shop.command()
	async def buy(self, ctx: Context, item_name: str):
		assert ctx.guild is not None
		assert isinstance(ctx.author, discord.Member)
		row = await self.client.db.fetchrow(
			"SELECT * FROM shop WHERE guild_id = $1 AND LOWER(item_name) = $2", ctx.guild.id, item_name.lower()
		)
		if not row:
			await ctx.send("shop.buy.errors.not_found")
			return

		role = ctx.guild.get_role(row["role"])
		item = ShopItem(row["item_name"], row["item_price"], row["item_description"], role)
		if not item.raw_role:
			await ctx.send("shop.buy.errors.role_not_found")
			return

		try:
			await self.ledger.debit(ctx.guild.id, ctx.author.id, item.price)
		except InsufficientFunds:
			await ctx.send("shop.buy.errors.balance")
			return

		try:
			await ctx.author.add_roles(item.raw_role)
		except discord.HTTPException:
			try:
				await self.ledger.credit(ctx.guild.id, ctx.author.id, item.price)
			except Exception:
				logger.exception(f"Refund of {item.price} to {ctx.author.id} in {ctx.guild.id} failed")
			await ctx.send("shop.buy.errors.role_failed", item=item)
			return

		await ctx.send("shop.buy.success", item=item)

	@shop.command()
	@app_commands.checks.has_permissions(manage_guild=True, manage_roles=True)
	@commands.has_permissions(manage_guild=True, manage_roles=True)
	async def set_item(self, ctx: Context, item_name: str, price: int, description: str, role: discord.Role):
		assert ctx.guild is not None
		assert isinstance(ctx.author, discord.Member)
		row = await self.client.db.fetchrow(
			"SELECT * FROM shop WHERE guild_id = $1 AND LOWER(item_name) = $2", ctx.guild.id, item_name.lower()
		)
		if row:
			await ctx.send("shop.set.errors.already_item")
			return

		items = await self.client.db.fetch("SELECT * FROM shop WHERE guild_id = $1", ctx.guild.id)
		if len(items) + 1 >= 10:
			await ctx.send("shop.set.errors.limit")
			return

		if ctx.author.top_role.position <= role.position:
			await ctx.send("shop.set.errors.role_higher")
			return

		await self.client.db.execute(
			"INSERT INTO shop(item_name, item_description, item_price, role, guild_id, creator_id) VALUES($1, $2, $3, $4, $5, $6)",
			item_name,
			description,
			price,
			role.id,
			ctx.guild.id,
			ctx.author.id,
		)

		item = ShopItem(item_name, price, description, role)
		await ctx.send("shop.set.success", item=item)

	@shop.command()
	@app_commands.checks.has_permissions(manage_guild=True)
	async def remove_item(self, ctx: Context, item_name: str):
		assert ctx.guild is not None
		assert isinstance(ctx.author, discord.Member)
		row = await self.client.db.fetchrow(
			"SELECT * FROM shop WHERE guild_id = $1 AND LOWER(item_name) = $2", ctx.guild.id, item_name.lower()
		)
		if not row:
			await ctx.send("shop.remove.errors.not_found")
			return

		role = ctx.guild.get_role(row["role"])
		item = ShopItem(row["item_name"], row["item_price"], row["item_description"], role)
		if item.raw_role and ctx.author.top_role.position <= item.raw_role.position:
			await ctx.send("shop.remove.errors.role_higher")
			return

		await self.client.db.execute(
			"DELETE FROM shop WHERE guild_id = $1 AND LOWER(item_name) = $2", ctx.guild.id, item.name.lower()
		)
		await ctx.send("shop.remove.success", item=item)


async def setup(client: Bot):
	await client.add_cog(Economy(client))
	await client.add_cog(Shop(client))
