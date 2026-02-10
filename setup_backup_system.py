#!/usr/bin/env python3
"""
Setup script for the Durus backup and restore system.

This script:
1. Installs required dependencies
2. Runs tests
3. Sets up example databases
4. Demonstrates functionality
"""

import os
import sys
import subprocess
import tempfile
import shutil
from pathlib import Path

def run_command(cmd, description=None, check=True):
    """Run a command with error handling."""
    if description:
        print(f"\n{'='*60}")
        print(f"STEP: {description}")
        print(f"COMMAND: {' '.join(cmd)}")
        print('='*60)

    try:
        result = subprocess.run(cmd, check=check, capture_output=True, text=True)
        if result.stdout:
            print("STDOUT:")
            print(result.stdout)
        return result
    except subprocess.CalledProcessError as e:
        print(f"ERROR: {e}")
        print("STDERR:")
        print(e.stderr)
        if check:
            sys.exit(1)
        return e

def install_dependencies():
    """Install required dependencies."""
    print("Installing dependencies for Durus backup system...")

    # Core dependencies
    run_command([
        sys.executable, "-m", "pip", "install",
        "cryptography", "zstandard", "schedule"
    ], "Installing core dependencies")

    # Cloud storage dependencies (optional)
    run_command([
        sys.executable, "-m", "pip", "install",
        "boto3", "google-cloud-storage", "azure-storage-blob"
    ], "Installing cloud storage dependencies")

    # Test dependencies
    run_command([
        sys.executable, "-m", "pip", "install",
        "pytest", "pytest-cov", "pytest-mock"
    ], "Installing test dependencies")

def create_test_database(path: str):
    """Create a test database."""
    print(f"Creating test database at {path}")

    # Import durus and create database
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from dhruva.file_storage import FileStorage
    from dhruva.persistent_dict import PersistentDict
    from datetime import datetime

    # Create storage
    storage = FileStorage(path)
    root = PersistentDict()

    # Add test data
    root["metadata"] = {
        "created": datetime.now().isoformat(),
        "type": "test_database",
        "records": 1000
    }

    # Add sample records
    for i in range(1000):
        root[f"record_{i}"] = {
            "id": i,
            "name": f"User {i}",
            "email": f"user{i}@example.com",
            "data": f"Sample data {i}" * 10
        }

    storage.store(root)
    storage.close()

    print(f"Test database created with {len(root['record_0'].keys()) * 1000} records")

def run_tests():
    """Run backup system tests."""
    print("\nRunning backup system tests...")

    # Change to project directory
    project_dir = Path(__file__).parent
    os.chdir(project_dir)

    # Run integration tests
    test_result = run_command([
        sys.executable, "-m", "pytest",
        "tests/integration/test_backup_restore.py",
        "-v", "--cov=backup", "--cov-report=html"
    ], "Running integration tests with coverage")

    if test_result.returncode == 0:
        print("\n✓ All tests passed!")
    else:
        print("\n✗ Some tests failed")

    return test_result.returncode == 0

def run_demo():
    """Run the backup system demonstration."""
    print("\nRunning backup system demonstration...")

    # Change to project directory
    project_dir = Path(__file__).parent
    os.chdir(project_dir)

    # Run the example script
    demo_result = run_command([
        sys.executable, "examples/backup_example.py"
    ], "Running backup system demonstration")

    return demo_result.returncode == 0

def create_cli_test():
    """Test the CLI functionality."""
    print("\nTesting CLI functionality...")

    # Create test database
    test_dir = tempfile.mkdtemp(prefix="durus_cli_test_")
    db_path = os.path.join(test_dir, "test_db.durus")
    backup_dir = os.path.join(test_dir, "backups")

    try:
        create_test_database(db_path)

        # Test backup command
        print("\nTesting backup command...")
        result = run_command([
            sys.executable, "-m", "durus.backup.cli",
            "backup",
            "--source", db_path,
            "--backup-dir", backup_dir,
            "--type", "full",
            "--verbose"
        ], "Creating backup via CLI")

        if result.returncode == 0:
            print("✓ Backup command successful")
        else:
            print("✗ Backup command failed")
            return False

        # Test list command
        print("\nTesting list command...")
        result = run_command([
            sys.executable, "-m", "durus.backup.cli",
            "list",
            "--backup-dir", backup_dir
        ], "Listing backups via CLI")

        if result.returncode == 0:
            print("✓ List command successful")
        else:
            print("✗ List command failed")
            return False

        # Test restore command
        print("\nTesting restore command...")
        restore_dir = os.path.join(test_dir, "restored_db")
        result = run_command([
            sys.executable, "-m", "durus.backup.cli",
            "restore",
            "--target", restore_dir,
            "--backup-dir", backup_dir,
            "--verify"
        ], "Restoring via CLI")

        if result.returncode == 0:
            print("✓ Restore command successful")
        else:
            print("✗ Restore command failed")
            return False

        return True

    finally:
        # Cleanup
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

def create_sample_configuration():
    """Create sample configuration files."""
    print("\nCreating sample configuration files...")

    config_dir = Path(__file__).parent / "config"
    config_dir.mkdir(exist_ok=True)

    # Sample backup configuration
    backup_config = """
# Durus Backup Configuration
[general]
backup_dir = ./backups
compression_level = 3
verification_enabled = true

[encryption]
enabled = false
key_file = ./backup.key

[retention]
full_days = 30
incremental_days = 7
differential_days = 14

[scheduling]
auto_start = true
verification_interval = 3600

[cloud]
provider = s3
bucket = durus-backups
enabled = false
"""

    config_file = config_dir / "backup.conf"
    with open(config_file, 'w') as f:
        f.write(backup_config)

    print(f"Sample configuration created: {config_file}")

    # Generate encryption key
    key_file = config_dir / "backup.key"
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    with open(key_file, 'wb') as f:
        f.write(key)

    print(f"Encryption key generated: {key_file}")
    print("WARNING: Store this key securely!")

def create_documentation():
    """Create additional documentation."""
    print("\nGenerating documentation...")

    doc_dir = Path(__file__).parent / "docs"

    # API documentation
    api_doc = """
# Durus Backup System API Documentation

## BackupManager

The `BackupManager` class is the main interface for creating backups.

### Constructor
```python
BackupManager(
    storage,                    # Durus storage instance
    backup_dir="./backups",     # Backup directory
    compression_level=3,        # ZSTD compression level
    encryption_key=None,        # Optional encryption key
    cloud_adapter=None,         # Optional cloud adapter
    retention_policy=None       # Retention policy
)
```

### Methods
- `perform_full_backup()` - Create full backup
- `perform_incremental_backup(last_backup_id)` - Create incremental backup
- `perform_differential_backup(last_full_id)` - Create differential backup
- `upload_to_cloud(metadata)` - Upload to cloud storage
- `cleanup_old_backups()` - Remove expired backups

## RestoreManager

The `RestoreManager` class handles database restoration.

### Constructor
```python
RestoreManager(
    target_path,               # Target database path
    backup_dir="./backups",     # Backup directory
    storage_type="file",        # Storage type
    encryption_key=None        # Optional decryption key
)
```

### Methods
- `restore_point_in_time(timestamp)` - Restore to specific time
- `restore_incremental_chain(base_id)` - Restore from incremental chain
- `restore_emergency(backup_id)` - Emergency restore
- `verify_restore(metadata)` - Verify restore success
- `find_restore_points()` - Find available restore points

## BackupScheduler

The `BackupScheduler` class provides automated backup scheduling.

### Constructor
```python
BackupScheduler(
    backup_dir,                # Backup directory
    backup_manager,            # BackupManager instance
    auto_verify=True,          # Enable verification
    verify_interval=3600       # Check interval in seconds
)
```

### Methods
- `add_job(name, type, schedule, ...)` - Add backup job
- `start()` - Start scheduler
- `stop()` - Stop scheduler
- `configure_default_jobs()` - Add default backup jobs

## BackupVerification

The `BackupVerification` class handles backup verification and testing.

### Constructor
```python
BackupVerification(
    backup_dir,               # Backup directory
    test_restore_dir="./test_restores",
    timeout_seconds=300,     # Verification timeout
    max_test_size_mb=100      # Maximum test size
)
```

### Methods
- `check_backup_integrity(metadata)` - Check backup integrity
- `perform_test_restore(metadata)` - Test restore operation
- `run_all_checks(metadata)` - Run all verification checks
- `generate_verification_report(metadata)` - Generate report
"""

    api_file = doc_dir / "API.md"
    with open(api_file, 'w') as f:
        f.write(api_doc)

    print(f"API documentation created: {api_file}")

def main():
    """Main setup function."""
    print("Durus Backup and Restore System Setup")
    print("=" * 50)

    # Change to script directory
    os.chdir(Path(__file__).parent)

    try:
        # Step 1: Install dependencies
        install_dependencies()

        # Step 2: Create documentation
        create_documentation()

        # Step 3: Create sample configuration
        create_sample_configuration()

        # Step 4: Run tests
        tests_passed = run_tests()

        # Step 5: Run demo
        demo_success = run_demo()

        # Step 6: Test CLI
        cli_success = create_cli_test()

        # Summary
        print("\n" + "=" * 50)
        print("SETUP SUMMARY")
        print("=" * 50)
        print(f"Tests passed: {'✓' if tests_passed else '✗'}")
        print(f"Demo successful: {'✓' if demo_success else '✗'}")
        print(f"CLI test successful: {'✓' if cli_success else '✗'}")

        if all([tests_passed, demo_success, cli_success]):
            print("\n🎉 Setup completed successfully!")
            print("\nNext steps:")
            print("1. Review the documentation in docs/ directory")
            print("2. Check the example in examples/backup_example.py")
            print("3. Try running the CLI commands:")
            print("   python -m durus.backup.cli --help")
            print("4. Set up your own backup schedules")
            return 0
        else:
            print("\n❌ Setup completed with errors")
            return 1

    except Exception as e:
        print(f"\nSetup failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
