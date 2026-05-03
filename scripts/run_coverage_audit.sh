#!/usr/bin/env bash
# Run test coverage audit for Dhara

set -e

echo "========================================"
echo "Dhara Test Coverage Audit"
echo "========================================"
echo ""

cd /Users/les/Projects/dhara

echo "Step 1: Cleaning up old coverage data..."
rm -rf htmlcov/ .coverage coverage.json
echo "✓ Cleanup complete"
echo ""

echo "Step 2: Running pytest with coverage..."
python -m pytest \
    --cov=dhara \
    --cov-report=term-missing:skip-covered \
    --cov-report=html:htmlcov \
    --cov-report=json \
    --strict-markers \
    --tb=short \
    -v \
    test/

echo ""
echo "✓ Coverage report generated"
echo ""

echo "Step 3: Parsing coverage JSON..."
if [ -f "coverage.json" ]; then
    python3 - <<'EOF'
import json
import sys

with open('coverage.json', 'r') as f:
    data = json.load(f)

totals = data['totals']
overall_percent = totals['percent_covered']

print(f"\n{'='*60}")
print(f"COVERAGE SUMMARY")
print(f"{'='*60}")
print(f"Overall Coverage: {overall_percent:.1f}%")
print(f"Lines Covered: {totals['covered_lines']}/{totals['num_statements']}")
print(f"Lines Missing: {totals['missing_lines']}")
print(f"Branches Covered: {totals.get('covered_branches', 0)}/{totals.get('num_branches', 0)}")
print(f"")

# Show coverage by module
print(f"{'='*60}")
print(f"MODULE COVERAGE")
print(f"{'='*60}")

modules = []
for filename, file_data in data['files'].items():
    if filename.startswith('dhara/'):
        summary = file_data['summary']
        percent = summary['percent_covered']
        covered = summary['covered_lines']
        total = summary['num_statements']
        modules.append((filename, percent, covered, total))

# Sort by coverage percentage
modules.sort(key=lambda x: x[1])

# Show modules with lowest coverage first
for filename, percent, covered, total in modules[:20]:
    status = "✓" if percent >= 70 else "⚠" if percent >= 40 else "✗"
    print(f"{status} {percent:5.1f}% {filename:50s} ({covered}/{total})")

print(f"")
print(f"{'='*60}")
print(f"Low coverage modules (<40%):")
low_coverage = [m for m in modules if m[1] < 40]
if low_coverage:
    for filename, percent, covered, total in low_coverage:
        print(f"  ✗ {percent:5.1f}% {filename}")
else:
    print(f"  None!")

print(f"{'='*60}")
EOF
else
    echo "⚠ coverage.json not found"
fi

echo ""
echo "Step 4: Opening HTML coverage report..."
if [ -d "htmlcov" ]; then
    open htmlcov/index.html
    echo "✓ HTML report opened in browser"
else
    echo "⚠ htmlcov/ directory not found"
fi

echo ""
echo "========================================"
echo "Coverage Audit Complete"
echo "========================================"
echo ""
echo "Next steps:"
echo "1. Review HTML report in browser"
echo "2. Identify low-coverage modules"
echo "3. Prioritize test implementation"
echo ""
