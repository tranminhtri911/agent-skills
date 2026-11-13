# Status changes in one place (BE-011)

When a status has rules (which changes are allowed, what must happen on each change, who may do it), every writer — API, admin, worker, import, command — goes through one transition function. Status assignments scattered across controllers drift: one path forgets the guard, the timestamp or the notification.

Learn from the source first: if the project uses a state library (`django-fsm`, `spatie/laravel-model-states`, XState) or already has a transition service, use it. Otherwise a transition map next to the enum and one function are enough; do not add a library for a handful of states.

## Django

```python
class BookingStatus(models.TextChoices):
    INQUIRY = "inquiry", _("Inquiry")
    CONFIRMED = "confirmed", _("Confirmed")
    CANCELLED = "cancelled", _("Cancelled")

# Allowed moves; the only place this rule is written.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    BookingStatus.INQUIRY: {BookingStatus.CONFIRMED, BookingStatus.CANCELLED},
    BookingStatus.CONFIRMED: {BookingStatus.CANCELLED},
    BookingStatus.CANCELLED: set(),
}


def change_booking_status(booking_id: int, target: BookingStatus) -> Booking:
    """Move a booking to `target`.

    Raises InvalidStatusTransition (a subclass of the project's error base) when the move is not allowed,
    including when a concurrent request changed the status first. Notification is sent after commit.
    """
    with transaction.atomic():
        booking = Booking.objects.select_for_update().get(pk=booking_id)
        if target not in ALLOWED_TRANSITIONS[booking.status]:
            raise InvalidStatusTransition(booking.status, target)
        booking.status = target
        if target == BookingStatus.CANCELLED:
            booking.cancelled_at = timezone.now()
        booking.save(update_fields=["status", "cancelled_at"])
        transaction.on_commit(lambda: notify_booking_status_changed.delay(booking_id, target))
    return booking
```

## Laravel

```php
enum BookingStatus: string
{
    case INQUIRY = 'inquiry';
    case CONFIRMED = 'confirmed';
    case CANCELLED = 'cancelled';

    /** Statuses this one may move to: the single source for every writer. */
    public function allowedNext(): array
    {
        return match ($this) {
            self::INQUIRY => [self::CONFIRMED, self::CANCELLED],
            self::CONFIRMED => [self::CANCELLED],
            self::CANCELLED => [],
        };
    }
}

// app/Actions/Booking/ChangeBookingStatus.php (or wherever the project keeps actions/services)
public function handle(int $bookingId, BookingStatus $target): Booking
{
    return DB::transaction(function () use ($bookingId, $target) {
        $booking = Booking::lockForUpdate()->findOrFail($bookingId);
        if (! in_array($target, $booking->status->allowedNext(), true)) {
            throw new InvalidStatusTransition($booking->status, $target);
        }
        $booking->status = $target;
        if ($target === BookingStatus::CANCELLED) {
            $booking->cancelled_at = now();
        }
        $booking->save();
        NotifyBookingStatusChanged::dispatch($booking->id, $target)->afterCommit();
        return $booking;
    });
}
```

High-traffic rows: instead of the row lock, a conditional update `UPDATE … SET status = :to WHERE id = :id AND status = :from` and treat 0 affected rows as a conflict.

## Frontend

Do not re-implement the rule: render actions from what the API returns (`allowed_actions: ["confirm", "cancel"]`) or, if the project mirrors it, from one shared transition map. The server stays the authority.

## Tests

- Transition matrix: parametrize over every (from, to) pair; allowed pairs succeed and set their side fields, all others raise and leave the row unchanged.
- Concurrency: two requests cancel/confirm the same booking at once → exactly one succeeds (integration DB, change-database `verification-db.md`).
- Every writer: admin action, import and worker call the same function (BE-009); in review, `rg -n "status\s*=" app/ --glob '!**/Actions/Booking/**'` finds bypasses.
- Acceptance criterion: `{"id": "AC-STATUS", "text": "booking status changes only along allowed transitions", "tags": ["regression", "concurrency"], "evidence": [{"test": "bookings/tests/test_status_transitions.py::test_transition_matrix", "check": "tests.unit"}]}`.
