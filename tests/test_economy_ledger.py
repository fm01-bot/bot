"""Ledger against real PostgreSQL, plus the shop's charge-then-grant flow."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import discord
import pytest
from cogs.economy import Balance, InsufficientFunds, Ledger, Shop

GUILD = 1
ALICE, BOB = 10, 20


@pytest.fixture
def ledger(db: asyncpg.Pool) -> Ledger:
	return Ledger(db)


@pytest.mark.db
async def test_new_members_have_nothing_and_no_row(ledger, db):
	assert await ledger.balance(GUILD, ALICE) == Balance(0, 0)
	assert await db.fetchval("SELECT count(*) FROM economy") == 0


@pytest.mark.db
async def test_credit_pays_off_debt_first(ledger):
	await ledger.debit(GUILD, ALICE, 300, "bank")  # admin removal into debt
	assert (await ledger.balance(GUILD, ALICE)).in_debt

	bal = await ledger.credit(GUILD, ALICE, 500)

	assert bal == Balance(cash=200, bank=0)


@pytest.mark.db
async def test_cash_never_goes_negative(ledger):
	await ledger.credit(GUILD, ALICE, 100)

	with pytest.raises(InsufficientFunds):
		await ledger.debit(GUILD, ALICE, 101)
	assert await ledger.balance(GUILD, ALICE) == Balance(100, 0)


@pytest.mark.db
async def test_move_between_wallets_is_all_or_nothing(ledger):
	await ledger.credit(GUILD, ALICE, 100)

	assert await ledger.move(GUILD, ALICE, 60, "cash", "bank") == Balance(40, 60)
	with pytest.raises(InsufficientFunds):
		await ledger.move(GUILD, ALICE, 61, "bank", "cash")
	assert await ledger.balance(GUILD, ALICE) == Balance(40, 60)


@pytest.mark.db
async def test_transfer_moves_cash_and_creates_the_recipient(ledger):
	await ledger.credit(GUILD, ALICE, 100)

	await ledger.transfer(GUILD, ALICE, BOB, 70)

	assert await ledger.balance(GUILD, ALICE) == Balance(30, 0)
	assert await ledger.balance(GUILD, BOB) == Balance(70, 0)
	with pytest.raises(InsufficientFunds):
		await ledger.transfer(GUILD, ALICE, BOB, 31)
	with pytest.raises(ValueError):
		await ledger.transfer(GUILD, ALICE, ALICE, 1)


@pytest.mark.db
async def test_concurrent_operations_lose_no_money(ledger, db):
	"""Opposing transfers and first-time credits racing each other: no deadlock, no lost update, one row each."""
	await ledger.credit(GUILD, ALICE, 1000)
	await ledger.credit(GUILD, BOB, 1000)

	await asyncio.gather(
		*(ledger.transfer(GUILD, ALICE, BOB, 10) for _ in range(20)),
		*(ledger.transfer(GUILD, BOB, ALICE, 5) for _ in range(20)),
		*(ledger.credit(GUILD, 30, 1) for _ in range(20)),
	)

	assert await ledger.balance(GUILD, ALICE) == Balance(900, 0)
	assert await ledger.balance(GUILD, BOB) == Balance(1100, 0)
	assert await ledger.balance(GUILD, 30) == Balance(20, 0)
	assert await db.fetchval("SELECT count(*) FROM economy WHERE user_id = 30") == 1


def _buy_ctx(add_roles: AsyncMock) -> MagicMock:
	ctx = MagicMock()
	ctx.guild.id = GUILD
	ctx.guild.get_role.return_value = MagicMock(spec=discord.Role, id=5, name="VIP")
	ctx.author = MagicMock(spec=discord.Member, id=ALICE)
	ctx.author.add_roles = add_roles
	ctx.send = AsyncMock()
	return ctx


def _shop(db: asyncpg.Pool) -> Shop:
	bot = MagicMock()
	bot.db = db
	shop = Shop(bot)
	return shop


@pytest.mark.db
async def test_buy_charges_then_grants(db, ledger):
	await db.execute(
		"INSERT INTO shop (item_name, item_description, item_price, role, guild_id, creator_id) "
		"VALUES ('VIP', 'd', 100, 5, $1, 1)",
		GUILD,
	)
	await ledger.credit(GUILD, ALICE, 150)
	ctx = _buy_ctx(AsyncMock())
	shop = _shop(db)

	await shop.buy.callback(shop, ctx, "vip")

	ctx.author.add_roles.assert_awaited_once()
	assert await ledger.balance(GUILD, ALICE) == Balance(50, 0)
	assert ctx.send.call_args.args[0] == "shop.buy.success"


@pytest.mark.db
async def test_buy_refunds_when_the_role_cannot_be_given(db, ledger):
	"""Regression: the role used to be granted before charging, so a failed charge meant a free role."""
	await db.execute(
		"INSERT INTO shop (item_name, item_description, item_price, role, guild_id, creator_id) "
		"VALUES ('VIP', 'd', 100, 5, $1, 1)",
		GUILD,
	)
	await ledger.credit(GUILD, ALICE, 150)
	ctx = _buy_ctx(AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "missing permissions")))
	shop = _shop(db)

	await shop.buy.callback(shop, ctx, "vip")

	assert await ledger.balance(GUILD, ALICE) == Balance(150, 0)
	assert ctx.send.call_args.args[0] == "shop.buy.errors.role_failed"


@pytest.mark.db
async def test_buy_without_enough_cash_grants_nothing(db, ledger):
	await db.execute(
		"INSERT INTO shop (item_name, item_description, item_price, role, guild_id, creator_id) "
		"VALUES ('VIP', 'd', 100, 5, $1, 1)",
		GUILD,
	)
	ctx = _buy_ctx(AsyncMock())
	shop = _shop(db)

	await shop.buy.callback(shop, ctx, "vip")

	ctx.author.add_roles.assert_not_awaited()
	assert ctx.send.call_args.args[0] == "shop.buy.errors.balance"
