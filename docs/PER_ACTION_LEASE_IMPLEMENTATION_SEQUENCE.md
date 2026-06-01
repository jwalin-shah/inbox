# Per-Action Lease Implementation Sequence

Date: 2026-05-30
Work item: WI-056D

## Goal

Remove the remaining Inbox per-action lease blockers without weakening the
approval boundary. The finished behavior must deny the historical static test
lease, require stable account/resource bindings for provider mutations, and keep
replay, body-change, wrong-route, and missing-resource denials before provider
helper execution.

## Current Gate State

`tests/test_approval_route_gate.py` already pins the important local safety
classes:

- static lease fallback is contained to test-mode helper behavior; outside
  `INBOX_TEST_MODE`, `_local_approval_lease()` must return the configured
  adapter lease and not `test-local-approval-lease`;
- minted Sheets update leases must bind a stable account, path-derived resource,
  and bounded item count, and must not use a `payload:` fallback when a stable
  resource exists;
- missing lease fails closed across the critical mutating route matrix;
- valid one-use lease can execute a mocked task helper once, then replay returns
  `403` with `lease_replayed`;
- changed Gmail compose body returns `403` with `payload_hash_mismatch`;
- changed Sheets value count returns `403` with `item_count_mismatch`;
- expired lease returns `403` with `lease_expired`;
- cross-provider reuse returns `403` before the destination helper;
- same-provider sibling route reuse returns `403` before the destination helper;
- production use of `test-local-approval-lease` returns `403`;
- two strict product-blocker xfail gates remain for static lease removal in
  test mode and missing stable resource binding on ambiguous provider writes.

## Implementation Sequence

1. Migrate broad server fixtures away from the static lease.
   - Update the `tests/test_server.py` client fixture so mutating requests use a
     route-specific helper that calls `mint_local_approval_lease(method, path,
     body=...)`.
   - Keep reads and explicit exception routes lease-free.
   - Acceptance test: add a fixture-level assertion that no request sends
     `X-Inbox-Approval-Lease: test-local-approval-lease`.
   - PASS: `tests/test_server.py` mutating coverage passes under
     `INBOX_TEST_MODE=1` without the static lease header.

2. Remove static lease authority.
   - Delete the `approved_by_legacy_test_lease` branch from
     `_approval_decision_for_request`.
   - Keep `APPROVAL_TEST_LEASE` only as a denied legacy sentinel until all
     callers are gone, then remove it.
   - Acceptance test: un-xfail
     `test_static_approval_test_lease_denied_even_in_test_mode_after_migration`.
   - PASS: static lease returns `403` with `unknown_per_action_approval_lease`
     or `legacy_static_lease_denied`, and the provider helper is not called.

3. Replace payload-derived resource fallback with stable binding adapters.
   - Add explicit resource extraction per provider family instead of using
     `payload:<hash>` for ambiguous provider mutations.
   - Treat missing account, resource, or bounded item count as a deny decision
     before lease lookup or helper execution.
   - Acceptance test: un-xfail
     `test_missing_stable_resource_binding_blocks_provider_mutation`.
   - PASS: ambiguous Drive folder creation without a stable resource binding
     returns `403` with `missing_resource_ref` or `missing_item_count`.

4. Preserve replay spend ordering.
   - Keep lease verification and spend inside `_approval_lease_lock`.
   - Mark one-use leases spent before route handlers execute provider helpers.
   - Add a concurrent or sequential replay regression if the route code moves
     spend later.
   - PASS: the first valid mocked call succeeds once; replay returns `403`
     with `lease_replayed`; helper call count remains one.

5. Preserve body-change and item-count binding.
   - Keep canonical JSON hashing for the full request body.
   - Keep item-count derivation for list-bearing batch payloads.
   - PASS: changed Gmail body returns `payload_hash_mismatch`; changed Sheets
     batch size returns `item_count_mismatch`; mocked helpers are not called.

6. Preserve route, method, provider, operation, class, executor, and account
   matching.
   - Keep method/path checks before provider/operation checks so sibling route
     drift is reported clearly.
   - Add account/resource swap cases as adapters become explicit.
   - PASS: cross-provider reuse and same-provider wrong-route reuse return
     `403` before helper execution.

7. Keep exception routes narrow.
   - Keep connector sync safe only for default `execute=false` dry-run/read sync.
   - Split or guard any future live provider execution route.
   - PASS: exception-policy tests reject provider-write semantics including
     send, delete, archive, RSVP, provider create/update/delete, and
     `execute=true`.

## Acceptance Test Set

Required local acceptance before closing the sequence:

```bash
cd /Users/jwalinshah/projects/inbox
INBOX_TEST_MODE=1 uv run python -m pytest tests/test_approval_route_gate.py tests/test_server.py -q
git diff --check
```

Focused gates that must be green, not xfail, at completion:

- static lease denied even in test mode;
- stable resource binding required for every provider mutation;
- replay denial happens before provider helper;
- body-change and item-count denial happen before provider helper;
- wrong route and wrong method denial happen before provider helper;
- missing resource/account/item-count denial happens before provider helper.

## Kill Criteria

Do not call providers, OAuth flows, external send/write/delete APIs, calendar
mutations, publishing flows, application submissions, or credit-spending
services while implementing this sequence. If a step requires live credentials,
stop and record the blocker instead.
