#!/usr/bin/env python3
"""
Command-line interface for Durus backup and restore operations.

This CLI provides easy-to-use commands for:
- Creating backups
- Restoring databases
- Managing backup schedules
- Verifying backups
- Cloud storage operations
"""

import argparse
import logging
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from druva.file_storage import FileStorage
from druva.backup.manager import BackupManager, BackupType
from druva.backup.restore import RestoreManager
from druva.backup.catalog import BackupCatalog
from druva.backup.scheduler import BackupScheduler
from druva.backup.verification import BackupVerification
from druva.backup.storage import StorageFactory

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def setup_parser():
    """Set up command-line argument parser."""
    parser = argparse.ArgumentParser(
        description='Durus Backup and Restore CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s backup --source my_db.durus --type full --backup-dir ./backups
  %(prog)s restore --source my_db.durus --target restored_db.durus
  %(prog)s list --backup-dir ./backups
  %(prog)s verify --backup-id full_backup_20240101
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Backup command
    backup_parser = subparsers.add_parser('backup', help='Create a backup')
    backup_parser.add_argument('--source', required=True, help='Source database file')
    backup_parser.add_argument('--backup-dir', default='./backups', help='Backup directory')
    backup_parser.add_argument('--type', choices=['full', 'incremental', 'differential'],
                              default='full', help='Backup type')
    backup_parser.add_argument('--compression-level', type=int, default=3,
                              choices=range(1, 20), help='ZSTD compression level')
    backup_parser.add_argument('--encrypt', action='store_true', help='Enable encryption')
    backup_parser.add_argument('--key-file', help='Encryption key file')
    backup_provider = backup_parser.add_mutually_exclusive_group()
    backup_provider.add_argument('--cloud-provider', choices=['s3', 'gcs', 'azure'],
                                 help='Cloud storage provider')
    backup_provider.add_argument('--cloud-upload', action='store_true',
                                 help='Upload to configured cloud storage')
    backup_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    # Restore command
    restore_parser = subparsers.add_parser('restore', help='Restore a database')
    restore_parser.add_argument('--target', required=True, help='Target database file')
    restore_parser.add_argument('--backup-dir', default='./backups', help='Backup directory')
    restore_parser.add_argument('--backup-id', help='Specific backup ID to restore')
    restore_parser.add_argument('--timestamp', help='Timestamp to restore to (YYYY-MM-DD HH:MM:SS)')
    restore_parser.add_argument('--type', choices=['full', 'incremental', 'differential'],
                               help='Backup type filter')
    restore_parser.add_argument('--verify', action='store_true', help='Verify restore')
    restore_parser.add_argument('--key-file', help='Encryption key file')
    restore_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    # List command
    list_parser = subparsers.add_parser('list', help='List available backups')
    list_parser.add_argument('--backup-dir', default='./backups', help='Backup directory')
    list_parser.add_argument('--type', choices=['full', 'incremental', 'differential'],
                           help='Filter by backup type')
    list_parser.add_argument('--since', help='Show backups since date (YYYY-MM-DD)')
    list_parser.add_argument('--format', choices=['table', 'json'], default='table',
                           help='Output format')

    # Verify command
    verify_parser = subparsers.add_parser('verify', help='Verify backup integrity')
    verify_parser.add_argument('--backup-dir', default='./backups', help='Backup directory')
    verify_parser.add_argument('--backup-id', help='Specific backup ID to verify')
    verify_parser.add_argument('--type', choices=['full', 'incremental', 'differential'],
                             help='Backup type filter')
    verify_parser.add_argument('--all', action='store_true', help='Verify all backups')
    verify_parser.add_argument('--test-restore', action='store_true',
                              help='Perform test restore')
    verify_parser.add_argument('--output', help='Output file for report')
    verify_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    # Schedule command
    schedule_parser = subparsers.add_parser('schedule', help='Manage backup schedules')
    schedule_parser.add_argument('--action', choices=['start', 'stop', 'status', 'add'],
                                required=True, help='Action to perform')
    schedule_parser.add_argument('--backup-dir', default='./backups', help='Backup directory')
    schedule_parser.add_argument('--source', help='Source database file')
    schedule_parser.add_argument('--name', help='Schedule name')
    schedule_parser.add_argument('--type', choices=['full', 'incremental', 'differential'],
                               help='Backup type')
    schedule_parser.add_argument('--schedule', help='Schedule specification')
    schedule_parser.add_argument('--retention', type=int, help='Retention period in days')
    schedule_parser.add_argument('--daemon', action='store_true', help='Run as daemon')

    # Catalog command
    catalog_parser = subparsers.add_parser('catalog', help='Manage backup catalog')
    catalog_parser.add_argument('--action', choices=['list', 'stats', 'cleanup', 'validate'],
                               required=True, help='Action to perform')
    catalog_parser.add_argument('--backup-dir', default='./backups', help='Backup directory')
    catalog_parser.add_argument('--export', help='Export catalog file')
    catalog_parser.add_argument('--import', help='Import catalog file')

    # Cloud command
    cloud_parser = subparsers.add_parser('cloud', help='Cloud storage operations')
    cloud_parser.add_argument('--action', choices=['sync', 'list', 'delete'],
                             required=True, help='Action to perform')
    cloud_parser.add_argument('--backup-dir', default='./backups', help='Backup directory')
    cloud_parser.add_argument('--provider', choices=['s3', 'gcs', 'azure'],
                             required=True, help='Cloud provider')
    cloud_parser.add_argument('--bucket', help='Cloud bucket/container name')
    cloud_parser.add_argument('--prefix', default='', help='Path prefix')
    cloud_parser.add_argument('--backup-id', help='Specific backup ID')

    # Config command
    config_parser = subparsers.add_parser('config', help='Configuration utilities')
    config_parser.add_argument('--action', choices=['show', 'generate-key', 'init-dir'],
                              required=True, help='Action to perform')
    config_parser.add_argument('--key-file', help='Key file path')
    config_parser.add_argument('--backup-dir', default='./backups', help='Backup directory')

    return parser


def generate_encryption_key(key_file: str):
    """Generate and save encryption key."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()

    key_path = Path(key_file)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    with open(key_path, 'wb') as f:
        f.write(key)

    logger.info(f"Encryption key generated and saved to: {key_file}")
    logger.info(f"Key: {key.decode()}")
    logger.warning("Store this key securely!")


def init_backup_directory(backup_dir: str):
    """Initialize backup directory structure."""
    path = Path(backup_dir)
    path.mkdir(parents=True, exist_ok=True)

    # Create basic structure
    (path / "catalog").mkdir(exist_ok=True)
    (path / "logs").mkdir(exist_ok=True)
    (path / "temp").mkdir(exist_ok=True)

    logger.info(f"Backup directory initialized: {backup_dir}")


def cmd_backup(args):
    """Handle backup command."""
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info(f"Creating {args.type} backup of {args.source}")

    # Validate source
    if not Path(args.source).exists():
        logger.error(f"Source database not found: {args.source}")
        return 1

    # Initialize backup directory
    init_backup_directory(args.backup_dir)

    # Load encryption key if specified
    encryption_key = None
    if args.encrypt or args.key_file:
        from cryptography.fernet import Fernet
        if args.key_file:
            with open(args.key_file, 'rb') as f:
                encryption_key = f.read()
        else:
            encryption_key = Fernet.generate_key()
        logger.info("Encryption enabled")

    # Create backup manager
    storage = FileStorage(args.source)
    backup_manager = BackupManager(
        storage=storage,
        backup_dir=args.backup_dir,
        compression_level=args.compression_level,
        encryption_key=encryption_key
    )

    # Perform backup
    try:
        if args.type == 'full':
            metadata = backup_manager.perform_full_backup()
        elif args.type == 'incremental':
            catalog = BackupCatalog(args.backup_dir)
            last_backup = catalog.get_last_backup()
            metadata = backup_manager.perform_incremental_backup(
                last_backup.backup_id if last_backup else None
            )
        elif args.type == 'differential':
            catalog = BackupCatalog(args.backup_dir)
            last_full = catalog.get_last_backup_of_type(BackupType.FULL)
            metadata = backup_manager.perform_differential_backup(
                last_full.backup_id if last_full else None
            )

        logger.info(f"Backup created: {metadata.backup_id}")
        logger.info(f"Size: {metadata.size_bytes} bytes")
        logger.info(f"Path: {metadata.source_path}")

        storage.close()
        return 0

    except Exception as e:
        logger.error(f"Backup failed: {e}")
        storage.close()
        return 1


def cmd_restore(args):
    """Handle restore command."""
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Initialize backup directory
    init_backup_directory(args.backup_dir)

    # Load encryption key if specified
    encryption_key = None
    if args.key_file:
        with open(args.key_file, 'rb') as f:
            encryption_key = f.read()

    # Create restore manager
    restore_manager = RestoreManager(
        target_path=args.target,
        backup_dir=args.backup_dir,
        encryption_key=encryption_key
    )

    try:
        # Find backup
        if args.backup_id:
            catalog = BackupCatalog(args.backup_dir)
            backup = catalog.get_backup(args.backup_id)
            if not backup:
                logger.error(f"Backup not found: {args.backup_id}")
                return 1
            restore_path = restore_manager._restore_from_backup(backup)
        elif args.timestamp:
            target_time = datetime.strptime(args.timestamp, '%Y-%m-%d %H:%M:%S')
            restore_path = restore_manager.restore_point_in_time(target_time)
        else:
            # Use latest backup
            catalog = BackupCatalog(args.backup_dir)
            backup = catalog.get_last_backup()
            if not backup:
                logger.error("No backups found")
                return 1
            restore_path = restore_manager._restore_from_backup(backup)

        logger.info(f"Database restored to: {args.target}")

        # Verify restore if requested
        if args.verify and backup:
            is_valid = restore_manager.verify_restore(backup)
            if is_valid:
                logger.info("Restore verification: PASSED")
            else:
                logger.warning("Restore verification: FAILED")

        return 0

    except Exception as e:
        logger.error(f"Restore failed: {e}")
        return 1


def cmd_list(args):
    """Handle list command."""
    try:
        catalog = BackupCatalog(args.backup_dir)

        # Filter backups
        start_time = None
        if args.since:
            start_time = datetime.strptime(args.since, '%Y-%m-%d')

        backups = catalog.search_backups(
            start_time=start_time,
            backup_type=BackupType(args.type) if args.type else None
        )

        if args.format == 'json':
            import json
            data = [b.to_dict() for b in backups]
            print(json.dumps(data, indent=2))
        else:
            # Table format
            if not backups:
                print("No backups found")
                return 0

            print(f"{'Backup ID':<25} {'Type':<12} {'Size':>10} {'Date':<20}")
            print("-" * 70)

            for backup in sorted(backups, key=lambda b: b.timestamp, reverse=True):
                size_mb = backup.size_bytes / (1024 * 1024)
                print(f"{backup.backup_id:<25} {backup.backup_type.value:<12} "
                      f"{size_mb:>8.1f} MB {backup.timestamp.strftime('%Y-%m-%d %H:%M')}")

        return 0

    except Exception as e:
        logger.error(f"List command failed: {e}")
        return 1


def cmd_verify(args):
    """Handle verify command."""
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    init_backup_directory(args.backup_dir)
    verification = BackupVerification(
        backup_dir=args.backup_dir,
        test_restore_dir=os.path.join(args.backup_dir, "test_restores")
    )

    try:
        # Get backups to verify
        catalog = BackupCatalog(args.backup_dir)

        if args.backup_id:
            backup = catalog.get_backup(args.backup_id)
            if not backup:
                logger.error(f"Backup not found: {args.backup_id}")
                return 1
            backups_to_verify = [backup]
        elif args.all:
            backups_to_verify = catalog.get_all_backups()
        else:
            # Use most recent backup
            backups_to_verify = [catalog.get_last_backup()]
            if not backups_to_verify[0]:
                logger.error("No backups found")
                return 1

        # Verify each backup
        all_passed = True
        for backup in backups_to_verify:
            logger.info(f"Verifying backup: {backup.backup_id}")

            results = verification.run_all_checks(backup)

            for check_name, result in results.items():
                status_icon = "✓" if result.status == "passed" else "✗" if result.status == "failed" else "⚠"
                print(f"{status_icon} {check_name}: {result.message}")

                if result.status == "failed":
                    all_passed = False

        # Generate report if requested
        if args.output:
            report = verification.generate_verification_report(backups_to_verify[0] if len(backups_to_verify) == 1 else None)

            with open(args.output, 'w') as f:
                import json
                json.dump(report, f, indent=2)

            logger.info(f"Verification report saved to: {args.output}")

        return 0 if all_passed else 1

    except Exception as e:
        logger.error(f"Verification failed: {e}")
        return 1


def cmd_schedule(args):
    """Handle schedule command."""
    if args.action == 'status':
        try:
            catalog = BackupCatalog(args.backup_dir)
            stats = catalog.get_backup_statistics()

            print("Backup Statistics:")
            print(f"  Total backups: {stats['total_backups']}")
            print(f"  Total size: {stats['total_size_mb']:.2f} MB")
            print(f"  Retention compliance: {stats['retention_compliance']:.1f}%")

            return 0
        except Exception as e:
            logger.error(f"Schedule status failed: {e}")
            return 1

    elif args.action in ['start', 'stop', 'add']:
        logger.warning(f"Schedule {args.action} not fully implemented in this demo")
        print(f"Scheduled backup management would {args.action} here")
        return 1


def cmd_catalog(args):
    """Handle catalog command."""
    try:
        catalog = BackupCatalog(args.backup_dir)

        if args.action == 'list':
            backups = catalog.get_all_backups()
            if not backups:
                print("No backups in catalog")
                return 0

            print("Catalog contents:")
            for backup in backups:
                print(f"  {backup.backup_id}: {backup.backup_type.value} at {backup.timestamp}")

        elif args.action == 'stats':
            stats = catalog.get_backup_statistics()
            print("Catalog statistics:")
            for key, value in stats.items():
                print(f"  {key}: {value}")

        elif args.action == 'cleanup':
            removed = catalog.cleanup_expired_backups()
            print(f"Removed {removed} expired backups from catalog")

        elif args.action == 'validate':
            issues = catalog.validate_catalog_integrity()
            if issues:
                print("Catalog validation issues found:")
                for issue in issues:
                    print(f"  - {issue}")
            else:
                print("Catalog validation: PASSED")

        elif args.action == 'export' and args.export:
            catalog.export_catalog(args.export)
            print(f"Catalog exported to: {args.export}")

        elif args.action == 'import' and args.import:
            imported = catalog.import_catalog(args.import)
            print(f"Imported {imported} backups from catalog")

        return 0

    except Exception as e:
        logger.error(f"Catalog command failed: {e}")
        return 1


def cmd_cloud(args):
    """Handle cloud command."""
    logger.warning("Cloud operations require additional configuration")
    print("Cloud storage setup would happen here")
    return 1


def cmd_config(args):
    """Handle config command."""
    if args.action == 'show':
        print("Current configuration would be displayed here")

    elif args.action == 'generate-key':
        if not args.key_file:
            logger.error("Key file required for generate-key")
            return 1
        generate_encryption_key(args.key_file)

    elif args.action == 'init-dir':
        init_backup_directory(args.backup_dir)

    return 0


def main():
    """Main CLI entry point."""
    parser = setup_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Route to appropriate handler
    command_handlers = {
        'backup': cmd_backup,
        'restore': cmd_restore,
        'list': cmd_list,
        'verify': cmd_verify,
        'schedule': cmd_schedule,
        'catalog': cmd_catalog,
        'cloud': cmd_cloud,
        'config': cmd_config
    }

    handler = command_handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        logger.error(f"Unknown command: {args.command}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
