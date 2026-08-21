from applications.extensions import ma
from marshmallow import fields
from applications.models import Dept


# 用户models的序列化类
class UserOutSchema(ma.Schema):
    id = fields.Integer()
    username = fields.Str()
    realname = fields.Str()
    enable = fields.Integer()
    create_at = fields.DateTime()
    update_at = fields.DateTime()
    dept = fields.Method("get_dept")
    roles = fields.Method("get_roles")

    def get_dept(self, obj):
        if obj.dept_id != None:
            return Dept.query.filter_by(id=obj.dept_id).first().dept_name
        else:
            return None

    def get_roles(self, obj):
        roles = obj.role.all() if hasattr(obj.role, "all") else obj.role
        return "、".join(role.name for role in roles if role and role.name)
