from sqlalchemy import desc
from applications.extensions import db
from applications.common.storage import FileService
from applications.models import Photo
from applications.schemas import PhotoOutSchema
from applications.common.curd import model_to_dicts


def get_photo(page, limit):
    photo = Photo.query.order_by(desc(Photo.create_time)).paginate(page=page, per_page=limit, error_out=False)
    count = Photo.query.count()
    data = model_to_dicts(schema=PhotoOutSchema, data=photo.items)
    return data, count


def upload_one(photo, mime):
    stored = FileService.upload_file(
        photo,
        asset_type="IMAGE",
        purpose="LEGACY_IMAGE",
        retention_policy=FileService.PERMANENT,
        category="images/uploads",
        record=False,
    )
    photo_record = Photo(
        name=stored.original_filename,
        href=stored.public_url,
        mime=mime or stored.content_type,
        size=str(stored.file_size or 0),
        storage_path=stored.storage_path,
    )
    db.session.add(photo_record)
    db.session.commit()
    return {"src": stored.public_url}


def delete_photo_by_id(_id):
    photo_record = Photo.query.filter_by(id=_id).first()
    if not photo_record:
        return 0
    if photo_record.storage_path:
        FileService.delete_storage(photo_record.storage_path)
    photo = Photo.query.filter_by(id=_id).delete()
    db.session.commit()
    return photo
