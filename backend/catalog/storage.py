import asyncio
import io
import warnings

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from PIL import Image, UnidentifiedImageError

from catalog.config import Settings


class InvalidPhoto(ValueError):
    pass


def normalize_photo(data: bytes, max_bytes: int) -> bytes:
    if not data or len(data) > max_bytes:
        raise InvalidPhoto("Нужна фотография размером до 10 МБ.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as original:
                if original.width * original.height > 20_000_000:
                    raise InvalidPhoto("Слишком большое разрешение фотографии.")
                original.load()
                result = io.BytesIO()
                original.convert("RGB").save(result, format="JPEG", quality=90)
                value = result.getvalue()
                if len(value) > max_bytes:
                    raise InvalidPhoto("Фотография после обработки превышает лимит размера.")
                return value
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise InvalidPhoto("Не удалось прочитать фотографию. Отправьте другое фото.") from exc


class ObjectStore:
    def __init__(self, settings: Settings):
        self.bucket = settings.s3_bucket
        self.max_bytes = settings.max_photo_bytes
        self.client = boto3.client(
            "s3", endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            region_name="us-east-1",
            config=Config(connect_timeout=3, read_timeout=10,
                          retries={"max_attempts": 2}, s3={"addressing_style": "path"}),
        )

    def initialize(self) -> None:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if str(exc.response["Error"]["Code"]) not in {"404", "NoSuchBucket"}:
                raise
            try:
                self.client.create_bucket(Bucket=self.bucket)
            except ClientError as create_exc:
                if create_exc.response["Error"]["Code"] != "BucketAlreadyOwnedByYou":
                    raise

    async def ready(self) -> None:
        await asyncio.to_thread(self.client.head_bucket, Bucket=self.bucket)

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(
            self.client.put_object, Bucket=self.bucket, Key=key,
            Body=data, ContentType="image/jpeg",
        )

    async def get(self, key: str) -> bytes:
        def read():
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
            with obj["Body"] as body:
                data = body.read(self.max_bytes + 1)
            if len(data) > self.max_bytes:
                raise ValueError("Object exceeds image limit")
            return data
        return await asyncio.to_thread(read)
