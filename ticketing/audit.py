from extensions import db
from models import AuditLog
from helpers import current_user_id


def record_audit(action, target_id):
    log = AuditLog(
        user_id=current_user_id(),
        action=action,
        target_id=target_id
    )
    db.session.add(log)
