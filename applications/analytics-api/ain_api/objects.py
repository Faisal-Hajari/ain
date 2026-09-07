"""The clip bucket: where rendered clips live, and how a browser reaches one.

Clips used to be files in a container-local directory, which made this
service stateful for something that is not state. Three things fall out of
moving them to object storage, and they are the reason for the change rather
than a side effect of it:

* **Retention stops being code.** The bucket expires objects on a lifecycle
  rule, so there is no cache limit to tune, no directory to walk and no
  prune-under-a-semaphore race to reason about.
* **The bytes stop going through two services.** The browser fetches the mp4
  from the store directly on a presigned link, instead of streaming through
  the analytics API and then through the backend.
* **A restart stops losing them.** A rendered clip outlives the container
  that rendered it.

The link is presigned rather than the bucket being public: a clip is footage
of identifiable people in a shop, and "unlisted URL" is not an access
control.
"""

import datetime
import functools
import logging

import boto3
import botocore.client
import botocore.exceptions

from ain_analytics import settings

_LOG = logging.getLogger(__name__)


class StoreError(Exception):
	"""The object store would not answer."""


def _build(endpoint: str):
	"""A client for one endpoint.

	Args:
		endpoint: The base URL to talk to, or to sign for.

	Returns:
		A configured S3 client.
	"""
	options = settings.get()
	return boto3.client(
		's3',
		endpoint_url=endpoint,
		aws_access_key_id=options.s3_access_key,
		aws_secret_access_key=options.s3_secret_key,
		region_name=options.s3_region,
		# Path style, because `bucket.minio:9000` is not a name that
		# resolves anywhere - virtual-host addressing needs DNS the
		# compose network does not have.
		config=botocore.client.Config(s3={'addressing_style': 'path'}),
	)


@functools.cache
def client():
	"""The client this service reads and writes through."""
	return _build(settings.get().s3_endpoint)


@functools.cache
def _signer():
	"""A client that signs for the endpoint a BROWSER can reach.

	A presigned URL is signed for one host. Signing with the internal
	name produces a link only the compose network can open, which is a
	link the person clicking it cannot.
	"""
	return _build(settings.get().s3_public_endpoint)


@functools.cache
def ensure_bucket() -> str:
	"""Creates the clip bucket and its expiry rule if they are missing.

	Returns:
		The bucket name.

	Raises:
		StoreError: The store is unreachable.

	The lifecycle rule is what makes retention somebody else's problem.
	Applied every start rather than once by hand, so a fresh volume comes
	up with the same policy as a long-running one.
	"""
	options = settings.get()
	bucket = options.s3_bucket
	store = client()
	try:
		try:
			store.head_bucket(Bucket=bucket)
		except botocore.exceptions.ClientError:
			store.create_bucket(Bucket=bucket)
			_LOG.info('created bucket %s', bucket)
		store.put_bucket_lifecycle_configuration(
			Bucket=bucket,
			LifecycleConfiguration={
				'Rules': [
					{
						'ID': 'expire-clips',
						'Status': 'Enabled',
						'Filter': {'Prefix': ''},
						'Expiration': {'Days': options.clip_retention_days},
					}
				]
			},
		)
	except botocore.exceptions.BotoCoreError as error:
		raise StoreError(f'object store unreachable: {error}') from error
	except botocore.exceptions.ClientError as error:
		raise StoreError(f'object store refused: {error}') from error
	return bucket


def exists(key: str) -> bool:
	"""Whether an object is already in the bucket.

	Args:
		key: The object name.

	Returns:
		True when it is there with a non-empty body.
	"""
	try:
		head = client().head_object(Bucket=ensure_bucket(), Key=key)
	except botocore.exceptions.ClientError:
		return False
	except botocore.exceptions.BotoCoreError as error:
		raise StoreError(f'object store unreachable: {error}') from error
	return head.get('ContentLength', 0) > 0


def put(key: str, path, content_type: str = 'video/mp4') -> None:
	"""Uploads a rendered file.

	Args:
		key: The object name.
		path: The local file to send.
		content_type: What the browser should be told it is.

	Raises:
		StoreError: The upload failed.
	"""
	try:
		client().upload_file(
			str(path),
			ensure_bucket(),
			key,
			ExtraArgs={'ContentType': content_type},
		)
	except (
		botocore.exceptions.BotoCoreError,
		botocore.exceptions.ClientError,
	) as error:
		raise StoreError(f'could not store {key}: {error}') from error


def link(key: str) -> tuple[str, datetime.datetime]:
	"""A URL the browser can fetch the object from, and when it stops working.

	Args:
		key: The object name.

	Returns:
		The presigned URL and its expiry.

	Raises:
		StoreError: The URL could not be signed.
	"""
	options = settings.get()
	try:
		url = _signer().generate_presigned_url(
			'get_object',
			Params={'Bucket': options.s3_bucket, 'Key': key},
			ExpiresIn=options.clip_link_ttl_seconds,
		)
	except (
		botocore.exceptions.BotoCoreError,
		botocore.exceptions.ClientError,
	) as error:
		raise StoreError(f'could not sign {key}: {error}') from error
	expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
		seconds=options.clip_link_ttl_seconds
	)
	return url, expires
