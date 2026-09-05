"""Localised text.

The frontend has no dictionary beyond its own chrome, so every string it
prints is built here. A `Text` holds both languages and is resolved at
the edge of a request, which keeps the generators language-free: the
numbers must not move when the user switches locale.
"""

import dataclasses
import enum


class Locale(enum.StrEnum):
	"""A language the dashboard is served in."""

	EN = 'en'
	AR = 'ar'


def parse_locale(value: str | None) -> Locale:
	"""Reads the `lang` query parameter, defaulting to English."""
	return Locale.AR if value == Locale.AR.value else Locale.EN


@dataclasses.dataclass(frozen=True)
class Text:
	"""One string in every language the dashboard serves."""

	en: str
	ar: str

	def get(self, locale: Locale) -> str:
		"""Returns the string for one locale."""
		return self.ar if locale is Locale.AR else self.en


# Strings shared across payloads. Element titles live in the catalogue.
TOTAL = Text('Total', 'الإجمالي')
INDOOR = Text('Indoor', 'الداخلي')
OUTDOOR = Text('Outdoor', 'الخارجي')
COUNT = Text('Count', 'العدد')
HOUR = Text('Hour', 'الساعة')
DAY = Text('Day', 'اليوم')
DATE = Text('Date', 'التاريخ')
MINUTES = Text('Minutes', 'الدقائق')
VISITS = Text('Visits', 'الزيارات')
PEOPLE = Text('people', 'شخص')
SECONDS_UNIT = Text('seconds', 'ثانية')
EVENTS = Text('events', 'حالة')
CAMERA = Text('Camera', 'كاميرا')
COVERAGE_ZONE = Text('Coverage zone', 'منطقة التغطية')
ONLINE = Text('Online', 'متصلة')
OFFLINE = Text('No signal', 'لا إشارة')
SHIFT = Text('Shift', 'الوردية')
NO_ACTIVE_ALERT = Text('No active alert', 'لا يوجد تنبيه نشط')
THRESHOLD_APPROACHING = Text('Threshold approaching', 'اقتراب من الحد')
ACTIVE_NOW = Text('Active now', 'نشط الآن')
SINCE = Text('since', 'منذ')
LAST_FLAGGED = Text('Last flagged 2h ago', 'آخر رصد قبل ساعتين')
DAY_AGO_PREFIX = Text('D-', 'ي-')
MALE = Text('Male', 'ذكر')
FEMALE = Text('Female', 'أنثى')
UNKNOWN = Text('Unknown', 'غير محدد')
ABOVE = Text('Above', 'أعلى من')
BELOW = Text('Below', 'أدنى من')
CREATED_TODAY = Text('Created today', 'أُنشئت اليوم')
CREATED_ON = Text('Created', 'أُنشئت في')

WEEKDAYS = (
	Text('Mon', 'الإثنين'),
	Text('Tue', 'الثلاثاء'),
	Text('Wed', 'الأربعاء'),
	Text('Thu', 'الخميس'),
	Text('Fri', 'الجمعة'),
	Text('Sat', 'السبت'),
	Text('Sun', 'الأحد'),
)
