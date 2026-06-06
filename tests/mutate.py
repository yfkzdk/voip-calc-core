"""Manual mutation tester — verify test suite catches injected bugs.

Since mutmut doesn't support native Windows, this script applies targeted
mutations to domain source files and checks whether the test suite detects
each one.

Usage:  PYTHONPATH=src python tests/mutate.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# (file, original_line, mutated_line, description)
Mutation = NamedTuple(
    "Mutation",
    [("file", str), ("orig", str), ("mutated", str), ("desc", str)],
)

MUTATIONS: list[Mutation] = []


def m(file, orig, mutated, desc):
    MUTATIONS.append(Mutation(file, orig, mutated, desc))


# ── rate_calculator.py ──────────────────────────────────────────────

m("domain/rate_calculator.py",
  'result.at_least(Money(Decimal("0"), CNY))',
  'result.at_least(Money(Decimal("0.01"), CNY))',
  "floor raised from 0.00 to 0.01")

m("domain/rate_calculator.py",
  "if self._night_valley.is_applicable(context.call_time):",
  "if self._night_valley.is_applicable(context.call_time) and False:",
  "night valley branch always skipped")

m("domain/rate_calculator.py",
  "result = discounted - self._night_valley.reduction_amount()",
  "result = discounted + self._night_valley.reduction_amount()",
  "night reduction sign flipped (- -> +)")

m("domain/rate_calculator.py",
  'chargeable_minutes = Decimal(chargeable_seconds) / Decimal("60")',
  'chargeable_minutes = Decimal(chargeable_seconds) / Decimal("100")',
  "chargeable divisor 60 -> 100")

# ── night_valley.py ─────────────────────────────────────────────────

m("domain/night_valley.py",
  "return hour >= self.start_hour or hour < self.end_hour",
  "return hour >= self.start_hour and hour < self.end_hour",
  "cross-midnight: or -> and")

m("domain/night_valley.py",
  "return self.start_hour <= hour < self.end_hour",
  "return self.start_hour < hour < self.end_hour",
  "same-day: half-open -> open at start")

m("domain/night_valley.py",
  "if self.reduction < 0:",
  "if self.reduction <= 0:",
  "reduction validation: < 0 -> <= 0 (rejects zero)")

# ── country_code.py ─────────────────────────────────────────────────

m("domain/country_code.py",
  'if not self._PATTERN.match(self.code):',
  'if self._PATTERN.match(self.code):',
  "country code validation inverted (removed 'not')")

# ── money.py ────────────────────────────────────────────────────────

m("domain/money.py",
  'elif isinstance(scalar, float):\n            scalar = Decimal(str(scalar))',
  'elif isinstance(scalar, float):\n            scalar = Decimal(scalar)',
  "float conversion: Decimal(str(...)) -> Decimal(...) direct")

m("domain/money.py",
  'rounded = self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)',
  'rounded = self.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)',
  "rounding: HALF_UP -> HALF_EVEN")

# ── billing_increment.py ────────────────────────────────────────────

m("domain/billing_increment.py",
  "if actual_seconds <= 0:",
  "if actual_seconds < 0:",
  "zero-duration check: <= 0 -> < 0")

m("domain/billing_increment.py",
  "if actual_seconds <= self.initial_seconds:",
  "if actual_seconds < self.initial_seconds:",
  "initial ceiling: <= -> <")

m("domain/billing_increment.py",
  "pulses = (\n            remaining + self.subsequent_seconds - 1\n        ) // self.subsequent_seconds",
  'pulses = remaining // self.subsequent_seconds',
  "ceiling division -> floor division (removed +b-1)")

# ── duration.py ─────────────────────────────────────────────────────

m("domain/duration.py",
  "if self.seconds < 0:",
  "if self.seconds <= 0:",
  "duration validation: < 0 -> <= 0 (rejects zero)")

# ── call_context.py ─────────────────────────────────────────────────

m("domain/call_context.py",
  "if self.call_time.tzinfo is None:",
  "if self.call_time.tzinfo is not None:",
  "timezone check inverted (is None -> is not None)")


# ── runner ──────────────────────────────────────────────────────────

def run_tests() -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode == 0


def apply_mutation(file_rel: str, orig: str, mutated: str):
    """Write mutated source, return path so we can restore it."""
    filepath = SRC / "voip_calc_core" / file_rel
    original_content = filepath.read_text(encoding="utf-8")
    if orig not in original_content:
        return None, original_content
    mutated_content = original_content.replace(orig, mutated, 1)
    filepath.write_text(mutated_content, encoding="utf-8")
    return filepath, original_content


def main():
    total = len(MUTATIONS)
    killed = 0
    survived = 0
    errors = 0

    print(f"Running {total} mutation tests...\n")

    for i, mut in enumerate(MUTATIONS, 1):
        path, original = apply_mutation(mut.file, mut.orig, mut.mutated)
        if path is None:
            print(f"[{i:2d}/{total}] SKIP  {mut.desc}")
            print(f"           Pattern not found in {mut.file}")
            errors += 1
            continue

        tests_pass = run_tests()

        # Restore
        path.write_text(original, encoding="utf-8")

        if tests_pass:
            survived += 1
            print(f"[{i:2d}/{total}] ALIVE {mut.desc}")
            print(f"           {mut.file} — TESTS DID NOT CATCH THIS")
        else:
            killed += 1
            print(f"[{i:2d}/{total}] KILL  {mut.desc}")

    print(f"\n{'='*60}")
    print(f"Results: {killed} killed, {survived} survived, {errors} skipped")
    print(f"Score:   {killed}/{total} = {100*killed//total}%")

    if survived > 0:
        print(f"\nSurviving mutants indicate blind spots in the test suite.")
        sys.exit(1)
    else:
        print(f"\nAll mutants killed. Tests are resilient.")


if __name__ == "__main__":
    main()
