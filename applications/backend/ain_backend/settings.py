"""Every environment variable this service reads, in one place.

Same rule as the analytics side: a tunable that lives as a bare number in
the middle of a module is one nobody knows exists until it is wrong in
production, and `os.environ.get` spread across four files is a
configuration surface you can only find by grepping. The name carries the
unit, and the default is what was hard-coded before.
"""

import functools

import pydantic
import pydantic_settings


class Settings(pydantic_settings.BaseSettings):
	"""The whole configurable surface of the dashboard API."""

	model_config = pydantic_settings.SettingsConfigDict(
		extra='ignore', frozen=True, populate_by_name=True
	)

	# Empty means "no analytics service": every card falls back to
	# generated data rather than erroring, which is what makes the
	# dashboard runnable without the pipeline.
	analytics_url: str = pydantic.Field('', alias='AIN_ANALYTICS_URL')
	analytics_timeout_seconds: float = pydantic.Field(
		4, alias='AIN_ANALYTICS_TIMEOUT'
	)
	# A clip is decoded, redrawn and re-encoded on demand. Ten minutes,
	# because the window can now be twenty of video: a long-wait alert is
	# measured in minutes and its clip has to be able to contain it.
	clip_timeout_seconds: float = pydantic.Field(600, alias='AIN_CLIP_TIMEOUT')

	# In-memory by default, shared across connections by name, so the
	# dashboard runs with no volume and loses its rules on restart.
	store_path: str = pydantic.Field(
		'file:ain-alerts?mode=memory&cache=shared', alias='AIN_STORE_PATH'
	)

	cors_origins: str = pydantic.Field('*', alias='AIN_CORS_ORIGINS')

	@property
	def analytics_base_url(self) -> str:
		"""The analytics URL without a trailing slash."""
		return self.analytics_url.rstrip('/')

	@property
	def cors_origin_list(self) -> list[str]:
		"""The CORS origins as the middleware wants them."""
		return [origin.strip() for origin in self.cors_origins.split(',')]


@functools.cache
def get() -> Settings:
	"""The process-wide settings, read once from the environment."""
	return Settings()
