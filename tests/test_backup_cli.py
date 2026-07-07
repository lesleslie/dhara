from __future__ import annotations

import argparse
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, mock_open, patch

import pytest


def _args(**kwargs):
    defaults = {
        "verbose": False,
        "backup_dir": "./backups",
        "source": None,
        "target": None,
        "type": "full",
        "compression_level": 3,
        "encrypt": False,
        "key_file": None,
        "cloud_provider": None,
        "cloud_upload": False,
        "backup_id": None,
        "timestamp": None,
        "verify": False,
        "all": False,
        "test_restore": False,
        "output": None,
        "action": None,
        "format": "table",
        "since": None,
        "provider": None,
        "bucket": None,
        "prefix": "",
        "name": None,
        "schedule": None,
        "retention": None,
        "daemon": False,
        "export": None,
        "import": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_setup_parser_exposes_commands():
    from dhara.backup.cli import setup_parser

    parser = setup_parser()
    assert isinstance(parser, argparse.ArgumentParser)
    subcommands = parser._subparsers._group_actions[0].choices
    assert {"backup", "restore", "list", "verify", "schedule", "catalog", "cloud", "config"} <= set(subcommands)


def test_generate_encryption_key_writes_key(tmp_path):
    from dhara.backup.cli import generate_encryption_key

    key_file = tmp_path / "keys" / "backup.key"
    with patch("cryptography.fernet.Fernet.generate_key", return_value=b"test-key"):
        generate_encryption_key(str(key_file))
    assert key_file.read_bytes() == b"test-key"


def test_init_backup_directory_creates_structure(tmp_path):
    from dhara.backup.cli import init_backup_directory

    backup_dir = tmp_path / "backups"
    init_backup_directory(str(backup_dir))
    assert (backup_dir / "catalog").is_dir()
    assert (backup_dir / "logs").is_dir()
    assert (backup_dir / "temp").is_dir()


def test_cmd_backup_missing_source_returns_error(tmp_path):
    from dhara.backup.cli import cmd_backup

    args = _args(source=str(tmp_path / "missing.dhara"), backup_dir=str(tmp_path / "backups"))
    with patch("dhara.backup.cli.Path.exists", return_value=False):
        assert cmd_backup(args) == 1


def test_cmd_backup_full_backup_happy_path(tmp_path):
    from dhara.backup.cli import cmd_backup

    source = tmp_path / "source.dhara"
    source.write_text("data")
    metadata = SimpleNamespace(backup_id="full_1", size_bytes=123, source_path=str(source))
    backup_manager = MagicMock()
    backup_manager.perform_full_backup.return_value = metadata

    with patch("dhara.backup.cli.init_backup_directory") as mock_init:
        with patch("dhara.backup.cli.FileStorage") as mock_storage_cls:
            storage = MagicMock()
            mock_storage_cls.return_value = storage
            with patch("dhara.backup.cli.BackupManager", return_value=backup_manager) as mock_mgr:
                args = _args(source=str(source), backup_dir=str(tmp_path / "backups"))
                assert cmd_backup(args) == 0

    mock_init.assert_called_once()
    mock_mgr.assert_called_once()
    storage.close.assert_called_once()


def test_cmd_backup_incremental_uses_latest_backup(tmp_path):
    from dhara.backup.cli import cmd_backup

    source = tmp_path / "source.dhara"
    source.write_text("data")
    metadata = SimpleNamespace(backup_id="inc_1", size_bytes=456, source_path=str(source))
    last_backup = SimpleNamespace(backup_id="full_prev")
    backup_manager = MagicMock()
    backup_manager.perform_incremental_backup.return_value = metadata
    catalog = MagicMock()
    catalog.get_last_backup.return_value = last_backup

    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.FileStorage") as mock_storage_cls:
            storage = MagicMock()
            mock_storage_cls.return_value = storage
            with patch("dhara.backup.cli.BackupManager", return_value=backup_manager) as mock_mgr:
                with patch("dhara.backup.cli.BackupCatalog", return_value=catalog) as mock_catalog:
                    args = _args(source=str(source), backup_dir=str(tmp_path / "backups"), type="incremental")
                    assert cmd_backup(args) == 0

    mock_mgr.assert_called_once()
    mock_catalog.assert_called_once()
    backup_manager.perform_incremental_backup.assert_called_once_with("full_prev")
    storage.close.assert_called_once()


def test_cmd_backup_differential_without_prior_full_backup(tmp_path):
    from dhara.backup.cli import cmd_backup

    source = tmp_path / "source.dhara"
    source.write_text("data")
    metadata = SimpleNamespace(backup_id="diff_1", size_bytes=789, source_path=str(source))
    backup_manager = MagicMock()
    backup_manager.perform_differential_backup.return_value = metadata
    catalog = MagicMock()
    catalog.get_last_backup_of_type.return_value = None

    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.FileStorage") as mock_storage_cls:
            storage = MagicMock()
            mock_storage_cls.return_value = storage
            with patch("dhara.backup.cli.BackupManager", return_value=backup_manager):
                with patch("dhara.backup.cli.BackupCatalog", return_value=catalog) as mock_catalog:
                    args = _args(source=str(source), backup_dir=str(tmp_path / "backups"), type="differential")
                    assert cmd_backup(args) == 0

    mock_catalog.assert_called_once()
    backup_manager.perform_differential_backup.assert_called_once_with(None)
    storage.close.assert_called_once()


def test_cmd_backup_differential_with_prior_full_backup(tmp_path):
    from dhara.backup.cli import cmd_backup

    source = tmp_path / "source.dhara"
    source.write_text("data")
    metadata = SimpleNamespace(backup_id="diff_2", size_bytes=321, source_path=str(source))
    backup_manager = MagicMock()
    backup_manager.perform_differential_backup.return_value = metadata
    catalog = MagicMock()
    catalog.get_last_backup_of_type.return_value = SimpleNamespace(backup_id="full_prev")

    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.FileStorage") as mock_storage_cls:
            storage = MagicMock()
            mock_storage_cls.return_value = storage
            with patch("dhara.backup.cli.BackupManager", return_value=backup_manager):
                with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
                    args = _args(source=str(source), backup_dir=str(tmp_path / "backups"), type="differential")
                    assert cmd_backup(args) == 0

    backup_manager.perform_differential_backup.assert_called_once_with("full_prev")
    storage.close.assert_called_once()


def test_cmd_backup_unknown_type_returns_error(tmp_path):
    from dhara.backup.cli import cmd_backup

    source = tmp_path / "source.dhara"
    source.write_text("data")

    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.FileStorage") as mock_storage_cls:
            storage = MagicMock()
            mock_storage_cls.return_value = storage
            with patch("dhara.backup.cli.BackupManager"):
                args = _args(source=str(source), backup_dir=str(tmp_path / "backups"), type="mystery")
                assert cmd_backup(args) == 1


def test_cmd_backup_key_file_path(tmp_path):
    from dhara.backup.cli import cmd_backup

    source = tmp_path / "source.dhara"
    source.write_text("data")
    key_file = tmp_path / "backup.key"
    key_file.write_bytes(b"manual-key")
    metadata = SimpleNamespace(backup_id="full_3", size_bytes=1, source_path=str(source))
    backup_manager = MagicMock()
    backup_manager.perform_full_backup.return_value = metadata

    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.FileStorage") as mock_storage_cls:
            storage = MagicMock()
            mock_storage_cls.return_value = storage
            with patch("dhara.backup.cli.BackupManager", return_value=backup_manager):
                args = _args(
                    source=str(source),
                    backup_dir=str(tmp_path / "backups"),
                    key_file=str(key_file),
                )
                assert cmd_backup(args) == 0


def test_cmd_backup_key_file_path(tmp_path):
    from dhara.backup.cli import cmd_backup

    source = tmp_path / "source.dhara"
    source.write_text("data")
    key_file = tmp_path / "backup.key"
    key_file.write_bytes(b"manual-key")
    metadata = SimpleNamespace(backup_id="full_3", size_bytes=1, source_path=str(source))
    backup_manager = MagicMock()
    backup_manager.perform_full_backup.return_value = metadata

    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.FileStorage") as mock_storage_cls:
            storage = MagicMock()
            mock_storage_cls.return_value = storage
            with patch("dhara.backup.cli.BackupManager", return_value=backup_manager):
                args = _args(
                    source=str(source),
                    backup_dir=str(tmp_path / "backups"),
                    key_file=str(key_file),
                )
                assert cmd_backup(args) == 0


def test_cmd_backup_encrypts_with_generated_key(tmp_path):
    from dhara.backup.cli import cmd_backup

    source = tmp_path / "source.dhara"
    source.write_text("data")
    metadata = SimpleNamespace(backup_id="full_2", size_bytes=123, source_path=str(source))
    backup_manager = MagicMock()
    backup_manager.perform_full_backup.return_value = metadata

    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.FileStorage") as mock_storage_cls:
            storage = MagicMock()
            mock_storage_cls.return_value = storage
            with patch("dhara.backup.cli.BackupManager", return_value=backup_manager):
                with patch("cryptography.fernet.Fernet.generate_key", return_value=b"enc-key") as mock_key:
                    args = _args(source=str(source), backup_dir=str(tmp_path / "backups"), encrypt=True)
                    assert cmd_backup(args) == 0

    mock_key.assert_called_once()
    backup_manager.perform_full_backup.assert_called_once()
    storage.close.assert_called_once()


def test_cmd_backup_verbose_and_key_file_failure(tmp_path):
    from dhara.backup.cli import cmd_backup

    source = tmp_path / "source.dhara"
    source.write_text("data")
    key_file = tmp_path / "key.bin"
    key_file.write_bytes(b"enc-key")

    backup_manager = MagicMock()
    backup_manager.perform_full_backup.side_effect = RuntimeError("boom")

    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.FileStorage") as mock_storage_cls:
            storage = MagicMock()
            mock_storage_cls.return_value = storage
            with patch("dhara.backup.cli.BackupManager", return_value=backup_manager):
                with patch("builtins.open", mock_open(read_data=b"enc-key")):
                    args = _args(
                        source=str(source),
                        backup_dir=str(tmp_path / "backups"),
                        verbose=True,
                        key_file=str(key_file),
                    )
                    assert cmd_backup(args) == 1

    storage.close.assert_called_once()



def test_cmd_restore_missing_backup_returns_error(tmp_path):
    from dhara.backup.cli import cmd_restore

    args = _args(target=str(tmp_path / "restored.dhara"), backup_dir=str(tmp_path / "backups"), backup_id="nope")
    catalog = MagicMock()
    catalog.get_backup.return_value = None
    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
            assert cmd_restore(args) == 1


def test_cmd_restore_latest_backup_with_verify(tmp_path):
    from dhara.backup.cli import cmd_restore

    source_backup = SimpleNamespace(backup_id="b1")
    catalog = MagicMock()
    catalog.get_last_backup.return_value = source_backup
    restore_manager = MagicMock()
    restore_manager.verify_restore.return_value = True

    args = _args(target=str(tmp_path / "restored.dhara"), backup_dir=str(tmp_path / "backups"), verify=True)
    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
            with patch("dhara.backup.cli.RestoreManager", return_value=restore_manager):
                assert cmd_restore(args) == 0

    restore_manager._restore_from_backup.assert_called_once_with(source_backup)
    restore_manager.verify_restore.assert_called_once_with(source_backup)


def test_cmd_restore_timestamp_branch(tmp_path):
    from dhara.backup.cli import cmd_restore

    restore_manager = MagicMock()

    args = _args(
        target=str(tmp_path / "restored.dhara"),
        backup_dir=str(tmp_path / "backups"),
        timestamp="2024-01-01 12:30:00",
    )
    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.RestoreManager", return_value=restore_manager):
            assert cmd_restore(args) == 0

    restore_manager.restore_point_in_time.assert_called_once_with(datetime(2024, 1, 1, 12, 30, 0))


def test_cmd_restore_backup_id_and_key_file(tmp_path):
    from dhara.backup.cli import cmd_restore

    backup = SimpleNamespace(backup_id="b42")
    catalog = MagicMock()
    catalog.get_backup.return_value = backup
    restore_manager = MagicMock()

    key_file = tmp_path / "restore.key"
    key_file.write_bytes(b"restore-key")
    args = _args(
        target=str(tmp_path / "restored.dhara"),
        backup_dir=str(tmp_path / "backups"),
        backup_id="b42",
        key_file=str(key_file),
    )
    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
            with patch("dhara.backup.cli.RestoreManager", return_value=restore_manager):
                assert cmd_restore(args) == 0

    restore_manager._restore_from_backup.assert_called_once_with(backup)


def test_cmd_restore_verbose_latest_and_verify_failure(tmp_path):
    from dhara.backup.cli import cmd_restore

    backup = SimpleNamespace(backup_id="b7")
    catalog = MagicMock()
    catalog.get_last_backup.return_value = backup
    restore_manager = MagicMock()
    restore_manager.verify_restore.return_value = False

    args = _args(
        target=str(tmp_path / "restored.dhara"),
        backup_dir=str(tmp_path / "backups"),
        verbose=True,
        verify=True,
    )
    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
            with patch("dhara.backup.cli.RestoreManager", return_value=restore_manager):
                assert cmd_restore(args) == 0

    restore_manager._restore_from_backup.assert_called_once_with(backup)
    restore_manager.verify_restore.assert_called_once_with(backup)


def test_cmd_restore_backup_missing_and_failure(tmp_path):
    from dhara.backup.cli import cmd_restore

    catalog = MagicMock()
    catalog.get_backup.return_value = None
    failing_restore = MagicMock()
    failing_restore._restore_from_backup.side_effect = RuntimeError("boom")

    args = _args(target=str(tmp_path / "restored.dhara"), backup_dir=str(tmp_path / "backups"), backup_id="missing")
    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
            assert cmd_restore(args) == 1

    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=MagicMock(get_last_backup=MagicMock(return_value=None))):
            assert cmd_restore(_args(target=str(tmp_path / "restored3.dhara"), backup_dir=str(tmp_path / "backups"))) == 1

    args2 = _args(target=str(tmp_path / "restored2.dhara"), backup_dir=str(tmp_path / "backups"))
    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=MagicMock(get_last_backup=MagicMock(return_value=SimpleNamespace(backup_id="b1")))):
            with patch("dhara.backup.cli.RestoreManager", return_value=failing_restore):
                assert cmd_restore(args2) == 1


def test_cmd_list_json_format(tmp_path, capsys):
    from dhara.backup.cli import cmd_list

    backup = SimpleNamespace(
        backup_id="b1",
        backup_type=SimpleNamespace(value="full"),
        timestamp=__import__("datetime").datetime(2024, 1, 1, 12, 0, 0),
        to_dict=lambda: {"backup_id": "b1"},
    )
    catalog = MagicMock()
    catalog.search_backups.return_value = [backup]
    args = _args(backup_dir=str(tmp_path), format="json")
    with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
        assert cmd_list(args) == 0
    out = capsys.readouterr().out
    assert '"backup_id": "b1"' in out


def test_cmd_list_empty_table_returns_zero(tmp_path, capsys):
    from dhara.backup.cli import cmd_list

    catalog = MagicMock()
    catalog.search_backups.return_value = []
    args = _args(backup_dir=str(tmp_path), format="table")
    with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
        assert cmd_list(args) == 0
    assert "No backups found" in capsys.readouterr().out


def test_cmd_list_table_and_failure(tmp_path, capsys):
    from dhara.backup.cli import cmd_list

    backup = SimpleNamespace(
        backup_id="b1",
        backup_type=SimpleNamespace(value="full"),
        size_bytes=1024 * 1024,
        timestamp=datetime(2024, 1, 1, 12, 0, 0),
    )
    catalog = MagicMock()
    catalog.search_backups.return_value = [backup]
    args = _args(backup_dir=str(tmp_path), format="table")
    with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
        assert cmd_list(args) == 0

    assert "Backup ID" in capsys.readouterr().out

    with patch("dhara.backup.cli.BackupCatalog", side_effect=RuntimeError("boom")):
        assert cmd_list(args) == 1


def test_cmd_list_since_filter_parses_date(tmp_path):
    from dhara.backup.cli import cmd_list

    catalog = MagicMock()
    catalog.search_backups.return_value = []
    args = _args(backup_dir=str(tmp_path), since="2024-01-02")
    with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
        assert cmd_list(args) == 0
    catalog.search_backups.assert_called_once()


def test_cmd_verify_all_backups(tmp_path, capsys):
    from dhara.backup.cli import cmd_verify

    backup = SimpleNamespace(backup_id="b1")
    result = SimpleNamespace(status="passed", message="ok")
    catalog = MagicMock()
    catalog.get_all_backups.return_value = [backup]
    verification = MagicMock()
    verification.run_all_checks.return_value = {"integrity": result}
    verification.generate_verification_report.return_value = {"report": True}

    args = _args(backup_dir=str(tmp_path), all=True, output=str(tmp_path / "report.json"))
    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
            with patch("dhara.backup.cli.BackupVerification", return_value=verification):
                with patch("builtins.open", mock_open()):
                    assert cmd_verify(args) == 0

    assert "✓ integrity: ok" in capsys.readouterr().out


def test_cmd_verify_missing_latest_backup_returns_error(tmp_path):
    from dhara.backup.cli import cmd_verify

    catalog = MagicMock()
    catalog.get_last_backup.return_value = None
    args = _args(backup_dir=str(tmp_path))
    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
            assert cmd_verify(args) == 1


def test_cmd_verify_report_and_failure_exception(tmp_path):
    from dhara.backup.cli import cmd_verify

    backup = SimpleNamespace(backup_id="b1")
    failed = SimpleNamespace(status="failed", message="bad")
    catalog = MagicMock()
    catalog.get_all_backups.return_value = [backup]
    verification = MagicMock()
    verification.run_all_checks.return_value = {"integrity": failed}
    verification.generate_verification_report.return_value = {"report": True}

    args = _args(backup_dir=str(tmp_path), all=True, output=str(tmp_path / "report.json"))
    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
            with patch("dhara.backup.cli.BackupVerification", return_value=verification):
                with patch("builtins.open", mock_open()):
                    assert cmd_verify(args) == 1

    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", side_effect=RuntimeError("boom")):
            assert cmd_verify(_args(backup_dir=str(tmp_path))) == 1


def test_cmd_verify_single_backup_with_failure_marks_nonzero(tmp_path, capsys):
    from dhara.backup.cli import cmd_verify

    backup = SimpleNamespace(backup_id="b1")
    failed = SimpleNamespace(status="failed", message="bad")
    catalog = MagicMock()
    catalog.get_backup.return_value = backup
    verification = MagicMock()
    verification.run_all_checks.return_value = {"integrity": failed}

    args = _args(backup_dir=str(tmp_path), backup_id="b1")
    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
            with patch("dhara.backup.cli.BackupVerification", return_value=verification):
                assert cmd_verify(args) == 1

    assert "✗ integrity: bad" in capsys.readouterr().out


def test_cmd_verify_verbose_and_missing_backup(tmp_path):
    from dhara.backup.cli import cmd_verify

    backup = SimpleNamespace(backup_id="b1")
    catalog = MagicMock()
    catalog.get_backup.return_value = backup
    verification = MagicMock()
    verification.run_all_checks.return_value = {"integrity": SimpleNamespace(status="passed", message="ok")}

    args = _args(backup_dir=str(tmp_path), backup_id="b1", verbose=True)
    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
            with patch("dhara.backup.cli.BackupVerification", return_value=verification):
                assert cmd_verify(args) == 0

    with patch("dhara.backup.cli.init_backup_directory"):
        with patch("dhara.backup.cli.BackupCatalog", return_value=MagicMock(get_backup=MagicMock(return_value=None))):
            assert cmd_verify(_args(backup_dir=str(tmp_path), backup_id="missing")) == 1


def test_cmd_schedule_status(tmp_path, capsys):
    from dhara.backup.cli import cmd_schedule

    catalog = MagicMock()
    catalog.get_backup_statistics.return_value = {
        "total_backups": 2,
        "total_size_mb": 1.5,
        "retention_compliance": 75.0,
    }
    args = _args(action="status", backup_dir=str(tmp_path))
    with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
        assert cmd_schedule(args) == 0
    assert "Total backups: 2" in capsys.readouterr().out


def test_cmd_schedule_unimplemented_actions_return_error(capsys):
    from dhara.backup.cli import cmd_schedule

    for action in ("start", "stop", "add"):
        assert cmd_schedule(_args(action=action)) == 1

    out = capsys.readouterr().out
    assert "Scheduled backup management would start here" in out


def test_cmd_schedule_unknown_action_returns_none():
    from dhara.backup.cli import cmd_schedule

    assert cmd_schedule(_args(action="bogus")) is None


def test_cmd_schedule_status_failure(tmp_path):
    from dhara.backup.cli import cmd_schedule

    args = _args(action="status", backup_dir=str(tmp_path))
    with patch("dhara.backup.cli.BackupCatalog", side_effect=RuntimeError("boom")):
        assert cmd_schedule(args) == 1


def test_cmd_catalog_branches(tmp_path, capsys):
    from dhara.backup.cli import cmd_catalog

    backup = SimpleNamespace(
        backup_id="b1",
        backup_type=SimpleNamespace(value="full"),
        timestamp="2024-01-01",
    )
    catalog = MagicMock()
    catalog.get_all_backups.return_value = [backup]
    catalog.get_backup_statistics.return_value = {"a": 1}
    catalog.cleanup_expired_backups.return_value = 3
    catalog.validate_catalog_integrity.return_value = []
    catalog.export_catalog.return_value = None
    catalog.import_catalog.return_value = 7

    with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
        assert cmd_catalog(_args(action="list", backup_dir=str(tmp_path))) == 0
        assert cmd_catalog(_args(action="stats", backup_dir=str(tmp_path))) == 0
        assert cmd_catalog(_args(action="cleanup", backup_dir=str(tmp_path))) == 0
        assert cmd_catalog(_args(action="validate", backup_dir=str(tmp_path))) == 0
        assert cmd_catalog(_args(action="export", export=str(tmp_path / "cat.json"), backup_dir=str(tmp_path))) == 0
        assert cmd_catalog(
            _args(action="import", **{"import": str(tmp_path / "cat.json")}, backup_dir=str(tmp_path))
        ) == 0

    out = capsys.readouterr().out
    assert "Catalog contents:" in out
    assert "Catalog statistics:" in out
    assert "Removed 3 expired backups" in out
    assert "Catalog validation: PASSED" in out
    assert "Catalog exported" in out
    assert "Imported 7 backups" in out


def test_cmd_catalog_import_missing_value_and_unknown_action(tmp_path):
    from dhara.backup.cli import cmd_catalog

    catalog = MagicMock()
    with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
        assert cmd_catalog(_args(action="import", backup_dir=str(tmp_path))) == 0
        assert cmd_catalog(_args(action="other", backup_dir=str(tmp_path))) == 0


def test_cmd_catalog_import_with_value(tmp_path):
    from dhara.backup.cli import cmd_catalog

    catalog = MagicMock()
    catalog.import_catalog.return_value = 2
    with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
        assert cmd_catalog(
            _args(action="import", backup_dir=str(tmp_path), **{"import": str(tmp_path / "cat.json")})
        ) == 0


def test_cmd_catalog_import_with_value(tmp_path):
    from dhara.backup.cli import cmd_catalog

    catalog = MagicMock()
    catalog.import_catalog.return_value = 2
    with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
        assert cmd_catalog(_args(action="import", backup_dir=str(tmp_path), **{"import": str(tmp_path / "cat.json")})) == 0


def test_cmd_catalog_empty_list_and_failure(tmp_path, capsys):
    from dhara.backup.cli import cmd_catalog

    catalog = MagicMock()
    catalog.get_all_backups.return_value = []
    with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
        assert cmd_catalog(_args(action="list", backup_dir=str(tmp_path))) == 0
    assert "No backups in catalog" in capsys.readouterr().out

    with patch("dhara.backup.cli.BackupCatalog", side_effect=RuntimeError("boom")):
        assert cmd_catalog(_args(action="stats", backup_dir=str(tmp_path))) == 1


def test_cmd_catalog_validate_with_issues(tmp_path, capsys):
    from dhara.backup.cli import cmd_catalog

    catalog = MagicMock()
    catalog.validate_catalog_integrity.return_value = ["missing entry", "corrupt checksum"]
    args = _args(action="validate", backup_dir=str(tmp_path))
    with patch("dhara.backup.cli.BackupCatalog", return_value=catalog):
        assert cmd_catalog(args) == 0

    out = capsys.readouterr().out
    assert "Catalog validation issues found:" in out
    assert "missing entry" in out


def test_cmd_cloud_returns_error():
    from dhara.backup.cli import cmd_cloud

    assert cmd_cloud(_args()) == 1


def test_cmd_config_show_generate_and_init(tmp_path):
    from dhara.backup.cli import cmd_config

    assert cmd_config(_args(action="show")) == 0

    key_file = tmp_path / "k" / "key.bin"
    with patch("dhara.backup.cli.generate_encryption_key") as mock_key:
        assert cmd_config(_args(action="generate-key", key_file=str(key_file))) == 0
    mock_key.assert_called_once_with(str(key_file))

    assert cmd_config(_args(action="generate-key")) == 1

    with patch("dhara.backup.cli.init_backup_directory") as mock_init:
        assert cmd_config(_args(action="init-dir", backup_dir=str(tmp_path / "b"))) == 0
    mock_init.assert_called_once()

    assert cmd_config(_args(action="other")) == 0


def test_cmd_config_generate_key_missing_file_returns_error():
    from dhara.backup.cli import cmd_config

    assert cmd_config(_args(action="generate-key", key_file=None)) == 1


def test_cmd_config_generate_key_uses_missing_file_error():
    from dhara.backup.cli import cmd_config

    assert cmd_config(_args(action="generate-key", key_file=None)) == 1


def test_main_without_command_prints_help():
    from dhara.backup.cli import main

    parser = MagicMock()
    parser.parse_args.return_value = _args(command=None)
    with patch("dhara.backup.cli.setup_parser", return_value=parser):
        assert main() == 1
    parser.print_help.assert_called_once()


def test_main_unknown_command_returns_error():
    from dhara.backup.cli import main

    parser = MagicMock()
    parser.parse_args.return_value = _args(command="unknown")
    with patch("dhara.backup.cli.setup_parser", return_value=parser):
        assert main() == 1


def test_main_dispatches_handler(tmp_path):
    from dhara.backup.cli import main

    args = _args(command="cloud")
    parser = MagicMock()
    parser.parse_args.return_value = args
    with patch("dhara.backup.cli.setup_parser", return_value=parser):
        assert main() == 1


def test_main_dispatches_backup_handler(tmp_path):
    from dhara.backup.cli import main

    args = _args(command="backup")
    parser = MagicMock()
    parser.parse_args.return_value = args
    with patch("dhara.backup.cli.setup_parser", return_value=parser):
        with patch("dhara.backup.cli.cmd_backup", return_value=7) as mock_handler:
            assert main() == 7
    mock_handler.assert_called_once_with(args)
