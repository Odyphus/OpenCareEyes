'''Offline holiday lookup for companion appearance rules.'''

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class HolidayEvent:
    '''A semantic holiday event that pet packs may render differently.'''

    event_id: str
    display_name: str
    appearance_key: str


_CHRISTMAS = HolidayEvent('christmas', '圣诞节', 'holiday.christmas')
_LANTERN_FESTIVAL = HolidayEvent('lantern_festival', '元宵节', 'holiday.lantern')

# Offline dates keep holiday behavior deterministic and avoid a lunar-calendar
# runtime dependency. Extend this table as part of a normal release update.
_LANTERN_FESTIVAL_DATES = frozenset(
    {
        date(2024, 2, 24),
        date(2025, 2, 12),
        date(2026, 3, 3),
        date(2027, 2, 20),
        date(2028, 2, 9),
        date(2029, 2, 27),
        date(2030, 2, 17),
        date(2031, 2, 6),
        date(2032, 2, 25),
        date(2033, 2, 14),
        date(2034, 3, 5),
        date(2035, 2, 22),
        date(2036, 2, 11),
        date(2037, 3, 1),
        date(2038, 2, 18),
        date(2039, 2, 7),
        date(2040, 2, 26),
    }
)


class HolidayService:
    '''Resolve bundled holiday events without network or persistent history.'''

    SUPPORTED_PACKS = frozenset({'none', 'zh-CN'})

    def events_for(self, day: date, *, pack: str = 'zh-CN') -> tuple[HolidayEvent, ...]:
        if not isinstance(day, date):
            raise TypeError('day must be a date')
        if pack not in self.SUPPORTED_PACKS:
            raise ValueError('unsupported holiday pack')
        if pack == 'none':
            return ()

        events: list[HolidayEvent] = []
        if day.month == 12 and 24 <= day.day <= 26:
            events.append(_CHRISTMAS)
        if day in _LANTERN_FESTIVAL_DATES:
            events.append(_LANTERN_FESTIVAL)
        return tuple(events)

    def current_events(
        self,
        *,
        pack: str = 'zh-CN',
        today: date | None = None,
    ) -> tuple[HolidayEvent, ...]:
        return self.events_for(today or date.today(), pack=pack)
