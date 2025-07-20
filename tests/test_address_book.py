import asyncio
from pathlib import Path

import pytest

from jabber_mcp.address_book import AddressBook


@pytest.fixture
async def address_book(tmp_path: Path):
    return AddressBook(storage_path=tmp_path / "address_book.json")


@pytest.mark.asyncio
async def test_save_and_query_alias(address_book):
    # Save alias
    assert await address_book.save_alias("test-alias", "test@jabber.org")

    # Query alias
    results = await address_book.query("test")
    assert len(results) == 1
    assert results[0][0] == "test-alias"
    assert results[0][1] == "test@jabber.org"


@pytest.mark.asyncio
async def test_invalid_alias(address_book):
    with pytest.raises(ValueError):
        await address_book.save_alias("", "test@jabber.org")


@pytest.mark.asyncio
async def test_invalid_jid(address_book):
    with pytest.raises(ValueError):
        await address_book.save_alias("test-alias", "invalid-jid")


@pytest.mark.asyncio
async def test_remove_alias(address_book):
    await address_book.save_alias("remove-alias", "remove@jabber.org")
    assert address_book.remove_alias("remove-alias")
    assert not address_book.remove_alias("nonexistent-alias")


@pytest.mark.asyncio
async def test_clear_address_book(address_book):
    await address_book.save_alias("clear-alias", "clear@jabber.org")
    assert address_book.clear() == 1
    assert address_book.count() == 0
