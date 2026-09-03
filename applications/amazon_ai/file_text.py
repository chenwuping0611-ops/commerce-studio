import os
import tempfile

from flask import current_app, has_app_context

from applications.common.storage import FileService, StorageError
from applications.common.scope import can_access_asset
from applications.models import StudioAsset


DEFAULT_MAX_TEXT_BYTES = 120000
SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".xls",
    ".xlsx",
    ".xlsm",
    ".json",
    ".html",
    ".htm",
}


def _limit_utf8(value, maximum):
    encoded = str(value or "").encode("utf-8")
    if len(encoded) <= maximum:
        return str(value or "")
    return encoded[:maximum].decode("utf-8", errors="ignore").rstrip()


def _download_asset(asset):
    """Download a GoFastDFS asset to a local temporary file for parsing."""

    if not asset or asset.status != "ACTIVE":
        raise StorageError("输入文件不存在或已经失效")
    if asset.expires_at:
        from datetime import datetime

        if asset.expires_at <= datetime.now():
            raise StorageError("输入文件已经过期")

    suffix = os.path.splitext(asset.original_filename or "")[1].lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise StorageError(
            "Amazon AI 仅支持 MD、TXT、CSV、TSV、XLS、XLSX、XLSM、JSON、HTML 文件"
        )

    client = FileService.client()
    maximum = int(client.maximum_size or 0)
    response = None
    temporary_path = None
    try:
        response = FileService.download_response(asset)
        with tempfile.NamedTemporaryFile(
            prefix="amazon-ai-",
            suffix=suffix,
            delete=False,
        ) as temporary:
            temporary_path = temporary.name
            total = 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if maximum and total > maximum:
                    raise StorageError("输入文件超过系统允许的大小")
                temporary.write(chunk)
        return temporary_path
    except Exception:
        if temporary_path:
            try:
                os.remove(temporary_path)
            except OSError:
                pass
        raise
    finally:
        if response is not None:
            response.close()


def read_text_file(local_path, max_bytes=DEFAULT_MAX_TEXT_BYTES):
    """Read TXT directly with open(), as required by the Amazon workflow."""

    with open(local_path, "r", encoding="utf-8-sig") as file:
        return _limit_utf8(file.read(), max_bytes)


def read_excel_file(local_path, max_bytes=DEFAULT_MAX_TEXT_BYTES):
    """Convert every Excel worksheet into bounded plain text."""

    try:
        import pandas
    except ImportError as exc:
        raise StorageError(
            "Excel 文本分析需要 pandas 和 openpyxl，请先安装依赖"
        ) from exc

    sheets = pandas.read_excel(local_path, sheet_name=None)
    parts = []
    for sheet_name, dataframe in sheets.items():
        parts.append(
            f"工作表：{sheet_name}\n"
            + dataframe.to_string(index=False)
        )
    return _limit_utf8("\n\n".join(parts), max_bytes)


def read_csv_file(local_path, max_bytes=DEFAULT_MAX_TEXT_BYTES):
    """Convert CSV input into the same bounded plain-text format as Excel."""

    try:
        import pandas
    except ImportError as exc:
        raise StorageError(
            "CSV 文本分析需要 pandas，请先安装依赖"
        ) from exc

    dataframe = pandas.read_csv(local_path)
    return _limit_utf8(dataframe.to_string(index=False), max_bytes)


def read_tsv_file(local_path, max_bytes=DEFAULT_MAX_TEXT_BYTES):
    """Convert tab-separated exports into the same bounded plain text format."""

    try:
        import pandas
    except ImportError as exc:
        raise StorageError(
            "TSV 文本分析需要 pandas，请先安装依赖"
        ) from exc

    dataframe = pandas.read_csv(local_path, sep="\t")
    return _limit_utf8(dataframe.to_string(index=False), max_bytes)


def read_json_file(local_path, max_bytes=DEFAULT_MAX_TEXT_BYTES):
    """Read JSON while keeping its structure visible to the model."""

    with open(local_path, "r", encoding="utf-8-sig") as file:
        value = file.read()
    try:
        import json

        value = json.dumps(json.loads(value), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        pass
    return _limit_utf8(value, max_bytes)


def read_asset_text(asset, max_bytes=DEFAULT_MAX_TEXT_BYTES):
    """Download one stored asset and turn it into model-ready text."""

    suffix = os.path.splitext(asset.original_filename or "")[1].lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise StorageError(
            "Amazon AI 仅支持 MD、TXT、CSV、TSV、XLS、XLSX、XLSM、JSON、HTML 文件"
        )
    local_path = _download_asset(asset)
    try:
        if suffix in {".txt", ".md", ".html", ".htm"}:
            return read_text_file(local_path, max_bytes=max_bytes)
        if suffix == ".csv":
            return read_csv_file(local_path, max_bytes=max_bytes)
        if suffix == ".tsv":
            return read_tsv_file(local_path, max_bytes=max_bytes)
        if suffix == ".json":
            return read_json_file(local_path, max_bytes=max_bytes)
        return read_excel_file(local_path, max_bytes=max_bytes)
    finally:
        try:
            os.remove(local_path)
        except OSError:
            pass


def read_assets_text(
    asset_ids,
    max_bytes=DEFAULT_MAX_TEXT_BYTES,
    user=None,
):
    """Read active Amazon input assets in the caller-provided order."""

    ids = []
    for value in asset_ids or []:
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item not in ids:
            ids.append(item)

    if not ids:
        return ""
    if has_app_context():
        configured_limit = current_app.config.get("AMAZON_AI_MAX_TEXT_BYTES")
        if configured_limit:
            max_bytes = min(max_bytes, int(configured_limit))
        max_files = int(
            current_app.config.get("AMAZON_AI_MAX_INPUT_FILES")
            or len(ids)
        )
        if len(ids) > max_files:
            raise StorageError(
                f"一次 Amazon AI 任务最多使用 {max_files} 个输入文件"
            )

    assets_by_id = {
        asset.id: asset
        for asset in StudioAsset.query.filter(
            StudioAsset.id.in_(ids),
            StudioAsset.purpose == "AMAZON_INPUT",
            StudioAsset.status == "ACTIVE",
        ).all()
    }
    parts = []
    remaining = max_bytes
    for asset_id in ids:
        asset = assets_by_id.get(asset_id)
        if not asset or not can_access_asset(user, asset):
            raise StorageError(f"输入文件 {asset_id} 不存在或用途不正确")
        if remaining <= 0:
            break
        text = read_asset_text(asset, max_bytes=remaining)
        if text:
            parts.append(
                f"文件：{asset.original_filename or asset_id}\n{text}"
            )
            remaining -= len(text.encode("utf-8"))
    return _limit_utf8("\n\n".join(parts), max_bytes)
