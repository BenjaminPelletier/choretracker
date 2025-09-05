from choretracker.time_utils import get_now

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from choretracker.calendar import (
    CalendarEntry,
    CalendarEntryType,
    InstanceSpecifics,
    Recurrence,
    RecurrenceType,
    responsible_for,
)


def test_responsible_hierarchy():
    rec = Recurrence(
        id=0,
        type=RecurrenceType.Weekly,
        responsible=["alice"],
    )
    rec.instance_specifics[1] = InstanceSpecifics(
        entry_id=0, recurrence_id=0, instance_index=1, responsible=["bob"]
    )
    entry = CalendarEntry(
        title="Test",
        description="",
        type=CalendarEntryType.Chore,
        first_start=get_now(),
        duration_seconds=60,
        recurrences=[rec],
        responsible=["carol"],
    )

    assert responsible_for(entry, 0, 0) == ["alice"]
    assert responsible_for(entry, 0, 1) == ["bob"]
    entry.recurrences[0].responsible = []
    entry.recurrences[0].instance_specifics.pop(1)
    assert responsible_for(entry, 0, 2) == ["carol"]
    entry.recurrences[0].instance_specifics[3] = InstanceSpecifics(
        entry_id=0, recurrence_id=0, instance_index=3, responsible=[]
    )
    assert responsible_for(entry, 0, 3) == []
