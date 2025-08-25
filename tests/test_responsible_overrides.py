from datetime import datetime

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import (
    CalendarEntry,
    CalendarEntryType,
    Delegation,
    Recurrence,
    RecurrenceType,
    responsible_for,
)


def test_responsible_hierarchy():
    entry = CalendarEntry(
        title="Test",
        description="",
        type=CalendarEntryType.Chore,
        first_start=datetime.now(),
        duration_seconds=60,
        recurrences=[
            Recurrence(
                type=RecurrenceType.Weekly,
                responsible=["alice"],
                delegations=[Delegation(instance_index=1, responsible=["bob"])]
            )
        ],
        responsible=["carol"],
    )

    assert responsible_for(entry, 0, 0) == ["alice"]
    assert responsible_for(entry, 0, 1) == ["bob"]
    entry.recurrences[0].responsible = []
    entry.recurrences[0].delegations = []
    assert responsible_for(entry, 0, 2) == ["carol"]
    entry.recurrences[0].delegations = [Delegation(instance_index=3, responsible=[])]
    assert responsible_for(entry, 0, 3) == []
