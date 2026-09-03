from applications.extensions import ma
from marshmallow import fields, validate


class DeptInSchema(ma.Schema):
    parentId = fields.Integer(required=False)
    deptName = fields.Str(required=True)
    leader = fields.Str(required=False, allow_none=True)
    status = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.OneOf(["0", "1"]),
    )
    sort = fields.Integer(required=False, allow_none=True)


class DeptOutSchema(ma.Schema):
    deptId = fields.Integer(attribute="id")
    parentId = fields.Integer(attribute="parent_id")
    deptName = fields.Str(attribute="dept_name")
    leader = fields.Str()
    status = fields.Str(validate=validate.OneOf(["0", "1"]))
    sort = fields.Integer()
