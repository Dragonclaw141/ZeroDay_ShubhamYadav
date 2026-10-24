import copy
from typing import Any, Optional

import pytest
import pytest_asyncio
from bson import ObjectId
from httpx import ASGITransport, AsyncClient
from pymongo import ReturnDocument
from pymongo.collation import Collation
from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError

from app.core.database import ensure_indexes, get_database
from app.main import app


class FakeInsertOneResult:
    def __init__(self, inserted_id: ObjectId):
        self.inserted_id = inserted_id


class FakeUpdateResult:
    def __init__(self, matched_count: int, modified_count: int):
        self.matched_count = matched_count
        self.modified_count = modified_count


class FakeCursor:
    """Async cursor returned by FakeCollection.find() supporting Motor's to_list()."""

    def __init__(self, docs: list[dict[str, Any]]):
        self._docs = docs

    async def to_list(self, length: Optional[int] = None) -> list[dict[str, Any]]:
        if length is None:
            return copy.deepcopy(self._docs)
        return copy.deepcopy(self._docs[:length])


class FakeCollection:
    """Isolated async in-memory collection implementing Motor collection methods for testing."""

    def __init__(self, name: str):
        self.name = name
        self._docs: list[dict[str, Any]] = []
        self.indexes: dict[str, dict[str, Any]] = {}
        self.fail_operations: bool = False

    def _check_fail(self) -> None:
        if self.fail_operations:
            raise ServerSelectionTimeoutError("Simulated database failure")

    async def create_index(self, keys: list[tuple[str, Any]], **kwargs: Any) -> str:
        self._check_fail()
        idx_name = kwargs.get("name") or "_".join(f"{k}_{v}" for k, v in keys)
        self.indexes[idx_name] = {"keys": keys, **kwargs}
        return idx_name

    def _matches(
        self,
        doc: dict[str, Any],
        query: dict[str, Any],
        collation: Optional[Collation] = None,
    ) -> bool:
        case_insensitive = bool(
            collation and getattr(collation, "document", {}).get("strength") == 2
        )
        for key, condition in query.items():
            val = doc.get(key)
            if isinstance(condition, dict):
                if "$ne" in condition and val == condition["$ne"]:
                    return False
            else:
                if case_insensitive and isinstance(val, str) and isinstance(condition, str):
                    if val.lower() != condition.lower():
                        return False
                elif val != condition:
                    return False
        return True

    def _enforce_unique_indexes(
        self,
        candidate: dict[str, Any],
        ignore_id: Optional[ObjectId] = None,
    ) -> None:
        for idx_name, idx_meta in self.indexes.items():
            if not idx_meta.get("unique"):
                continue
            keys = idx_meta["keys"]
            collation = idx_meta.get("collation")
            case_insensitive = bool(
                collation and getattr(collation, "document", {}).get("strength") == 2
            )
            for field, _ in keys:
                cand_val = candidate.get(field)
                if cand_val is None:
                    continue
                for existing in self._docs:
                    if ignore_id is not None and existing.get("_id") == ignore_id:
                        continue
                    ex_val = existing.get(field)
                    if case_insensitive and isinstance(cand_val, str) and isinstance(ex_val, str):
                        if cand_val.lower() == ex_val.lower():
                            raise DuplicateKeyError(f"E11000 duplicate key error index: {idx_name} ({field})")
                    elif cand_val == ex_val:
                        raise DuplicateKeyError(f"E11000 duplicate key error index: {idx_name} ({field})")

    async def find_one(
        self,
        query: dict[str, Any],
        collation: Optional[Collation] = None,
    ) -> Optional[dict[str, Any]]:
        self._check_fail()
        for doc in self._docs:
            if self._matches(doc, query, collation=collation):
                return copy.deepcopy(doc)
        return None

    def find(
        self,
        query: Optional[dict[str, Any]] = None,
    ) -> FakeCursor:
        self._check_fail()
        q = query or {}
        matched = [
            copy.deepcopy(doc)
            for doc in self._docs
            if self._matches(doc, q)
        ]
        return FakeCursor(matched)

    async def insert_one(self, doc: dict[str, Any]) -> FakeInsertOneResult:
        self._check_fail()
        new_doc = copy.deepcopy(doc)
        if "_id" not in new_doc:
            new_doc["_id"] = ObjectId()
        self._enforce_unique_indexes(new_doc)
        self._docs.append(new_doc)
        return FakeInsertOneResult(new_doc["_id"])

    async def update_one(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
    ) -> FakeUpdateResult:
        self._check_fail()
        for idx, doc in enumerate(self._docs):
            if self._matches(doc, query):
                updated = copy.deepcopy(doc)
                if "$set" in update:
                    updated.update(copy.deepcopy(update["$set"]))
                self._enforce_unique_indexes(updated, ignore_id=doc["_id"])
                self._docs[idx] = updated
                return FakeUpdateResult(matched_count=1, modified_count=1)
        return FakeUpdateResult(matched_count=0, modified_count=0)

    async def find_one_and_update(
        self,
        query: dict[str, Any],
        update: dict[str, Any],
        return_document: bool = ReturnDocument.BEFORE,
    ) -> Optional[dict[str, Any]]:
        self._check_fail()
        for idx, doc in enumerate(self._docs):
            if self._matches(doc, query):
                before_doc = copy.deepcopy(doc)
                updated = copy.deepcopy(doc)
                if "$set" in update:
                    updated.update(copy.deepcopy(update["$set"]))
                self._enforce_unique_indexes(updated, ignore_id=doc["_id"])
                self._docs[idx] = updated
                if return_document == ReturnDocument.AFTER:
                    return copy.deepcopy(updated)
                return before_doc
        return None


class FakeDatabase:
    """Isolated async in-memory MongoDB database for Stage 1 testing."""

    def __init__(self):
        self._collections: dict[str, FakeCollection] = {}
        self.healthy: bool = True

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection(name)
        return self._collections[name]

    async def command(self, cmd: str) -> dict[str, Any]:
        if not self.healthy or cmd != "ping":
            raise ServerSelectionTimeoutError("Database unavailable")
        return {"ok": 1.0}


@pytest_asyncio.fixture
async def test_db() -> FakeDatabase:
    db = FakeDatabase()
    await ensure_indexes(db)
    return db


@pytest_asyncio.fixture
async def client(test_db: FakeDatabase):
    app.dependency_overrides[get_database] = lambda: test_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
    app.dependency_overrides.clear()
