"""
GCS 가중치 동기화 유틸리티

환경변수:
  BOSS_WEIGHTS_GCS_URI  — gs://bucket/path/to/trained_weights.json
                          설정 안 하면 GCS 기능 전체 비활성화 (로컬 파일 사용)

서빙 측:  download() → /tmp/boss_weights.json 캐시 → RLBossBot에 경로 전달
학습 측:  train_boss_bot.py 가 download() 후 학습, 완료 후 upload()
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_GCS_URI: str = os.environ.get("BOSS_WEIGHTS_GCS_URI", "")
_LOCAL_CACHE = Path("/tmp/boss_weights.json")


def enabled() -> bool:
    return bool(_GCS_URI)


def _parse_uri(uri: str) -> tuple[str, str]:
    """gs://bucket/blob → (bucket, blob)"""
    assert uri.startswith("gs://"), f"Invalid GCS URI: {uri}"
    bucket, _, blob = uri[5:].partition("/")
    return bucket, blob


def download(gcs_uri: str = "", dest: Path = _LOCAL_CACHE) -> Optional[Path]:
    """GCS에서 가중치를 다운로드한다. 실패 시 None 반환."""
    uri = gcs_uri or _GCS_URI
    if not uri:
        return None
    try:
        from google.cloud import storage  # type: ignore
        bucket_name, blob_name = _parse_uri(uri)
        client = storage.Client()
        blob = client.bucket(bucket_name).blob(blob_name)
        if not blob.exists():
            logger.warning("GCS weights not found: %s", uri)
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        blob.download_to_filename(str(dest))
        logger.info("Weights downloaded: %s → %s", uri, dest)
        return dest
    except ImportError:
        logger.warning("google-cloud-storage not installed; skipping GCS download")
        return None
    except Exception as exc:
        logger.error("GCS download failed: %s", exc)
        return None


def upload(src: Path, gcs_uri: str = "") -> bool:
    """가중치를 GCS에 atomic 업로드한다. (tmp → rename)"""
    uri = gcs_uri or _GCS_URI
    if not uri:
        return False
    if not src.exists():
        logger.error("upload: source file not found: %s", src)
        return False
    try:
        from google.cloud import storage  # type: ignore
        bucket_name, blob_name = _parse_uri(uri)
        client = storage.Client()
        bucket = client.bucket(bucket_name)

        # atomic: tmp 파일로 올린 뒤 rename
        tmp_name = blob_name + ".uploading"
        tmp_blob = bucket.blob(tmp_name)
        tmp_blob.upload_from_filename(str(src))
        bucket.copy_blob(tmp_blob, bucket, blob_name)
        tmp_blob.delete()

        logger.info("Weights uploaded: %s → %s", src, uri)
        return True
    except ImportError:
        logger.warning("google-cloud-storage not installed; skipping GCS upload")
        return False
    except Exception as exc:
        logger.error("GCS upload failed: %s", exc)
        return False


def get_generation(gcs_uri: str = "") -> Optional[int]:
    """변경 감지용 GCS object generation 반환. 실패/미설정 시 None."""
    uri = gcs_uri or _GCS_URI
    if not uri:
        return None
    try:
        from google.cloud import storage  # type: ignore
        bucket_name, blob_name = _parse_uri(uri)
        blob = storage.Client().bucket(bucket_name).get_blob(blob_name)
        return blob.generation if blob else None
    except Exception:
        return None


def local_cache_path() -> Path:
    return _LOCAL_CACHE
