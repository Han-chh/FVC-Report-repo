from pathlib import Path

import pytest

from data_prep.fcover_cache import SourceDownloadError, _official_https_url, acquire_official_cog, sha256_file


def test_official_cache_rejects_unapproved_source_route():
    with pytest.raises(SourceDownloadError, match="UNAPPROVED_SOURCE_ROUTE"):
        _official_https_url({"alternate": {"https": {"href": "https://example.invalid/fcover.tif"}}})


def test_official_cache_requires_a_bounded_retry_budget(tmp_path: Path):
    asset = {"href": "s3://eodata/path/file.tif", "alternate": {"https": {"href": "https://download.dataspace.copernicus.eu/file"}}}
    with pytest.raises(ValueError, match="DOWNLOAD_RETRIES_MUST_BE_POSITIVE"):
        acquire_official_cog("item", "fcover", asset, tmp_path, retries=0)


def test_checksum_is_deterministic_for_a_completed_file(tmp_path: Path):
    value = tmp_path / "complete.tif"; value.write_bytes(b"complete-source-fixture")
    assert sha256_file(value) == sha256_file(value)
