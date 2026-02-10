# Disaster Recovery Runbook

This runbook provides step-by-step procedures for responding to and recovering from disasters affecting Durus databases.

## Table of Contents

1. [Overview](#overview)
1. [Activation Criteria](#activation-criteria)
1. [Response Team](#response-team)
1. [Incident Classification](#incident-classification)
1. [Procedural Steps](#procedural-steps)
1. [Recovery Scenarios](#recovery-scenarios)
1. [Communication Plan](#communication-plan)
1. [Post-Incident](#post-incident)
1. [Checklists](#checklists)
1. [Contacts](#contacts)

## Overview

### Purpose

- Provide clear, actionable steps for disaster recovery
- Minimize downtime and data loss
- Ensure consistent response to incidents
- Maintain business continuity

### Scope

This runbook covers:

- Hardware failures
- Software corruption
- Natural disasters
- Security incidents
- Data corruption
- Service provider failures

### Success Metrics

- **RTO**: < 1 hour for critical systems
- **RPO**: < 5 minutes for transactional data
- **Recovery Success Rate**: > 99%
- **Communication**: < 15 minutes stakeholder notification

## Activation Criteria

### Immediate Activation

- Complete database failure
- Data corruption requiring restore
- Natural disaster affecting primary site
- Security breach requiring isolation
- Prolonged unavailability (> 4 hours)

### Conditional Activation

- Partial system failure
- Performance degradation
- Backup failures
- Storage warnings
- Network issues

### Deactivation Criteria

- Systems restored to service
- Business operations normal
- All stakeholders notified
- Documentation complete

## Response Team

### Emergency Response Team

**Incident Commander**

- Role: Overall coordination
- Contact: [Phone], [Email]
- Backup: [Name]

**Technical Lead**

- Role: Technical coordination
- Contact: [Phone], [Email]
- Backup: [Name]

**Database Administrator**

- Role: Database recovery
- Contact: [Phone], [Email]
- Backup: [Name]

**System Administrator**

- Role: Infrastructure recovery
- Contact: [Phone], [Email]
- Backup: [Name]

**Security Officer**

- Role: Security coordination
- Contact: [Phone], [Email]
- Backup: [Name]

**Communications Lead**

- Role: Stakeholder communication
- Contact: [Phone], [Email]
- Backup: [Name]

### Support Team

**Application Owners**

- Role: Application coordination
- Contact: [Phone], [Email]

**Business Continuity**

- Role: Business coordination
- Contact: [Phone], [Email]

**Vendor Support**

- Role: Vendor coordination
- Contact: [Phone], [Email]

## Incident Classification

### Critical (P0)

**Definition**: Complete system failure affecting all customers
**Symptoms**:

- Database unavailable for all customers
- Data corruption affecting core operations
- Primary site completely down

**Response**: Immediate activation, 24/7 response

### High (P1)

**Definition**: Partial system failure affecting significant customers
**Symptoms**:

- Database partially available
- Performance severely degraded
- Data corruption in specific modules

**Response**: 1 hour response, 24/7 support

### Medium (P2)

**Definition**: Non-critical system failure
**Symptoms**:

- Backup failures
- Storage warnings
- Performance issues

**Response**: 4 hour response, business hours support

### Low (P3)

**Definition**: Minor issues with no customer impact
**Symptoms**:

- Documentation issues
- Training needs
- Process improvements

**Response**: Normal business hours

## Procedural Steps

### Initial Response (0-15 minutes)

1. **Incident Detection**

   ```bash
   # Check system status
   check_backup_status.sh

   # Verify connectivity
   ping primary_database_server

   # Check storage systems
   df -h | grep backup
   ```

1. **Incident Commander Activation**

   - Contact Incident Commander
   - Initial assessment of impact
   - Determine activation level

1. **Team Notification**

   ```bash
   # Notify response team
   notify_team.sh "P0" "Primary database down"

   # Create incident ticket
   create_incident.sh "P0-001" "Primary database failure"
   ```

1. **Initial Assessment**

   - Determine root cause
   - Identify affected systems
   - Assess impact on business

### Assessment Phase (15-30 minutes)

1. **System Diagnostics**

   ```bash
   # Check database status
   systemctl status durus-server

   # Check disk usage
   du -sh /backup/*

   # Check network connectivity
   netstat -tuln | grep :2972
   ```

1. **Impact Assessment**

   - Affected customer segments
   - Estimated downtime
   - Data loss potential
   - Business impact analysis

1. **Strategy Determination**

   - Recovery method selection
   - Resource requirements
   - Timeline estimation
   - Communication needs

### Recovery Phase (30 minutes - 6 hours)

#### Backup Verification

```bash
# Check backup catalog
python -m durus.backup.catalog --list-backups --days 7

# Verify backup integrity
python -m durus.backup.verification --check-all --backup latest

# Test restore to staging
python -m durus.backup.restore --test --backup latest
```

#### Recovery Procedures

```bash
# Restore from backup
python -m durus.backup.restore \
  --target /data/recovered_db.durus \
  --backup-id full_backup_20240101_020000

# Start recovered database
systemctl start durus-server --recovered

# Verify recovery
python -m durus.backup.verify --connection "localhost:2972" --health-check
```

#### Performance Tuning

```bash
# Monitor recovery
monitor_recovery.sh

# Optimize configuration
optimize_db_recovery.sh

# Load test recovered system
load_test_recovery.sh
```

### Post-Recovery (1-2 hours)

1. **Verification Checklist**

   - Data integrity verified
   - Application connectivity confirmed
   - Performance meets requirements
   - Security controls active

1. **Stakeholder Notification**

   ```bash
   # Notify customers
   notify_customers.sh "service_restored" "recovery_complete"

   # Update management
   update_management.sh "recovery_metrics"
   ```

1. **Documentation**

   - Timeline recording
   - Root cause identification
   - Lessons learned
   - Process improvements

## Recovery Scenarios

### Database Corruption

**Symptoms**: Error messages, application failures, corrupted data

**Procedure**:

1. Isolate affected database
1. Verify backup catalog
1. Perform point-in-time restore
1. Validate data integrity
1. Restore application connectivity

**Commands**:

```bash
# Isolate database
pkill -f durus-server
mv /data/corrupted_db.durus /data/corrupted_db.durus.bak

# Find backup
python -m durus.backup.catalog --list-corrupted --since "1 hour ago"

# Restore
python -m durus.backup.restore \
  --target /data/recovered_db.durus \
  --time "2024-01-01 12:00:00"

# Verify
python -m durus.backup.verify --integrity --performance
```

### Hardware Failure

**Symptoms**: Server unresponsive, storage errors, network issues

**Procedure**:

1. Identify failed hardware
1. Activate secondary hardware
1. Restore from last backup
1. Replicate to new hardware
1. Test failover

**Commands**:

```bash
# Check hardware status
hardware_health_check.sh

# Activate standby
activate_standby_server.sh

# Restore to standby
python -m durus.backup.restore \
  --target /standby/data/db.durus \
  --backup latest

# Test failover
test_failover.sh
```

### Natural Disaster

**Symptoms**: Site down, network unavailable, power failure

**Procedure**:

1. Activate disaster recovery site
1. Restore from cloud backup
1. Establish network connectivity
1. Replicate data
1. Failover to DR site

**Commands**:

```bash
# Activate DR site
activate_dr_site.sh

# Restore from cloud
python -m durus.backup.restore \
  --target /dr/data/db.durus \
  --cloud --backup latest

# Replicate data
setup_data_replication.sh

# Failover
failover_to_dr.sh
```

### Ransomware Attack

**Symptoms**: Encrypted files, ransom notes, abnormal activity

**Procedure**:

1. Isolate affected systems
1. Scan for malware
1. Restore from clean backup
1. Change all passwords
1. Monitor for additional issues

**Commands**:

```bash
# Isolate systems
isolate_infected_systems.sh

# Scan for malware
malware_scan.sh /all

# Restore from clean backup
python -m durus.backup.restore \
  --target /clean_data/db.durus \
  --backup "clean_backup_20240101"

# Change credentials
change_all_credentials.sh

# Monitor
security_monitoring.sh
```

## Communication Plan

### Stakeholder Communication

**Customers**

- Initial notification within 15 minutes
- Updates every 30 minutes
- Restoration confirmation
- Post-incident summary

**Internal Teams**

- Real-time updates via Slack
- Incident command center
- Regular briefings
- Debrief sessions

**Management**

- Executive summary within 30 minutes
- Regular status updates
- Recovery projections
- Final report

### Communication Templates

**Initial Alert**

```
Subject: Critical Database Incident - [System Name]

Team,

We are experiencing a critical database incident affecting [system name].
Current impact: [description]

We have activated the disaster recovery plan and working to restore service.

Estimated time to resolution: TBD

Further updates to follow.

Incident Commander: [Name]
```

**Status Update**

```
Subject: Status Update - Database Recovery

Team,

Current status: [description]
Actions taken: [list]
Next steps: [steps]
Updated ETA: [time]

Monitoring: [metrics]
```

**Resolution Notice**

```
Subject: Service Restored - [System Name]

Team,

The database incident has been resolved and service has been restored.
Duration: [time period]
Impact: [summary]
Actions taken: [brief summary]

We will continue monitoring and provide a detailed incident report.

Thank you for your patience.
```

## Post-Incident

### Documentation

1. **Incident Report**

   ```markdown
   # Incident Report: [ID]

   ## Timeline
   - [time]: [event]

   ## Impact
   - Affected systems: [list]
   - Duration: [time]
   - Customers affected: [count]

   ## Root Cause
   [analysis]

   ## Resolution
   [steps taken]

   ## Lessons Learned
   [insights]

   ## Action Items
   - [ ] Item 1
   - [ ] Item 2
   ```

1. **Process Improvements**

   - Update runbook procedures
   - Modify backup policies
   - Enhance monitoring
   - Improve training

1. **Performance Review**

   ```python
   # Analyze recovery performance
   analyze_recovery_performance.py --incident "P0-001"

   # Check RTO/RPO compliance
   check_compliance.py --after-incident
   ```

### Training Updates

1. **Team Training**

   - Incident response refresher
   - New procedures review
   - Technology updates
   - Role-specific training

1. **Documentation Updates**

   - Runbook revisions
   - Playbook additions
   - FAQ updates
   - Training materials

1. **Simulation Exercises**

   - Tabletop exercises
   - Live simulations
   - Cross-team coordination
   - Time-pressure scenarios

## Checklists

### Immediate Response Checklist

- [ ] Notify Incident Commander
- [ ] Activate response team
- [ ] Create incident ticket
- [ ] Assess initial impact
- [ ] Determine activation level
- [ ] Notify key stakeholders

### Assessment Checklist

- [ ] Check system status
- [ ] Verify connectivity
- [ ] Assess storage systems
- [ ] Check backup status
- [ ] Determine root cause
- [ ] Estimate timeline

### Recovery Checklist

- [ ] Verify backup availability
- [ ] Check backup integrity
- [ ] Perform test restore
- [ ] Execute recovery procedure
- [ ] Verify data integrity
- [ ] Confirm application connectivity
- [ ] Monitor performance

### Post-Recovery Checklist

- [ ] Notify stakeholders
- [ ] Document incident
- [ ] Conduct debrief
- [ ] Update documentation
- [ ] Schedule review
- [ ] Implement improvements

### Testing Checklist

- [ ] Backup verification
- [ ] Restore testing
- [ ] Performance validation
- [ ] Security verification
- [ ] Documentation review
- [ ] Team coordination

## Contacts

### Emergency Contacts

**Incident Commander**

- [Name]
- [Phone]
- [Email]
- [Backup Name/Contact]

**Technical Lead**

- [Name]
- [Phone]
- [Email]
- [Backup Name/Contact]

### Support Contacts

**Database Administrator**

- [Name]
- [Phone]
- [Email]
- [Backup Name/Contact]

**System Administrator**

- [Name]
- [Phone]
- [Email]
- [Backup Name/Contact]

**Security Officer**

- [Name]
- [Phone]
- [Email]
- [Backup Name/Contact]

### Vendor Contacts

**Cloud Provider**

- [Support Phone]
- [Support Email]
- [Account Manager]
- [Emergency Contact]

**Hardware Vendor**

- [Support Phone]
- [Support Email]
- [Account Manager]
- [Emergency Contact]

### Emergency Numbers

- **Primary Site**: [Phone]
- **Backup Site**: [Phone]
- **DR Site**: [Phone]
- **IT Support**: [Phone]
- **Security Team**: [Phone]
- **Management On-Call**: [Phone]

### Resources

- **Incident Tracking System**: [URL]
- **Monitoring Dashboard**: [URL]
- **Documentation Repository**: [URL]
- **Communication Channels**: [Slack channel, Email list]
- **Command Center**: [Location, Access info]

______________________________________________________________________

**Revision History:**

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | [Date] | Initial version | [Name] |
| 1.1 | [Date] | [Changes] | [Name] |

**Approval:**

Incident Commander: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_
Technical Lead: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_
Database Administrator: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_
Security Officer: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_
Management: \_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_\_
