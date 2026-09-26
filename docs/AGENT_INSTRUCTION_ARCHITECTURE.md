# Agent Instruction Architecture (Operator Steering)

## 1. Vision & Purpose

In an institutional trading environment, an autonomous agent must accept high-level contextual guidance, risk boundaries, or observational focus from a human discretionary trader (e.g., *"Focus on 23,000 support level bounce"*, *"Avoid trading during RBI rate statement"*).

However, an AI agent must **NEVER** allow an instruction to breach hard safety or risk boundaries, whether intentional, accidental, or via prompt injection.

The **Manual Agent Instruction Box** is a first-class subsystem designed to:
1. Validate all operator inputs against non-negotiable safety guardrails.
2. Persist instructions in SQLite (`data/agent/instructions.db`).
3. Manage priority queues and expiration timestamps.
4. Seamlessly inject active instructions into ModelRouter perception prompts.

---

## 2. Non-Negotiable Safety Invariant Enforcement

Before any instruction enters the system, `InstructionManager.validate_safety()` executes deterministic regex analysis. If any prohibited directive is detected, the instruction is immediately flagged as `REJECTED` and will never reach the reasoning layer.

### Prohibited Directives (Instantly Rejected)
| Pattern | Rationale |
| :--- | :--- |
| `ignore (all) (risk\|safety\|loss) limits` | Invariant: Risk limits cannot be overridden |
| `bypass (risk\|safety\|policy\|guardrails)` | Invariant: Safety guardrails are absolute |
| `trade (with) (maximum\|unlimited\|huge) (size\|leverage\|risk)` | Invariant: Position sizing constraints are immutable |
| `execute live (order\|trade\|now)` | Invariant: Live broker execution is disabled |
| `override (stop loss\|daily loss)` | Invariant: Capital preservation limits are non-negotiable |
| `reveal (api key\|secret\|password)` | Invariant: Secrets protection |
| `delete (database\|journal\|history)` | Invariant: Immutable audit trail preservation |

---

## 3. Instruction Lifecycle & Expiration

```text
[Operator Submits Instruction]
              │
      Deterministic Safety Validation
              │
    ┌─────────┴─────────┐
    ▼                   ▼
 [PASS]              [FAIL]
    │                   │
    ▼                   ▼
 Status: PENDING     Status: REJECTED
 Priority: Set       Reason: Documented
 Store: SQLite       Store: SQLite (Audit)
    │
    ▼
 Time Elapsed > Expiry ?
    │
 ┌──┴──┐
 ▼     ▼
[NO]  [YES]
 │     │
 │     ▼
 │   Status: EXPIRED
 │
 ▼
[Active in Market Perception Prompt]
```

---

## 4. Prompt Context Formatting

Active instructions are injected into the LLM system prompt as structured guidelines:

```text
Active Operator Instructions (Guiding Observation/Context Only):
  1. [HIGH] "Focus on 23000 support level bounce" [Expires: 18:37 UTC] (ID: inst_2f4ff8e7)
```
The model acknowledges the instructions in its perception schema (`operator_directives_acknowledged`), ensuring human-machine symbiosis with cryptographic-like safety.
