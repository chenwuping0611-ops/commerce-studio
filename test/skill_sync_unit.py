from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from applications.common.skill_storage import force_replace_skill_storage
from applications.common.storage import StorageError, StoredFile
from applications.extensions import db


def _skill(asset):
    return SimpleNamespace(
        id=1,
        code="builtin-skill",
        storage_asset_id=getattr(asset, "id", None),
        storage_asset=asset,
        created_by=7,
        dept_id=3,
        content="legacy content",
        prompt_template="legacy prompt",
    )


def test_force_replace_keeps_asset_identity_when_old_file_is_readable():
    old_asset = SimpleNamespace(
        id=10,
        purpose="SKILL",
        status="ACTIVE",
        original_filename="old.md",
    )
    pending = SimpleNamespace(
        asset=old_asset,
        new_file=SimpleNamespace(storage_path="/group1/skills/new.md"),
    )
    session = MagicMock()

    with patch.object(db, "session", session), patch(
        "applications.common.skill_storage.FileService.read_text",
        return_value="old content",
    ), patch(
        "applications.common.skill_storage.FileService.stage_asset_update",
        return_value=pending,
    ) as stage_update, patch(
        "applications.common.skill_storage.FileService.finalize_asset_update",
        return_value=True,
    ) as finalize:
        skill = _skill(old_asset)
        result = force_replace_skill_storage(
            skill,
            "new content",
            "skill.md",
        )

    assert result is old_asset
    assert skill.storage_asset_id == old_asset.id
    assert skill.content is None
    assert skill.prompt_template is None
    stage_update.assert_called_once()
    assert stage_update.call_args.kwargs["content"] == b"new content"
    finalize.assert_called_once_with(pending)
    assert session.commit.call_count == 1


def test_force_replace_switches_asset_when_old_file_is_unreadable():
    old_asset = SimpleNamespace(
        id=10,
        purpose="SKILL",
        status="ACTIVE",
        original_filename="old.md",
        storage_path="/group1/skills/old.md",
    )
    new_asset = SimpleNamespace(id=11)
    stored = StoredFile(
        storage_path="/group1/skills/new.md",
        public_url="https://files.example/gofastdfs/group1/skills/new.md",
        original_filename="skill.md",
        content_type="text/markdown",
        file_size=11,
    )
    session = MagicMock()
    session.commit.side_effect = [None, None]

    with patch.object(db, "session", session), patch(
        "applications.common.skill_storage.FileService.read_text",
        side_effect=StorageError("old object missing"),
    ), patch(
        "applications.common.skill_storage.FileService.upload_bytes",
        return_value=stored,
    ) as upload_bytes, patch(
        "applications.common.skill_storage.FileService.create_asset_record",
        return_value=new_asset,
    ), patch(
        "applications.common.skill_storage.FileService.delete_asset",
        return_value=True,
    ) as delete_asset, patch(
        "applications.common.skill_storage.asset_referenced",
        return_value=False,
    ):
        skill = _skill(old_asset)
        result = force_replace_skill_storage(
            skill,
            "new content",
            "skill.md",
        )

    assert result is new_asset
    assert skill.storage_asset_id == new_asset.id
    upload_bytes.assert_called_once()
    delete_asset.assert_called_once_with(old_asset)
    session.delete.assert_called_once_with(old_asset)
    assert session.commit.call_count == 2


def main():
    test_force_replace_keeps_asset_identity_when_old_file_is_readable()
    test_force_replace_switches_asset_when_old_file_is_unreadable()
    print("skill sync unit passed")


if __name__ == "__main__":
    main()
